#!/usr/bin/env python3
"""Plain-python3 test: sai.models (the `models` subcommand + read-only
cache helpers) and each provider's list_models().

Safety, matching test_status_shapes.py's approach exactly (this machine
actually has claude/codex/agy/grok installed — see ABSOLUTE SAFETY RULES
in the task this was built from): subprocess.run is monkeypatched for the
ENTIRE file with a fake that raises on anything not explicitly canned, so
a bug that would otherwise shell out to a real `agy`/`grok` binary fails
the test loudly instead of silently making a live call (which for
antigravity/grok's `models` subcommand could pop a real OAuth browser
window, same failure class as `agy -p /usage`).

Cache tests point sai.cache.CACHE_FILE (not sai.paths.CACHE_FILE — see
sai/cache.py, which binds CACHE_FILE at import time via `from sai.paths
import CACHE_FILE`, so only patching the name actually used,
sai.cache.CACHE_FILE, has any effect) at a tempdir and restore it in a
finally block. Never touches ~/.selectorai.
"""
import io
import json
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sai.cache as cache_mod  # noqa: E402
import sai.models as models  # noqa: E402
from sai import providers  # noqa: E402
from sai.i18n import t  # noqa: E402
from sai.providers import antigravity, claude, codex, grok  # noqa: E402
from sai.providers.base import parse_model_lines  # noqa: E402


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


class _FakeRun:
    """Same shape as test_status_shapes.py's _FakeRun: canned stdout per
    argv, raises on anything unrecognized."""

    def __init__(self, canned):
        self.canned = canned
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


# ---------------------------------------------------------------------------
# parse_model_lines — pure function, no subprocess involved
# ---------------------------------------------------------------------------


def test_parse_model_lines_strips_and_keeps_names():
    out = "  claude-fable  \nopus\n\nsonnet\n"
    check(
        "blank lines dropped, real lines stripped and kept",
        parse_model_lines(out) == ["claude-fable", "opus", "sonnet"],
    )


def test_parse_model_lines_drops_decoration():
    out = "----\nmodel-a\n====\nmodel-b\n~~~~\n"
    check("pure-punctuation decoration lines dropped", parse_model_lines(out) == ["model-a", "model-b"])


def test_parse_model_lines_drops_known_headers():
    out = "Available models:\nmodel-a\nName\nmodel-b\nmodels:\nmodel-c\n"
    check(
        "known header words dropped case-insensitively",
        parse_model_lines(out) == ["model-a", "model-b", "model-c"],
    )


def test_parse_model_lines_drops_short_colon_headers():
    out = "Claude models:\nmodel-a\nGPT models:\nmodel-b\n"
    check(
        "short lines ending in ':' treated as section headers, dropped",
        parse_model_lines(out) == ["model-a", "model-b"],
    )


def test_parse_model_lines_empty_input():
    check("empty string -> empty list", parse_model_lines("") == [])
    check("whitespace-only -> empty list", parse_model_lines("   \n  \n") == [])


# ---------------------------------------------------------------------------
# Per-provider list_models()
# ---------------------------------------------------------------------------


def test_claude_list_models_is_static():
    result = claude.list_models()
    check("claude.list_models() returns the documented static alias list",
          result == ["fable", "opus", "sonnet", "haiku"])
    check("claude.MODELS_STATIC is True", claude.MODELS_STATIC is True)
    check(
        "returned list is a copy, not the module constant itself",
        result is not claude._STATIC_MODEL_ALIASES,
    )


def test_codex_list_models_is_none():
    check("codex has no models subcommand -> None", codex.list_models() is None)
    check("codex has no MODELS_STATIC marker (defaults False via getattr)",
          getattr(codex, "MODELS_STATIC", False) is False)


def test_antigravity_list_models_ok(monkeypatch_run):
    # Format is UNVERIFIED (see antigravity.py's list_models() docstring) —
    # this exercises the defensive parsing end-to-end through the real
    # subprocess call site, header/decoration lines included on purpose.
    out = "Available models:\n----\ngemini-2.5-pro\ngemini-2.5-flash\n"
    monkeypatch_run({("agy", "models"): out})
    result = antigravity.list_models()
    check("antigravity.list_models() parses real model names, drops header/decoration",
          result == ["gemini-2.5-pro", "gemini-2.5-flash"])


def test_antigravity_list_models_subprocess_failure_is_none(monkeypatch_run):
    def _raise(*a, **k):
        raise OSError("simulated failure")

    orig = subprocess.run
    subprocess.run = _raise
    try:
        check("antigravity.list_models(): any exception -> None, no raise", antigravity.list_models() is None)
    finally:
        subprocess.run = orig


def test_grok_list_models_ok(monkeypatch_run):
    out = "grok-4\ngrok-4-fast\n"
    monkeypatch_run({("grok", "models"): out})
    result = grok.list_models()
    check("grok.list_models() parses real model names", result == ["grok-4", "grok-4-fast"])


