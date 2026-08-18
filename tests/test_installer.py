#!/usr/bin/env python3
"""Plain-python3 test for sai/installer.py's cmd_setup(['--dry-run']) —
the ONLY mode this test is allowed to exercise (see docs/ARCHITECTURE.md
and this repo's safety rules: real `setup` blocks on input() and, once
confirmed, can shell out to a real `claude`/`codex`/`agy`/`grok` install
or login flow — never something a test may trigger).

subprocess.run and builtins.input are both replaced with stubs that raise
AssertionError the instant either is called — --dry-run's whole point is
answering every step 'no' without ever touching either, so a call to
either one here means a real bug (a gate that isn't actually gating).
STATE_DIR is pointed at a tempdir (same convention as tests/test_session.py)
as defense in depth, and the real ~/.selectorai pref files' mtimes are
recorded before and after as the final check that dry-run genuinely wrote
nothing, belt-and-suspenders alongside the subprocess/input stubs above.
"""
import builtins
import io
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sai.paths as paths  # noqa: E402
from sai import providers  # noqa: E402
from sai.installer import cmd_setup  # noqa: E402


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


def _raising_subprocess_run(cmd, *args, **kwargs):
    raise AssertionError(
        f"--dry-run must never call subprocess.run, but it called: {cmd!r}"
    )


def _raising_input(prompt=""):
    raise AssertionError(f"--dry-run must never call input(), but it was prompted: {prompt!r}")


# The real (never touched, never written to) pref files under ~/.selectorai
# whose mtime-or-absence this test snapshots before and after, as the final
# proof --dry-run left them alone — independent of STATE_DIR being pointed
# at a tempdir below, since a couple of sai.paths constants (LANG_FILE,
# CHECK_ANTIGRAVITY_FILE) are computed once at import time from the *real*
# STATE_DIR and wouldn't move just because a test later monkeypatches
# sai.paths.STATE_DIR — see sai/installer.py's antigravity-file comment.
_REAL_PREF_FILES = [
    Path.home() / ".selectorai" / "lang",
    Path.home() / ".selectorai" / "theme",
    Path.home() / ".selectorai" / "check_antigravity",
    Path.home() / ".selectorai" / "background",
]


def _snapshot(paths_list):
    return [(p.exists(), p.stat().st_mtime if p.exists() else None) for p in paths_list]


def test_dry_run_flow():
    before = _snapshot(_REAL_PREF_FILES)

    orig_run = subprocess.run
    orig_input = builtins.input
    orig_state_dir = paths.STATE_DIR

    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        paths.STATE_DIR = Path(tmp)
        subprocess.run = _raising_subprocess_run
        builtins.input = _raising_input
        try:
            with redirect_stdout(buf):
                cmd_setup(["--dry-run"])
        finally:
            subprocess.run = orig_run
            builtins.input = orig_input
            paths.STATE_DIR = orig_state_dir

    out = buf.getvalue()
    check("dry-run: produced non-empty output", len(out) > 0)
    check("dry-run: shows the dry-run banner", "dry-run" in out.lower() or "пробный" in out.lower())

    for p in providers.ORDER:
        label = providers.label(p)
        check(f"dry-run: mentions provider {p} ({label!r})", label in out)

    check(
        "dry-run: mentions the final 'run ./selectorai.py' close-out",
        "./selectorai.py" in out,
    )

    after = _snapshot(_REAL_PREF_FILES)
    check("dry-run: real ~/.selectorai pref files untouched", before == after)


def test_dry_run_never_calls_subprocess_or_input_even_when_nothing_installed():
    """Same run, but with providers.installed forced False for every
    provider (shutil.which stubbed out) — exercises the 'offer to
    install'/'offer to log in' branches' own dry-run guards, not just the
    already-installed path this dev machine happens to be in."""
    import shutil

    orig_which = shutil.which
    orig_run = subprocess.run
    orig_input = builtins.input
    orig_state_dir = paths.STATE_DIR

    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        paths.STATE_DIR = Path(tmp)
        shutil.which = lambda name: None
        subprocess.run = _raising_subprocess_run
        builtins.input = _raising_input
        try:
            with redirect_stdout(buf):
                cmd_setup(["--dry-run"])
        finally:
            shutil.which = orig_which
            subprocess.run = orig_run
            builtins.input = orig_input
            paths.STATE_DIR = orig_state_dir

    out = buf.getvalue()
    for p in providers.ORDER:
        check(f"dry-run (nothing installed): mentions {p}", providers.label(p) in out)
        cmd = providers.registry[p].INSTALL_CMD
        check(f"dry-run (nothing installed): would-install line names {p}'s real INSTALL_CMD", cmd in out)


class _NonTtyStream(io.StringIO):
    """Stand-in for sys.stdin/sys.stdout that is never a tty, regardless of
    what fd 0/1 actually are in whatever environment runs this test (a real
    terminal, CI, a pipe) — the guard must fire the same way in all of
    them, so isatty() is hardcoded False rather than left to the ambient
    environment."""

    def isatty(self):
        return False


def test_interactive_guard_blocks_non_tty():
    """cmd_setup with no --dry-run, given non-tty stdin+stdout, must exit(1)
    before ever reaching input() or subprocess.run — this is the guard at
    sai/installer.py's cmd_setup() (lines ~117-119). Without --dry-run,
    reaching either call for real would mean blocking forever on input()
    or (once confirmed) shelling out to a real provider install/login —
    exactly what this repo's safety rules forbid from an automated run, so
    the guard existing and firing first is what makes calling cmd_setup at
    all safe here."""
    orig_run = subprocess.run
    orig_input = builtins.input
    orig_stdin = sys.stdin
    orig_state_dir = paths.STATE_DIR

    out_buf = _NonTtyStream()
    in_buf = _NonTtyStream()
    exit_code = None
    with tempfile.TemporaryDirectory() as tmp:
        paths.STATE_DIR = Path(tmp)
        subprocess.run = _raising_subprocess_run
        builtins.input = _raising_input
        sys.stdin = in_buf
        try:
            with redirect_stdout(out_buf):
                try:
                    cmd_setup([])
                except SystemExit as exc:
                    exit_code = exc.code
        finally:
            subprocess.run = orig_run
            builtins.input = orig_input
            sys.stdin = orig_stdin
            paths.STATE_DIR = orig_state_dir

    out = out_buf.getvalue()
    check("non-tty guard: raised SystemExit(1)", exit_code == 1)
    # All three i18n/*.json translations of setup_needs_tty contain the
    # literal substring "tty" (en: "a real tty", es: "una tty real", ru:
    # "настоящим tty") — checking for it is locale-independent, which
    # matters here since LANG_FILE (unlike STATE_DIR above) is bound at
    # import time from the *real* ~/.selectorai, not the tempdir.
    check("non-tty guard: printed the needs-a-tty message", "tty" in out.lower())
    check("non-tty guard: never reached input() or subprocess.run", len(out.splitlines()) <= 1)


def main():
    print("test_installer:")
    test_dry_run_flow()
    test_dry_run_never_calls_subprocess_or_input_even_when_nothing_installed()
    test_interactive_guard_blocks_non_tty()
    print("test_installer: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
