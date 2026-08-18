#!/usr/bin/env python3
"""Plain-python3 test for sai/session.py: shutil.which and subprocess.run
are stubbed for the whole run (never a real `tmux` binary — see
sai/session.py's module docstring: tmux isn't installed on this machine,
so this only proves the module's own branching logic, not that tmux
itself behaves as documented). STATE_DIR is pointed at a tempdir for
every toggle-file test, never touching the real ~/.selectorai/background.

Covers: available()/enabled() basics, cmd_background's on/off/status
file handling, the wrap_launch branch matrix (no-tmux / disabled /
inside-TMUX / session-absent / session-present) called out explicitly in
the feature spec, and live_windows()/peek()'s output parsing + best-effort
failure handling.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sai.paths as paths  # noqa: E402
from sai import session  # noqa: E402


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


class _FakeWhich:
    """Drop-in for shutil.which: reports tmux present/absent without
    touching the real PATH."""

    def __init__(self, present):
        self.present = present

    def __call__(self, name):
        return f"/usr/bin/{name}" if self.present else None


class _Result:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class _FakeRun:
    """Drop-in for subprocess.run: routes by the command's first two argv
    elements, refuses (raises) anything unrecognized — same defensive
    shape as tests/test_status_shapes.py's _FakeRun, so a bug that would
    otherwise shell out to a real `tmux` fails the test loudly instead of
    silently doing nothing (or worse, something) on a machine that
    someday does have tmux installed."""

    def __init__(self, has_session_rc=1, list_windows_out="", capture_pane_out=""):
        self.has_session_rc = has_session_rc
        self.list_windows_out = list_windows_out
        self.capture_pane_out = capture_pane_out
        self.calls = []

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        head = cmd[:2]
        if head == ["tmux", "has-session"]:
            return _Result(returncode=self.has_session_rc)
        if head == ["tmux", "list-windows"]:
            return _Result(returncode=0, stdout=self.list_windows_out)
        if head == ["tmux", "new-window"]:
            return _Result(returncode=0)
        if head == ["tmux", "capture-pane"]:
            return _Result(returncode=0, stdout=self.capture_pane_out)
        raise AssertionError(f"unexpected subprocess.run call in test_session: {cmd!r}")


def test_available():
    orig_which = shutil.which
    try:
        shutil.which = _FakeWhich(True)
        check("available() True when tmux is on PATH", session.available() is True)
        shutil.which = _FakeWhich(False)
        check("available() False when tmux is missing", session.available() is False)
    finally:
        shutil.which = orig_which


def test_enabled_toggle():
    with tempfile.TemporaryDirectory() as tmp:
        orig_state_dir = paths.STATE_DIR
        paths.STATE_DIR = Path(tmp)
        try:
            check("enabled() True when toggle file absent (default ON)", session.enabled() is True)
            (paths.STATE_DIR / "background").write_text("0")
            check("enabled() False when toggle file contains '0'", session.enabled() is False)
            (paths.STATE_DIR / "background").write_text("1")
            check("enabled() True when toggle file contains anything else", session.enabled() is True)
        finally:
            paths.STATE_DIR = orig_state_dir


def test_cmd_background_on_off_status():
    with tempfile.TemporaryDirectory() as tmp:
        orig_state_dir = paths.STATE_DIR
        orig_which = shutil.which
        paths.STATE_DIR = Path(tmp)
        try:
            shutil.which = _FakeWhich(True)
            toggle_file = paths.STATE_DIR / "background"

            session.cmd_background(["off"])
            check("background off: writes '0'", toggle_file.exists() and toggle_file.read_text() == "0")
            check("background off: enabled() now False", session.enabled() is False)

            session.cmd_background(["on"])
            check("background on: removes the toggle file", not toggle_file.exists())
            check("background on: enabled() now True", session.enabled() is True)

            session.cmd_background([])  # status: must not raise, must not touch the file
            check("background status: leaves the (absent) file untouched", not toggle_file.exists())
        finally:
            shutil.which = orig_which
            paths.STATE_DIR = orig_state_dir


def test_wrap_launch_no_tmux():
    orig_which = shutil.which
    try:
        shutil.which = _FakeWhich(False)
        argv = ["codex", "--flag"]
        check("no-tmux: argv passed through unchanged", session.wrap_launch("codex", argv) == argv)
    finally:
        shutil.which = orig_which


def test_wrap_launch_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        orig_state_dir = paths.STATE_DIR
        orig_which = shutil.which
        paths.STATE_DIR = Path(tmp)
        try:
            shutil.which = _FakeWhich(True)
            (paths.STATE_DIR / "background").write_text("0")
            argv = ["claude", "--x"]
            check("disabled: argv passed through unchanged", session.wrap_launch("claude", argv) == argv)
        finally:
            shutil.which = orig_which
            paths.STATE_DIR = orig_state_dir


def test_wrap_launch_inside_tmux():
    orig_which = shutil.which
    had_tmux_env = "TMUX" in os.environ
    orig_tmux_env = os.environ.get("TMUX")
    try:
        shutil.which = _FakeWhich(True)
        os.environ["TMUX"] = "/tmp/tmux-1000/default,1234,0"
        argv = ["grok", "--y"]
        check(
            "inside an existing tmux client: argv passed through unchanged (no nesting)",
            session.wrap_launch("grok", argv) == argv,
        )
    finally:
        shutil.which = orig_which
        if had_tmux_env:
            os.environ["TMUX"] = orig_tmux_env
        else:
            os.environ.pop("TMUX", None)


def test_wrap_launch_session_absent():
    orig_which = shutil.which
    orig_run = subprocess.run
    had_tmux_env = "TMUX" in os.environ
    orig_tmux_env = os.environ.get("TMUX")
    os.environ.pop("TMUX", None)
    try:
        shutil.which = _FakeWhich(True)
        fake = _FakeRun(has_session_rc=1)  # has-session fails -> no session yet
        subprocess.run = fake
        argv = ["codex", "--z"]
        result = session.wrap_launch("codex", argv)
        check(
            "session-absent: returns a new-session argv that both creates the "
            "session and runs the launch",
            result == ["tmux", "new-session", "-s", session.SESSION_NAME, "-n", "codex"] + argv,
        )
        check(
            "session-absent: no new-window call happened (nothing to add a window to yet)",
            all(c[:2] != ["tmux", "new-window"] for c in fake.calls),
        )
    finally:
        subprocess.run = orig_run
        shutil.which = orig_which
        if had_tmux_env:
            os.environ["TMUX"] = orig_tmux_env


def test_wrap_launch_session_present():
    orig_which = shutil.which
    orig_run = subprocess.run
    had_tmux_env = "TMUX" in os.environ
    orig_tmux_env = os.environ.get("TMUX")
    os.environ.pop("TMUX", None)
    try:
        shutil.which = _FakeWhich(True)
        fake = _FakeRun(has_session_rc=0, list_windows_out="claude\t1720000000\n")
        subprocess.run = fake
        argv = ["claude", "--w"]
        result = session.wrap_launch("claude", argv)
        check(
            "session-present: returns attach-session argv (caller lands in the shared session)",
            result == ["tmux", "attach-session", "-t", session.SESSION_NAME],
        )
        check(
            "session-present: a new-window call ran first, carrying the launch argv",
            any(
                c == ["tmux", "new-window", "-t", session.SESSION_NAME, "-n", "claude"] + argv
                for c in fake.calls
            ),
        )
    finally:
        subprocess.run = orig_run
        shutil.which = orig_which
        if had_tmux_env:
            os.environ["TMUX"] = orig_tmux_env


def test_live_windows_parses_tab_separated_output():
    orig_run = subprocess.run
    try:
        fake = _FakeRun(has_session_rc=0, list_windows_out="claude\t1720000000\ncodex\t1720000100\n")
        subprocess.run = fake
        windows = session.live_windows()
        check(
            "live_windows: parses '#{window_name}\\t#{window_activity}' rows",
            windows == [("claude", 1720000000), ("codex", 1720000100)],
        )
    finally:
        subprocess.run = orig_run


def test_live_windows_no_session():
    orig_run = subprocess.run
    try:
        subprocess.run = _FakeRun(has_session_rc=1)
        check("live_windows: [] when has-session fails", session.live_windows() == [])
    finally:
        subprocess.run = orig_run


def test_peek_best_effort():
    orig_run = subprocess.run
    try:
        def _raiser(*a, **k):
            raise OSError("no tmux binary")

        subprocess.run = _raiser
        check("peek: [] on any subprocess failure (best-effort, never raises)", session.peek("claude") == [])
    finally:
        subprocess.run = orig_run

    orig_run = subprocess.run
    try:
        capture_out = "\n".join(f"line{i}" for i in range(8)) + "\n\n"  # trailing blank dropped
        subprocess.run = _FakeRun(has_session_rc=0, capture_pane_out=capture_out)
        lines = session.peek("claude")
        check(
            "peek: last 5 non-empty lines only",
            lines == [f"line{i}" for i in range(3, 8)],
        )
    finally:
        subprocess.run = orig_run


def main():
    print("test_session:")
    test_available()
    test_enabled_toggle()
    test_cmd_background_on_off_status()
    test_wrap_launch_no_tmux()
    test_wrap_launch_disabled()
    test_wrap_launch_inside_tmux()
    test_wrap_launch_session_absent()
    test_wrap_launch_session_present()
    test_live_windows_parses_tab_separated_output()
    test_live_windows_no_session()
    test_peek_best_effort()
    print("test_session: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