def test_grok_list_models_subprocess_failure_is_none():
    orig = subprocess.run

    def _raise(*a, **k):
        raise OSError("simulated failure")

    subprocess.run = _raise
    try:
        check("grok.list_models(): any exception -> None, no raise", grok.list_models() is None)
    finally:
        subprocess.run = orig


def test_providers_list_models_dispatches(monkeypatch_run):
    monkeypatch_run({("agy", "models"): "model-x\n"})
    check("providers.list_models('claude') dispatches to claude module",
          providers.list_models("claude") == ["fable", "opus", "sonnet", "haiku"])
    check("providers.list_models('codex') dispatches to codex module", providers.list_models("codex") is None)
    check("providers.list_models('antigravity') dispatches to antigravity module",
          providers.list_models("antigravity") == ["model-x"])


# ---------------------------------------------------------------------------
# get_cached_models / models_line — read-only, never fetch
# ---------------------------------------------------------------------------


def test_get_cached_models_missing_entry_is_none():
    with tempfile.TemporaryDirectory() as tmp:
        orig_cache_file = cache_mod.CACHE_FILE
        cache_mod.CACHE_FILE = Path(tmp) / "cache.json"
        try:
            check("no cache file at all -> None", models.get_cached_models("claude") is None)
            check("models_line() with nothing cached -> None", models.models_line("claude") is None)
        finally:
            cache_mod.CACHE_FILE = orig_cache_file


def test_get_cached_models_fresh_entry():
    with tempfile.TemporaryDirectory() as tmp:
        orig_cache_file = cache_mod.CACHE_FILE
        cache_mod.CACHE_FILE = Path(tmp) / "cache.json"
        try:
            cache_mod.CACHE_FILE.write_text(json.dumps({
                "models": {"claude": {"timestamp": int(time.time()), "models": ["opus", "haiku"], "static": True}}
            }))
            result = models.get_cached_models("claude")
            check("fresh entry returns (models, is_static)", result == (["opus", "haiku"], True))
            line = models.models_line("claude")
            check(
                "static entry's line matches the detail_models_static i18n template exactly",
                line == t("detail_models_static", models="opus, haiku"),
            )
        finally:
            cache_mod.CACHE_FILE = orig_cache_file


def test_get_cached_models_nonstatic_entry_uses_plain_template():
    with tempfile.TemporaryDirectory() as tmp:
        orig_cache_file = cache_mod.CACHE_FILE
        cache_mod.CACHE_FILE = Path(tmp) / "cache.json"
        try:
            cache_mod.CACHE_FILE.write_text(json.dumps({
                "models": {"antigravity": {"timestamp": int(time.time()), "models": ["gemini-2.5-pro"], "static": False}}
            }))
            line = models.models_line("antigravity")
            check(
                "non-static entry's line matches the plain detail_models i18n template exactly",
                line == t("detail_models", models="gemini-2.5-pro"),
            )
        finally:
            cache_mod.CACHE_FILE = orig_cache_file


def test_get_cached_models_stale_entry_is_none():
    with tempfile.TemporaryDirectory() as tmp:
        orig_cache_file = cache_mod.CACHE_FILE
        cache_mod.CACHE_FILE = Path(tmp) / "cache.json"
        try:
            stale_ts = int(time.time()) - models.MODELS_CACHE_TTL - 3600  # 1h past the 7-day TTL
            cache_mod.CACHE_FILE.write_text(json.dumps({
                "models": {"claude": {"timestamp": stale_ts, "models": ["opus"], "static": True}}
            }))
            check("entry older than MODELS_CACHE_TTL -> None (hidden, not shown stale)",
                  models.get_cached_models("claude") is None)
            check("models_line() also None for a stale entry", models.models_line("claude") is None)
        finally:
            cache_mod.CACHE_FILE = orig_cache_file


def test_get_cached_models_empty_list_is_none():
    with tempfile.TemporaryDirectory() as tmp:
        orig_cache_file = cache_mod.CACHE_FILE
        cache_mod.CACHE_FILE = Path(tmp) / "cache.json"
        try:
            cache_mod.CACHE_FILE.write_text(json.dumps({
                "models": {"codex": {"timestamp": int(time.time()), "models": None, "static": False}}
            }))
            check("cached models is None (e.g. codex) -> get_cached_models is None too",
                  models.get_cached_models("codex") is None)
        finally:
            cache_mod.CACHE_FILE = orig_cache_file


# ---------------------------------------------------------------------------
# cmd_models — end to end, real providers.ORDER (all 4 "installed" for real
# on this machine), subprocess fully stubbed for the entire test.
# ---------------------------------------------------------------------------


