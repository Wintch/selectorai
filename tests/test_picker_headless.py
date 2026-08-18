#!/usr/bin/env python3
"""Headless test of the Textual picker, run through Textual's own
`app.run_test()` pilot (no real terminal). Self-skips (prints SKIP, exits
0) when textual isn't importable, so `python3 tests/run_tests.py` (plain
interpreter) still passes — this test only really runs under
~/.selectorai/venv/bin/python3 (STATE_DIR, see sai/paths.py), which has
textual installed.

Safety: action_cycle_lang/action_cycle_theme (exercised below) write the
user's REAL ~/.selectorai/lang and ~/.selectorai/theme files — there is no
way to intercept that without changing production code just for a test.
So this file reads both files' original bytes first and restores them
(or removes them, if they didn't exist) in a finally block, no matter how
the test ends. Never touches any other file under ~/.selectorai.
"""
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    import textual  # noqa: F401
except ImportError:
    print("test_picker_headless: SKIP (textual not importable on this interpreter — "
          "expected under plain python3; run under ~/.selectorai/venv/bin/python3 "
          "to actually exercise this test)")
    sys.exit(0)

from sai.i18n import set_lang, t  # noqa: E402
from sai.paths import LANG_FILE, THEME_FILE  # noqa: E402
from sai.ui import picker  # noqa: E402

PROVIDER_LIST = ["claude", "codex", "antigravity", "grok"]

# Canned status dicts — real shape (see sai/providers/base.py's contract
# docstring). Deliberately mixes all three health states so the sectioned
# OptionList (see sai/ui/picker.py's compose()) has something real to
# section: claude ONLINE, grok WARNING (pct 85, >= the 80 boundary),
# codex OFFLINE (pct 100, quota exhausted), antigravity OFFLINE
# (auth-needed) — not meant to represent real provider behavior.
STUB_STATUSES = {
    "claude": {"pct_used": 42, "rows": [("Session (5h)", 42, "in 3h")], "note": None, "kind": "ok"},
    "codex": {"pct_used": 100, "rows": [("Usage", 100, "in 1h")], "note": None, "kind": "ok"},
    "antigravity": {"pct_used": None, "rows": [], "note": "Sign-in needed.", "kind": "auth-needed"},
    "grok": {"pct_used": 85, "rows": [("Usage", 85, "in 2h")], "note": None, "kind": "ok"},
}

# Empty on purpose: none of the scenarios below are about service-status
# fold-in (that's tests/test_health_service.py's job) — this file only
# needs classify() to behave exactly as it did before service_state
# existed, and {}.get(p) -> None gives it precisely that "no signal" case.
STUB_SERVICE_STATES = {}

THEME_PATH = REPO_ROOT / "themes" / "mother.tcss"

# Fake reattach descriptor — same shape sai.cli._reattach_descriptor()
# builds from real sai.session tmux calls (see that function's docstring),
# faked here directly since this file drives _build_app in isolation, the
# same way STUB_STATUSES fakes provider status() output instead of really
# calling claude/codex/etc.
STUB_REATTACH = {
    "windows": [("claude", "2m ago"), ("codex", "1h ago")],
    "peek_lines": ["$ claude --permission-mode auto", "Working on the thing...", "165 tokens"],
}


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


async def _test_options_and_navigation():
    from textual.widgets import OptionList, Static

    app = picker._build_app(PROVIDER_LIST, STUB_STATUSES, STUB_SERVICE_STATES, THEME_PATH)
    async with app.run_test() as pilot:
        option_list = app.query_one("#picker", OptionList)
        # 4 providers + 1 disabled separator row: codex (quota-exhausted)
        # and antigravity (auth-needed) are OFFLINE per STUB_STATUSES, so
        # they land after the "health_section_offline" separator.
        check("5 rows mounted (4 providers + 1 separator)", option_list.option_count == 5)
        check("first option highlighted on mount", option_list.highlighted == 0)
        check(
            "index 0 is claude (ONLINE providers sort before the separator)",
            option_list.get_option_at_index(0).id == "claude",
        )
        check(
            "index 1 is grok, the WARNING provider, and its label shows ⚠",
            option_list.get_option_at_index(1).id == "grok"
            and "⚠" in option_list.get_option_at_index(1).prompt,
        )
        check(
            "index 2 is the disabled offline-section separator, unselectable",
            option_list.get_option_at_index(2).id is None
            and option_list.get_option_at_index(2).disabled,
        )

        detail_before = str(app.query_one("#detail", Static).render())
        check("detail panel shows claude's row on mount", "Session (5h)" in detail_before)
        check("detail panel's health line says ONLINE for claude", t("health_state_online") in detail_before)

        await pilot.press("down")
        check("arrow-down moves highlight to index 1 (grok)", option_list.highlighted == 1)
        detail_after = str(app.query_one("#detail", Static).render())
        check("arrow-down changed the detail panel", detail_after != detail_before)
        check("detail panel says WARNING for grok", t("health_state_warning") in detail_after)
        check("detail panel gives the low-quota reason for grok", t("health_reason_low_quota") in detail_after)

        # The separator (index 2) must not be reachable by arrow
        # navigation: one more "down" from grok (index 1) has to skip
        # straight over it and land on codex (index 3), the first OFFLINE
        # provider.
        await pilot.press("down")
        check(
            "down from grok skips the disabled separator, landing on codex (index 3)",
            option_list.highlighted == 3,
        )
        detail_offline = str(app.query_one("#detail", Static).render())
        check("detail panel says OFFLINE for codex", t("health_state_offline") in detail_offline)
        check("detail panel gives the quota reason for codex", t("health_reason_quota") in detail_offline)

        # Deliberate: OFFLINE providers stay normal, selectable options —
        # our data can be stale, so Enter must still launch one.
        await pilot.press("enter")
        check("enter on an OFFLINE provider still returns its id (codex)", app.chosen == "codex")


