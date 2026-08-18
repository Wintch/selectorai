"""Grok Build (xAI) provider.

No CHECK_GROK gate to match Antigravity's: confirmed (not just
precautionary) that there's no live usage check to gate in the first
place — see status() below for why.
"""
import os
from pathlib import Path

from sai.i18n import t

NAME = "grok"
LABEL = "Grok Build (xAI)"
BIN = "grok"
INSTALL_CMD = "curl -fsSL https://x.ai/cli/install.sh | bash"
UPDATE_CMD = ["grok", "update"]
# `grok login --help` -> `--device-auth` explicitly requests the URL+code
# flow (phone-friendly, vs. defaulting to auto-opening a local browser).
LOGIN_CMD = ["grok", "login", "--device-auth"]
LOGIN_STATUS_CMD = None  # no non-interactive status subcommand exposed either


def last_used_epoch():
    # Unconfirmed — this machine has no completed Grok session yet to
    # observe the real path from (didn't want to start one just to
    # check; same lesson as the Antigravity OAuth-popup incident).
    # Best-effort: same history.jsonl convention claude/codex use, then
    # a sessions/ dir, since `grok sessions list` implies persisted
    # session state exists somewhere under ~/.grok. "never" if neither
    # exists — mark this confirmed once someone's actually used it.
    f = Path.home() / ".grok" / "history.jsonl"
    if f.exists():
        return int(f.stat().st_mtime)
    d = Path.home() / ".grok" / "sessions"
    if not d.exists():
        return 0
    latest = 0
    try:
        with os.scandir(d) as it:
            for entry in it:
                try:
                    mtime = entry.stat().st_mtime
                    if mtime > latest:
                        latest = mtime
                except OSError:
                    pass
    except OSError:
        pass
    return int(latest)


def status():
    # Two confirmations stack here, not one:
    # 1. Docs (~/.grok/docs/user-guide/04-slash-commands.md,
    #    14-headless-mode.md): `/usage`/`/cost` are real but TUI-only —
    #    headless mode (`-p`) sends its argument as a literal chat prompt,
    #    it does not interpret slash commands at all, and there's no CLI
    #    subcommand for this either (checked the full `grok --help`
    #    command list). So this could never work headlessly regardless of
    #    account type.
    # 2. Confirmed live, free account (grok.com login, no API key/billing):
    #    `/usage` and `/cost` inside the actual TUI show nothing — no
    #    credit balance to check exists at all for this account type. The
    #    server just cuts you off past an undocumented limit and pushes an
    #    upgrade prompt, no reset time given anywhere. So even the
    #    interactive path has nothing to surface, not just the headless one.
    #
    # Don't even try `grok -p "/usage"`: it would spend real tokens/credits
    # sending the model the literal text "/usage" as a prompt, for a
    # response that still wouldn't contain parseable usage data.
    return {"pct_used": None, "rows": [], "note": t("note_grok_no_headless_usage"), "kind": "no-usage-api"}


def launch(yolo, prompt, cont):
    # Same preset shape as Claude: --permission-mode auto by default —
    # confirmed via `grok --help`, same enum as Claude's (default/
    # acceptEdits/auto/dontAsk/bypassPermissions/plan). --yolo swaps to
    # the full bypass value instead of a separate dangerous flag.
    if yolo:
        args = ["grok", "--permission-mode", "bypassPermissions"]
    else:
        args = ["grok", "--permission-mode", "auto"]
    if cont:
        args.append("--continue")
    print(t("launch_grok", flags=" ".join(args[1:])))
    if prompt:
        args.append(prompt)
    os.execvp(args[0], args)
