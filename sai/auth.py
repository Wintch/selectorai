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

# Deliberately NOT `https?://\S.*` with re.S (an earlier version): that
# matched from the first "https?://" to the END of the captured output,
# on the theory that a CLI-wrapped URL is followed by a blank line before
# any other prose. Confirmed live to be wrong when a login command's OWN
# error text embeds a URL mid-sentence with no blank line after it (e.g.
# grok's device-auth flow on a DNS failure: "Error: error sending request
# for url (https://auth.x.ai/oauth2/device/code): client error (Connect):
# dns error: ..."), which fell through as run_login_capture's ONLY match —
# `block.split("\n\n")[0]` never found a blank line to stop at, so the
# whitespace-stripped "clean URL" ended up mashing the entire error
# message onto the end of the real URL, e.g. "...device/code):
# clienterror(Connect):dnserror:failedtolookupaddressinformation:Tryagain".
# This version instead stops at the first space or ")" — a wrapped URL's
# own line breaks have no such character before the next fragment (each
# `\n[^\s)]+` chunk requires a non-blank, non-")"-led continuation right
# after the newline, so a real blank line naturally ends the match too,
# same stopping behavior the old `.split("\n\n")[0]` was for), while
# trailing prose on the same line — wrapped or not — now can't be
# swallowed into the URL at all.
_URL_BLOCK_RE = re.compile(r"https?://[^\s)]+(?:\n[^\s)]+)*")


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
            # No `.split("\n\n")[0]` here (an earlier version had one): the
            # regex above can no longer match across a blank line at all,
            # so m.group(0) never contains "\n\n" to split on in the first
            # place — see the regex's own comment.
            clean_url = re.sub(r"\s+", "", m.group(0))
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