async def _test_reattach_offer():
    from textual.widgets import OptionList, Static

    app = picker._build_app(PROVIDER_LIST, STUB_STATUSES, STUB_SERVICE_STATES, THEME_PATH, STUB_REATTACH)
    async with app.run_test() as pilot:
        option_list = app.query_one("#picker", OptionList)
        check(
            "reattach offer adds one row on top of the usual 5 (4 providers + separator)",
            option_list.option_count == 6,
        )
        first = option_list.get_option_at_index(0)
        check("reattach row is first and carries the _REATTACH sentinel id", first.id == picker._REATTACH)
        check(
            "reattach row's label mentions both window names and the freshest ago string",
            "claude" in first.prompt and "codex" in first.prompt and "2m ago" in first.prompt,
        )
        check(
            "index 1 is still claude, the top provider (reattach didn't push it past the separator)",
            option_list.get_option_at_index(1).id == "claude",
        )

        detail = str(app.query_one("#detail", Static).render())
        check("detail panel shows the peek lines on mount (reattach highlighted first)", "165 tokens" in detail)
        check(
            "detail panel does not show provider stats for the reattach row",
            "Session (5h)" not in detail,
        )

        await pilot.press("enter")
        check("enter on the reattach row returns the _REATTACH sentinel, not a provider id", app.chosen == picker._REATTACH)


async def _test_cycle_lang():
    app = picker._build_app(PROVIDER_LIST, STUB_STATUSES, STUB_SERVICE_STATES, THEME_PATH)
    exit_results = []
    orig_exit = app.exit

    def _capture_exit(result=None):
        exit_results.append(result)
        return orig_exit(result=result)

    app.exit = _capture_exit
    async with app.run_test() as pilot:
        await pilot.press("l")
    check("L returns the restart-lang sentinel", exit_results and exit_results[-1] == picker._RESTART_LANG)


async def _test_cycle_theme():
    app = picker._build_app(PROVIDER_LIST, STUB_STATUSES, STUB_SERVICE_STATES, THEME_PATH)
    exit_results = []
    orig_exit = app.exit

    def _capture_exit(result=None):
        exit_results.append(result)
        return orig_exit(result=result)

    app.exit = _capture_exit
    async with app.run_test() as pilot:
        await pilot.press("t")
    check("T returns the restart-theme sentinel", exit_results and exit_results[-1] == picker._RESTART_THEME)


def main():
    print("test_picker_headless:")

    orig_lang = LANG_FILE.read_text() if LANG_FILE.exists() else None
    orig_theme = THEME_FILE.read_text() if THEME_FILE.exists() else None
    orig_lang_module_state = None
    try:
        from sai.i18n import get_lang

        orig_lang_module_state = get_lang()
    except Exception:
        pass

    try:
        asyncio.run(_test_options_and_navigation())

        # Reattach offer: pure rendering + selection, no key that touches
        # LANG_FILE/THEME_FILE — assert both are exactly as this test found
        # them (see module docstring: those two files are the only ones
        # this test suite is allowed to touch, and only via the L/T
        # actions exercised below).
        pre_lang = LANG_FILE.read_text() if LANG_FILE.exists() else None
        pre_theme = THEME_FILE.read_text() if THEME_FILE.exists() else None
        asyncio.run(_test_reattach_offer())
        post_lang = LANG_FILE.read_text() if LANG_FILE.exists() else None
        post_theme = THEME_FILE.read_text() if THEME_FILE.exists() else None
        check("reattach offer test didn't touch LANG_FILE", pre_lang == post_lang)
        check("reattach offer test didn't touch THEME_FILE", pre_theme == post_theme)

        asyncio.run(_test_cycle_lang())
        check("lang file was written by the L action", LANG_FILE.exists())
        asyncio.run(_test_cycle_theme())
        check("theme file was written by the T action", THEME_FILE.exists())
    finally:
        # Restore the user's real preferences byte-for-byte — never leave
        # this test's L/T key presses as a lasting side effect.
        if orig_lang is None:
            LANG_FILE.unlink(missing_ok=True)
        else:
            LANG_FILE.write_text(orig_lang)
        if orig_theme is None:
            THEME_FILE.unlink(missing_ok=True)
        else:
            THEME_FILE.write_text(orig_theme)
        if orig_lang_module_state is not None:
            set_lang(orig_lang_module_state)
        print(f"  (restored {LANG_FILE} and {THEME_FILE} to their original contents)")

    print("test_picker_headless: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
