"""auth / login — same "clean URL" wrapper for every provider, specific
login command per provider. Triggered only on explicit request (`auth`),
never automatically, same principle as --check-antigravity.
"""
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from sai import providers
from sai.i18n import t

_URL_BLOCK_RE = re.compile(r"https?://\S.*", re.S)


def run_login_capture(p):
    cmd = providers.registry[p].LOGIN_CMD
    # Deliberately does NOT touch `stty cols` anymore. An earlier version
    # widened the pty to dodge a CLI's own word-wrap, but that mutates shared
    # terminal state a foreground TUI (this provider's login flow, or a
    # later `claude`/`codex`/`agy` session) reads at startup — if that TUI
    # is then running full-screen in raw mode, there's no way to hand
    # control back to restore it, and it stays stuck rendering at the wrong
    # width (confirmed live: a Claude Code session box-drawing itself across
    # a corrupted-huge column count). The tee+reconstruct step below already
    # fixes the actual URL regardless of whether it got wrapped on screen,
    # so mutating the terminal was never load-bearing — just removed.
    fd, logfile = tempfile.mkstemp(prefix="selectorai-auth-", suffix=".log")
    os.close(fd)
    try:
        # Real `tee`, not a hand-rolled line-buffered reader: a login prompt
        # without a trailing newline (e.g. "Enter code: ") needs to reach the
        # screen immediately, which a naive `for line in proc.stdout` loop in
        # Python would delay until the next newline arrives. `cmd` is always
        # one of our own fixed LOGIN_CMD lists, never user input, so
        # building this as a shell string is safe.
        shell_cmd = f"{shlex.join(cmd)} 2>&1 | tee {shlex.quote(logfile)}"
        subprocess.run(shell_cmd, shell=True)

        full = Path(logfile).read_text(errors="replace")
        m = _URL_BLOCK_RE.search(full)
        if m:
            block = m.group(0).split("\n\n")[0]
            clean_url = re.sub(r"\s+", "", block)
            print()
            print(t("auth_clean_url", url=clean_url))
    finally:
        Path(logfile).unlink(missing_ok=True)

    status_cmd = providers.registry[p].LOGIN_STATUS_CMD
    if status_cmd:
        print()
        print(t("auth_status_header"))
        subprocess.run(status_cmd)


def cmd_auth(argv):
    if not argv:
        targets = providers.ORDER
    else:
        unknown = [a for a in argv if a not in providers.ORDER]
        if unknown:
            print(f"Unknown provider(s): {', '.join(unknown)}. Options: {', '.join(providers.ORDER)}")
            sys.exit(1)
        targets = argv
    for p in targets:
        if not providers.installed(p):
            print(t("status_not_installed", label=providers.label(p)))
            continue
        print(f"== {providers.label(p)} ==")
        run_login_capture(p)
        print()
