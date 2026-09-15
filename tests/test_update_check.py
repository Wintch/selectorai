#!/usr/bin/env python3
"""Plain-python3 test: feed each provider's check_update() function canned
CLI output (never a real subprocess — subprocess.run is monkeypatched for
the whole test, same _FakeRun shape as tests/test_status_shapes.py) and
assert the returned shape: None (not confirmed safe to check — currently
just Antigravity), or {"installed", "latest", "update_available"}.

Codex's check_update() also reads ~/.codex/version.json directly (that's
Codex's own real config path, not something selectorai owns or redirects
in production — same category as claude.py's last_used_epoch() reading
~/.claude/history.jsonl unmocked). To keep this test hermetic rather than
reading whatever real file happens to exist on the machine running it,
Path.home is monkeypatched to a temp directory for the duration of those
two tests only, restored in a finally block.

Never touches ~/.selectorai and never subprocesses a real AI CLI.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sai.providers import antigravity, claude, codex, grok  # noqa: E402


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


class _FakeRun:
    """Same drop-in as tests/test_status_shapes.py's _FakeRun: canned
    stdout for a known argv, raises on anything unrecognized so a bug that
    would otherwise shell out to a real CLI fails loudly instead of
    silently running one."""

    def __init__(self, canned):
        self.canned = canned  # {tuple(argv): stdout}

    def __call__(self, cmd, *args, **kwargs):
        key = tuple(cmd) if isinstance(cmd, list) else cmd
        if key not in self.canned:
            raise AssertionError(f"unexpected subprocess.run call, would hit a real CLI: {cmd!r}")

        class _Result:
            stdout = self.canned[key]
            returncode = 0

        return _Result()


def assert_update_shape(label, info):
    if info is None:
        return
    check(f"{label}: is dict", isinstance(info, dict))
    check(f"{label}: has installed/latest/update_available keys", set(info.keys()) == {"installed", "latest", "update_available"})
    check(f"{label}: update_available is bool or None", info["update_available"] in (True, False, None))


def test_claude_up_to_date(monkeypatch_run):
    # Real confirmed output (see sai/providers/claude.py's check_update()).
    out = (
        "Claude Code doctor\n\n"
        "Running: native (2.1.272)\n"
        "Commit: 013cad548b76\n"
        "Auto-updates: enabled\n"
        "Auto-update channel: latest\n"
        "Last update attempt: success → 2.1.272 (2026-09-15)\n"
    )
    monkeypatch_run({("claude", "doctor"): out})
    info = claude.check_update()
    assert_update_shape("claude up-to-date", info)
    check("claude up-to-date: installed == 2.1.272", info["installed"] == "2.1.272")
    check("claude up-to-date: latest == 2.1.272", info["latest"] == "2.1.272")
    check("claude up-to-date: update_available is False", info["update_available"] is False)


def test_claude_update_available(monkeypatch_run):
    out = (
        "Running: native (2.1.270)\n"
        "Auto-updates: enabled\n"
        "Last update attempt: success → 2.1.272 (2026-09-15)\n"
    )
    monkeypatch_run({("claude", "doctor"): out})
    info = claude.check_update()
    assert_update_shape("claude update-available", info)
    check("claude update-available: installed == 2.1.270", info["installed"] == "2.1.270")
    check("claude update-available: latest == 2.1.272", info["latest"] == "2.1.272")
    check("claude update-available: update_available is True", info["update_available"] is True)


def test_claude_no_running_line(monkeypatch_run):
    monkeypatch_run({("claude", "doctor"): "No installation issues found.\n"})
    info = claude.check_update()
    check("claude no-running-line: check_update() is None", info is None)


def test_grok_up_to_date(monkeypatch_run):
    # Real confirmed output (see sai/providers/grok.py's check_update()).
    out = json.dumps({
        "currentVersion": "1.0.30", "latestVersion": "1.0.30",
        "updateAvailable": False, "channel": "stable",
    })
    monkeypatch_run({("grok", "update", "--check", "--json"): out})
    info = grok.check_update()
    assert_update_shape("grok up-to-date", info)
    check("grok up-to-date: installed == 1.0.30", info["installed"] == "1.0.30")
    check("grok up-to-date: update_available is False", info["update_available"] is False)


def test_grok_bad_json(monkeypatch_run):
    monkeypatch_run({("grok", "update", "--check", "--json"): "not json"})
    info = grok.check_update()
    check("grok bad-json: check_update() is None", info is None)


def test_antigravity_never_checks():
    info = antigravity.check_update()
    check("antigravity: check_update() is always None", info is None)


def test_codex_up_to_date(monkeypatch_run):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / ".codex").mkdir()
        (Path(tmp) / ".codex" / "version.json").write_text(
            json.dumps({"latest_version": "0.154.0", "last_checked_at": "2026-09-15T02:52:22Z"})
        )
        monkeypatch_run({("codex", "--version"): "codex-cli 0.154.0\n"})
        orig_home = codex.Path.home
        codex.Path.home = staticmethod(lambda: Path(tmp))
        try:
            info = codex.check_update()
        finally:
            codex.Path.home = orig_home
    assert_update_shape("codex up-to-date", info)
    check("codex up-to-date: installed == 0.154.0", info["installed"] == "0.154.0")
    check("codex up-to-date: latest == 0.154.0", info["latest"] == "0.154.0")
    check("codex up-to-date: update_available is False", info["update_available"] is False)


def test_codex_update_available(monkeypatch_run):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / ".codex").mkdir()
        (Path(tmp) / ".codex" / "version.json").write_text(json.dumps({"latest_version": "0.155.0"}))
        monkeypatch_run({("codex", "--version"): "codex-cli 0.154.0\n"})
        orig_home = codex.Path.home
        codex.Path.home = staticmethod(lambda: Path(tmp))
        try:
            info = codex.check_update()
        finally:
            codex.Path.home = orig_home
    assert_update_shape("codex update-available", info)
    check("codex update-available: update_available is True", info["update_available"] is True)


def test_codex_no_version_file(monkeypatch_run):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch_run({("codex", "--version"): "codex-cli 0.154.0\n"})
        orig_home = codex.Path.home
        codex.Path.home = staticmethod(lambda: Path(tmp))
        try:
            info = codex.check_update()
        finally:
            codex.Path.home = orig_home
    assert_update_shape("codex no-version-file", info)
    check("codex no-version-file: installed still known", info["installed"] == "0.154.0")
    check("codex no-version-file: latest is None", info["latest"] is None)
    check("codex no-version-file: update_available is None (unknown)", info["update_available"] is None)


def main():
    print("test_update_check:")
    fake = _FakeRun({})
    orig_run = subprocess.run

    def install_canned(canned):
        fake.canned = canned
        subprocess.run = fake

    subprocess.run = fake

    try:
        test_claude_up_to_date(install_canned)
        test_claude_update_available(install_canned)
        test_claude_no_running_line(install_canned)
        test_grok_up_to_date(install_canned)
        test_grok_bad_json(install_canned)
        test_codex_up_to_date(install_canned)
        test_codex_update_available(install_canned)
        test_codex_no_version_file(install_canned)
    finally:
        subprocess.run = orig_run

    test_antigravity_never_checks()

    print("test_update_check: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
