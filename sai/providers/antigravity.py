"""Antigravity (Google) provider.

Off by default: probing Antigravity ("agy -p /usage") while not logged in
triggers its real interactive Google OAuth flow (confirmed in
~/.gemini/antigravity-cli/log/*.log: "Print mode: not authenticated, trying
silent auth" -> "silent auth failed" -> "triggering interactive OAuth" ->
opens a browser). Only probe it live when explicitly asked (--check-antigravity,
or persisted on via `check-antigravity on` — see sai.cli.cmd_check_antigravity).
"""
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from sai.i18n import t
from sai.timeutil import _reset_with_countdown

NAME = "antigravity"
LABEL = "Antigravity (Google)"
BIN = "agy"
INSTALL_CMD = "curl -fsSL https://antigravity.google/cli/install.sh | bash"
UPDATE_CMD = ["agy", "update"]
# `agy --help` has no separate login subcommand at all — bare `agy`
# auto-detects a missing session and runs its own local-browser-or-URL flow.
LOGIN_CMD = ["agy"]
LOGIN_STATUS_CMD = None  # no non-interactive status subcommand exposed

# Module state for the --check-antigravity gate, read by status() below and
# by sai.cache.fetch_all_statuses (which special-cases this provider's
# cache entries around the gate — see the module docstring there). Same
# "module state behind get_/set_ instead of a bare global" shape as
# sai.i18n's current-language slot, for the same cross-module reason.
_check_enabled = False


def get_check_enabled():
    return _check_enabled


def set_check_enabled(value):
    global _check_enabled
    _check_enabled = value


def last_used_epoch():
    d = Path.home() / ".gemini" / "antigravity-cli" / "conversations"
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


def _format_iso_reset(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone()
        absolute = dt.strftime("%b %d, %H:%M %Z").strip()
        return _reset_with_countdown(absolute, epoch=dt.timestamp())
    except Exception:
        return iso_str


def status():
    if not _check_enabled:
        return {"pct_used": None, "rows": [], "note": t("note_antigravity_skipped"), "kind": "not-checked"}
    try:
        out = subprocess.run(
            ["agy", "-p", "/usage"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        out = ""
    # Real confirmed format (tab-separated, "% remaining" not "% used", one
    # row per underlying model bucket), e.g.:
    #   Gemini Models\tWeekly Limit Remaining\t62%\t2026-08-22T23:58:13Z
    #   Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-08-24T08:15:03Z
    # Confirmed live and replaces an earlier guess (copied blindly from
    # Claude's "% used" format) that never matched anything real.
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        m = re.match(r"(\d+)%", parts[2].strip())
        if not m:
            continue
        pct_used = 100 - int(m.group(1))
        rows.append((parts[0].strip(), pct_used, _format_iso_reset(parts[3].strip())))
    if not rows:
        return {"pct_used": None, "rows": [], "note": t("note_antigravity_no_usage"), "kind": "auth-needed"}
    pct_used = max(u for _, u, _ in rows)
    return {"pct_used": pct_used, "rows": rows, "note": None, "kind": "ok"}


def launch(yolo, prompt, cont):
    args = ["agy", "--dangerously-skip-permissions"]
    if cont:
        args.append("--continue")
    print(t("launch_antigravity", flags=" ".join(args[1:])))
    if prompt:
        args += ["--prompt-interactive", prompt]
    os.execvp(args[0], args)
