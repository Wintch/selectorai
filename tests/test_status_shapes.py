#!/usr/bin/env python3
"""Plain-python3 test: feed each provider's status() function canned CLI
output (never a real subprocess — subprocess.run is monkeypatched for the
whole test) and assert the returned dict has the documented shape,
including the "kind" field (see sai/providers/base.py's contract
docstring). Also exercises Codex's cached-ratelimit path through a
temporary STATE_DIR, proving sai.paths.STATE_DIR is patchable per-call
(see sai/providers/codex.py's status(), which reads `paths.STATE_DIR`
at call time rather than a name bound at import time).

Never touches ~/.selectorai and never subprocesses a real AI CLI.
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sai.paths as paths  # noqa: E402
from sai.providers import antigravity, claude, codex, grok  # noqa: E402


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


def assert_status_shape(label, st):
    check(f"{label}: is dict", isinstance(st, dict))
    check(f"{label}: has pct_used/rows/note/kind keys", set(st.keys()) == {"pct_used", "rows", "note", "kind"})
    check(f"{label}: kind is a known value", st["kind"] in ("ok", "auth-needed", "not-checked", "no-usage-api"))
    check(f"{label}: rows is a list", isinstance(st["rows"], list))
    for row in st["rows"]:
        check(f"{label}: row is a 3-tuple", len(row) == 3)


class _FakeRun:
    """Drop-in for subprocess.run that returns canned stdout for a given
    argv prefix and refuses (raises) anything unrecognized — so a bug that
    would otherwise shell out to a real `claude`/`codex`/`agy`/`grok`
    fails the test loudly instead of silently popping a browser."""

    def __init__(self, canned):
        self.canned = canned  # {tuple(argv): stdout}
        self.calls = []

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(cmd)
        key = tuple(cmd) if isinstance(cmd, list) else cmd
        if key not in self.canned:
            raise AssertionError(f"unexpected subprocess.run call, would hit a real CLI: {cmd!r}")

        class _Result:
            stdout = self.canned[key]
            returncode = 0

        return _Result()


def test_claude_ok(monkeypatch_run):
    # Real confirmed format (see sai/providers/claude.py's status()):
    # "Current session: N% used ... resets <text>" lines.
    out = (
        "Current session: 42% used, resets Aug 21, 4am (America/Argentina/Buenos_Aires)\n"
        "Current week (all models): 10% used, resets Aug 24, 9am (America/Argentina/Buenos_Aires)\n"
    )
    monkeypatch_run({("claude", "-p", "/usage"): out})
    st = claude.status()
    assert_status_shape("claude ok", st)
    check("claude ok: kind == ok", st["kind"] == "ok")
    check("claude ok: pct_used == 42", st["pct_used"] == 42)
    check("claude ok: 2 rows", len(st["rows"]) == 2)


def test_claude_login_expired(monkeypatch_run):
    monkeypatch_run({("claude", "-p", "/usage"): "Please run /login to authenticate.\n"})
    st = claude.status()
    assert_status_shape("claude auth-needed", st)
    check("claude auth-needed: kind == auth-needed", st["kind"] == "auth-needed")
    check("claude auth-needed: pct_used is None", st["pct_used"] is None)
    check("claude auth-needed: no rows", st["rows"] == [])


def test_antigravity_ok(monkeypatch_run):
    # Real confirmed format (tab-separated, "% remaining"):
    #   Gemini Models\tWeekly Limit Remaining\t62%\t2026-08-22T23:58:13Z
    out = (
        "Gemini Models\tWeekly Limit Remaining\t62%\t2026-08-22T23:58:13Z\n"
        "Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-08-24T08:15:03Z\n"
    )
    monkeypatch_run({("agy", "-p", "/usage"): out})
    antigravity.set_check_enabled(True)
    try:
        st = antigravity.status()
    finally:
        antigravity.set_check_enabled(False)
    assert_status_shape("antigravity ok", st)
    check("antigravity ok: kind == ok", st["kind"] == "ok")
    # 62% remaining -> 38% used; 100% remaining -> 0% used; worst-case max.
    check("antigravity ok: pct_used == 38", st["pct_used"] == 38)
    check("antigravity ok: 2 rows", len(st["rows"]) == 2)


def test_antigravity_not_checked():
    antigravity.set_check_enabled(False)
    st = antigravity.status()
    assert_status_shape("antigravity not-checked", st)
    check("antigravity not-checked: kind == not-checked", st["kind"] == "not-checked")
    check("antigravity not-checked: pct_used is None", st["pct_used"] is None)


def test_antigravity_no_usage(monkeypatch_run):
    monkeypatch_run({("agy", "-p", "/usage"): "not authenticated\n"})
    antigravity.set_check_enabled(True)
    try:
        st = antigravity.status()
    finally:
        antigravity.set_check_enabled(False)
    assert_status_shape("antigravity auth-needed (no usage)", st)
    check("antigravity no-usage: kind == auth-needed", st["kind"] == "auth-needed")


def test_grok_not_checked():
    grok.set_check_enabled(False)
    st = grok.status()
    assert_status_shape("grok not-checked", st)
    check("grok not-checked: kind == not-checked", st["kind"] == "not-checked")
    check("grok not-checked: pct_used is None", st["pct_used"] is None)


# Fake tmux pane text, same shape confirmed live 2026-08-18 (Grok Build
# 1.0.5, free grok.com account) via `/info` + Tab + Tab inside a real
# tmux session — see sai/providers/grok.py's _live_usage_limit()
# docstring. The "│ ❯" substring is the ready-prompt marker
# _live_usage_limit polls for; "Weekly limit"/"%"/"Resets:" are what it
# regex-searches for once ready.
_GROK_PANE_WITH_USAGE = (
    "  │  Weekly limit (Free)                        │\n"
    "  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  37%          │\n"
    "  │  Resets: August 21, 21:00                    │\n"
    "  │ ❯                                             │\n"
)
_GROK_PANE_NO_USAGE = "  │ ❯                                             │\n"


def test_grok_ok(monkeypatch_run):
    session_name = grok._PROBE_SESSION
    monkeypatch_run({
        ("tmux", "kill-session", "-t", session_name): "",
        ("tmux", "new-session", "-d", "-s", session_name, "-x", "200", "-y", "50", "grok"): "",
        ("tmux", "capture-pane", "-t", session_name, "-p"): _GROK_PANE_WITH_USAGE,
        ("tmux", "send-keys", "-t", session_name, "/info"): "",
        ("tmux", "send-keys", "-t", session_name, "Enter"): "",
        ("tmux", "send-keys", "-t", session_name, "Escape"): "",
    })
    orig_available = grok.session.available
    orig_sleep = grok.time.sleep
    grok.session.available = lambda: True
    grok.time.sleep = lambda s: None  # this test's pane is "ready" from the first capture, so nothing waits on real time
    grok.set_check_enabled(True)
    try:
        st = grok.status()
    finally:
        grok.session.available = orig_available
        grok.time.sleep = orig_sleep
        grok.set_check_enabled(False)
    assert_status_shape("grok ok", st)
    check("grok ok: kind == ok", st["kind"] == "ok")
    check("grok ok: pct_used == 37", st["pct_used"] == 37)
    check("grok ok: 1 row", len(st["rows"]) == 1)
    check("grok ok: row label is grok's own text", st["rows"][0][0] == "Weekly limit (Free)")
    check("grok ok: reset text includes grok's own date", "August 21, 21:00" in st["rows"][0][2])


def test_grok_no_usage(monkeypatch_run):
    session_name = grok._PROBE_SESSION
    monkeypatch_run({
        ("tmux", "kill-session", "-t", session_name): "",
        ("tmux", "new-session", "-d", "-s", session_name, "-x", "200", "-y", "50", "grok"): "",
        ("tmux", "capture-pane", "-t", session_name, "-p"): _GROK_PANE_NO_USAGE,
        ("tmux", "send-keys", "-t", session_name, "/info"): "",
        ("tmux", "send-keys", "-t", session_name, "Enter"): "",
        ("tmux", "send-keys", "-t", session_name, "Tab"): "",
        ("tmux", "send-keys", "-t", session_name, "Escape"): "",
    })
    orig_available = grok.session.available
    orig_sleep = grok.time.sleep
    grok.session.available = lambda: True
    grok.time.sleep = lambda s: None
    grok.set_check_enabled(True)
    try:
        st = grok.status()
    finally:
        grok.session.available = orig_available
        grok.time.sleep = orig_sleep
        grok.set_check_enabled(False)
    assert_status_shape("grok no-usage", st)
    check("grok no-usage: kind == no-usage-api", st["kind"] == "no-usage-api")
    check("grok no-usage: pct_used is None", st["pct_used"] is None)
    check("grok no-usage: no rows", st["rows"] == [])


def test_grok_tmux_missing():
    orig_available = grok.session.available
    grok.session.available = lambda: False
    grok.set_check_enabled(True)
    try:
        st = grok.status()
    finally:
        grok.session.available = orig_available
        grok.set_check_enabled(False)
    assert_status_shape("grok no-tmux", st)
    check("grok no-tmux: kind == no-usage-api", st["kind"] == "no-usage-api")


def test_codex_no_saved_state():
    with tempfile.TemporaryDirectory() as tmp:
        orig_state_dir = paths.STATE_DIR
        paths.STATE_DIR = Path(tmp)
        try:
            st = codex.status()
        finally:
            paths.STATE_DIR = orig_state_dir
    assert_status_shape("codex no-saved-state", st)
    check("codex no-saved-state: kind == no-usage-api", st["kind"] == "no-usage-api")
    check("codex no-saved-state: pct_used is None", st["pct_used"] is None)


def test_codex_cached_ratelimit_active():
    with tempfile.TemporaryDirectory() as tmp:
        orig_state_dir = paths.STATE_DIR
        paths.STATE_DIR = Path(tmp)
        try:
            future = int(time.time()) + 3600
            (paths.STATE_DIR / "codex.ratelimited.msg").write_text("Aug 21st, 2026 4:00 AM")
            (paths.STATE_DIR / "codex.ratelimited.until").write_text(str(future))
            st = codex.status()
        finally:
            paths.STATE_DIR = orig_state_dir
    assert_status_shape("codex cached ratelimit (active)", st)
    check("codex cached ratelimit: kind == ok", st["kind"] == "ok")
    check("codex cached ratelimit: pct_used == 100", st["pct_used"] == 100)
    check("codex cached ratelimit: 1 row", len(st["rows"]) == 1)


def test_codex_cached_ratelimit_expired_self_clears():
    with tempfile.TemporaryDirectory() as tmp:
        orig_state_dir = paths.STATE_DIR
        paths.STATE_DIR = Path(tmp)
        try:
            past = int(time.time()) - 3600
            msg_f = paths.STATE_DIR / "codex.ratelimited.msg"
            until_f = paths.STATE_DIR / "codex.ratelimited.until"
            msg_f.write_text("some past date")
            until_f.write_text(str(past))
            st = codex.status()
            check("codex expired ratelimit: kind == no-usage-api", st["kind"] == "no-usage-api")
            check("codex expired ratelimit: msg file cleared", not msg_f.exists())
            check("codex expired ratelimit: until file cleared", not until_f.exists())
        finally:
            paths.STATE_DIR = orig_state_dir


def test_record_and_clear_codex_ratelimit_roundtrip():
    """record_codex_ratelimit/clear_codex_ratelimit are unreachable from
    any current call site (launches are exec'd — see sai/providers/codex.py's
    comment) but are kept, and must still work correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        orig_state_dir = paths.STATE_DIR
        paths.STATE_DIR = Path(tmp)
        try:
            codex.record_codex_ratelimit("You've hit your usage limit. try again at Sep 14th, 2026 10:37 AM.")
            msg_f = paths.STATE_DIR / "codex.ratelimited.msg"
            check("record: msg file written", msg_f.exists())
            check("record: msg content", msg_f.read_text().startswith("Sep 14th, 2026"))
            codex.clear_codex_ratelimit()
            check("clear: msg file removed", not msg_f.exists())
        finally:
            paths.STATE_DIR = orig_state_dir


def main():
    print("test_status_shapes:")
    fake = _FakeRun({})
    orig_run = subprocess.run

    def install_canned(canned):
        fake.canned = canned
        subprocess.run = fake

    subprocess.run = fake  # blanket install; real CLI calls would raise via _FakeRun

    try:
        test_claude_ok(install_canned)
        test_claude_login_expired(install_canned)
        test_antigravity_ok(install_canned)
        test_antigravity_no_usage(install_canned)
        test_grok_ok(install_canned)
        test_grok_no_usage(install_canned)
    finally:
        subprocess.run = orig_run

    # These don't need the fake at all (antigravity/grok gate off never
    # calls subprocess; grok tmux-missing short-circuits before any
    # subprocess call; codex reads only from disk state).
    test_antigravity_not_checked()
    test_grok_not_checked()
    test_grok_tmux_missing()
    test_codex_no_saved_state()
    test_codex_cached_ratelimit_active()
    test_codex_cached_ratelimit_expired_self_clears()
    test_record_and_clear_codex_ratelimit_roundtrip()

    print("test_status_shapes: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