def test_cmd_models_unknown_provider_reported():
    with tempfile.TemporaryDirectory() as tmp:
        orig_cache_file = cache_mod.CACHE_FILE
        cache_mod.CACHE_FILE = Path(tmp) / "cache.json"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                models.cmd_models(["not-a-real-provider"])
            check("unknown provider name gets reported", "not-a-real-provider" in buf.getvalue())
        finally:
            cache_mod.CACHE_FILE = orig_cache_file


def test_cmd_models_caution_printed_for_risky_providers(monkeypatch_run):
    monkeypatch_run({("agy", "models"): "model-a\n"})
    with tempfile.TemporaryDirectory() as tmp:
        orig_cache_file = cache_mod.CACHE_FILE
        cache_mod.CACHE_FILE = Path(tmp) / "cache.json"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                models.cmd_models(["antigravity"])
            out = buf.getvalue()
            expected_caution = t("models_caution", providers=providers.label("antigravity"))
            check("caution text printed before touching antigravity's models subcommand",
                  expected_caution in out)
        finally:
            cache_mod.CACHE_FILE = orig_cache_file


def test_cmd_models_no_caution_for_claude_only():
    with tempfile.TemporaryDirectory() as tmp:
        orig_cache_file = cache_mod.CACHE_FILE
        cache_mod.CACHE_FILE = Path(tmp) / "cache.json"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                models.cmd_models(["claude"])
            out = buf.getvalue()
            expected = t(
                "models_result_static",
                label=providers.label("claude"),
                models="fable, opus, sonnet, haiku",
            )
            # claude isn't in _RISKY_PROVIDERS, so requesting only claude
            # must print exactly this one result line and nothing else —
            # no caution block (that's only for antigravity/grok targets).
            check("claude-only run prints exactly the one expected result line, nothing else",
                  out == expected + "\n")
        finally:
            cache_mod.CACHE_FILE = orig_cache_file


def test_cmd_models_writes_cache_for_all_providers(monkeypatch_run):
    # No args -> every provider in providers.ORDER. All four binaries are
    # actually installed on this machine (see module docstring), so this
    # is the real code path providers.installed() takes in production —
    # subprocess.run is fully stubbed so it can never reach a real CLI.
    monkeypatch_run({
        ("agy", "models"): "gemini-2.5-pro\n",
        ("grok", "models"): "grok-4\n",
    })
    with tempfile.TemporaryDirectory() as tmp:
        orig_cache_file = cache_mod.CACHE_FILE
        cache_mod.CACHE_FILE = Path(tmp) / "cache.json"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                models.cmd_models([])
            saved = json.loads(cache_mod.CACHE_FILE.read_text())["models"]
            check("all 4 providers got a cache entry", set(saved) == {"claude", "codex", "antigravity", "grok"})
            check("claude entry is static with the alias list",
                  saved["claude"]["static"] is True and saved["claude"]["models"] == ["fable", "opus", "sonnet", "haiku"])
            check("codex entry has models: null (no subcommand)", saved["codex"]["models"] is None)
            check("antigravity entry has the parsed model list", saved["antigravity"]["models"] == ["gemini-2.5-pro"])
            check("grok entry has the parsed model list", saved["grok"]["models"] == ["grok-4"])
            check("every entry has a numeric timestamp", all(isinstance(v["timestamp"], int) for v in saved.values()))
        finally:
            cache_mod.CACHE_FILE = orig_cache_file


def main():
    print("test_models:")

    test_parse_model_lines_strips_and_keeps_names()
    test_parse_model_lines_drops_decoration()
    test_parse_model_lines_drops_known_headers()
    test_parse_model_lines_drops_short_colon_headers()
    test_parse_model_lines_empty_input()

    test_claude_list_models_is_static()
    test_codex_list_models_is_none()

    fake = _FakeRun({})
    orig_run = subprocess.run

    def install_canned(canned):
        fake.canned = canned
        subprocess.run = fake

    subprocess.run = fake  # blanket install; real CLI calls would raise via _FakeRun

    try:
        test_antigravity_list_models_ok(install_canned)
        test_grok_list_models_ok(install_canned)
        test_providers_list_models_dispatches(install_canned)
        test_cmd_models_caution_printed_for_risky_providers(install_canned)
        test_cmd_models_writes_cache_for_all_providers(install_canned)
    finally:
        subprocess.run = orig_run

    # These manage subprocess.run themselves (simulating a raised
    # exception directly rather than a canned return).
    test_antigravity_list_models_subprocess_failure_is_none(install_canned)
    test_grok_list_models_subprocess_failure_is_none()

    test_get_cached_models_missing_entry_is_none()
    test_get_cached_models_fresh_entry()
    test_get_cached_models_nonstatic_entry_uses_plain_template()
    test_get_cached_models_stale_entry_is_none()
    test_get_cached_models_empty_list_is_none()

    test_cmd_models_unknown_provider_reported()
    test_cmd_models_no_caution_for_claude_only()

    print("test_models: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
