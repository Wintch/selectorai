"""Grok Build (xAI) provider.

Live usage check, gated behind --check-grok / `check-grok on` — same
opt-in-only shape as Antigravity's --check-antigravity, for a related but
distinct reason: this doesn't risk a surprise OAuth popup, but it does
mean spinning up a real interactive `grok` session inside a throwaway
tmux window just to read one screen, which is slow (~5-20s) and coupled
to grok's current TUI layout in a way a flag or JSON endpoint wouldn't be.
See _live_usage_limit() below for what's confirmed and why headless mode
can't do this instead.

EXPERIMENTAL, separately from the above: confirmed live (see docs/NOTES.md's
"Marked experimental" section) that the "Weekly limit" bar this scrapes
doesn't reliably predict the real cutoff — a free account got cut off
entirely while this same reading still said 0% used. status() always
appends a caveat row (see sai/providers/base.py's render_status_rows,
p == "grok" branch) when real numbers come back, not just on a failed
probe, since the risk is specifically in a number that looks fine.
"""
import os
import re
import subprocess
import time
from pathlib import Path

from sai import session
from sai.i18n import t
from sai.providers.base import parse_model_lines
from sai.timeutil import _reset_with_countdown

NAME = "grok"
LABEL = "Grok Build (xAI)"
BIN = "grok"
INSTALL_CMD = "curl -fsSL https://x.ai/cli/install.sh | bash"
UPDATE_CMD = ["grok", "update"]
# `grok login --help` -> `--device-auth` explicitly requests the URL+code
# flow (phone-friendly, vs. defaulting to auto-opening a local browser).
LOGIN_CMD = ["grok", "login", "--device-auth"]
LOGIN_STATUS_CMD = None  # no non-interactive status subcommand exposed either

# Module state for the --check-grok gate, same "module state behind
# get_/set_ instead of a bare global" shape as sai.providers.antigravity's
# _check_enabled, for the same cross-module reason (sai.cli reads/writes
# it, sai.cache's fetch_all_statuses reads it to decide cache freshness).
_check_enabled = False


def get_check_enabled():
    return _check_enabled


def set_check_enabled(value):
    global _check_enabled
    _check_enabled = value


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


_PROBE_SESSION = "selectorai-grok-probe"
_PROBE_READY_TIMEOUT = 20  # seconds — grok's own TUI boot time, observed
# live between 1s (warm) and ~15s (cold/slow network) on the machine this
# was built against; 20s leaves headroom without hanging forever on a
# genuinely broken session.


def _tmux(*args, timeout=10):
    try:
        return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def _capture_probe_pane():
    r = _tmux("capture-pane", "-t", _PROBE_SESSION, "-p")
    return r.stdout if r is not None and r.returncode == 0 else ""


def _live_usage_limit():
    """Scrapes the "Usage limit" tab of grok's own `/info` popup inside a
    throwaway tmux session — confirmed live (2026-08-18, Grok Build 1.0.5,
    free grok.com account) to be the ONLY place this data exists:

      - `grok -p "/status" --output-format json` (the same trick that
        works for Claude/Antigravity's headless usage) returns session
        info only (session ID, model, turn, context tokens) — no usage/
        reset fields at all, confirmed via the raw JSON.
      - `/usage`/`/cost` are not real slash commands in headless mode
        either — sent as a literal chat prompt, the model tries to
        research an answer instead of the CLI intercepting it.
      - `/info` (alias `/status`, `/session-info`) IS intercepted
        headlessly, but only returns that same session-info text — the
        tabbed popup (Context usage / Usage limit / Session info) a real
        interactive render produces is a pager-only UI feature with no
        headless equivalent.

    So the only way to reach "Weekly limit (Free) ... Resets: <date>" is
    to actually open the popup in a live render and read the screen:
    `/info` lands on "Session info" first, Tab cycles to "Context usage"
    then "Usage limit" (confirmed live; order intentionally not assumed
    fixed — this Tabs up to 3 times and stops as soon as "Weekly limit"
    appears in the pane, so a future reorder doesn't silently break it).

    Returns (label, pct_used, reset_text) or None if grok's session never
    became ready, or the pane never showed the Usage limit tab (e.g.
    reordered popup UI in a future grok version). Never raises.
    """
    if not session.available():  # tmux itself missing
        return None
    _tmux("kill-session", "-t", _PROBE_SESSION)  # clear any stale probe
    started = _tmux(
        "new-session", "-d", "-s", _PROBE_SESSION, "-x", "200", "-y", "50", "grok",
        timeout=10,
    )
    if started is None or started.returncode != 0:
        return None
    try:
        ready = False
        for _ in range(_PROBE_READY_TIMEOUT):
            if re.search(r"│\s*❯", _capture_probe_pane()):
                ready = True
                break
            time.sleep(1)
        if not ready:
            return None

        _tmux("send-keys", "-t", _PROBE_SESSION, "/info")
        time.sleep(0.3)
        _tmux("send-keys", "-t", _PROBE_SESSION, "Enter")
        time.sleep(2)

        pane = _capture_probe_pane()
        for _ in range(3):
            if "Weekly limit" in pane:
                break
            _tmux("send-keys", "-t", _PROBE_SESSION, "Tab")
            time.sleep(1)
            pane = _capture_probe_pane()
        else:
            return None

        # Label captured verbatim from the pane ("Weekly limit (Free)",
        # or presumably "(Plus)"/"(Heavy)" on a paid tier — never seen
        # live, so not hardcoded) rather than a static i18n string, same
        # reasoning as Antigravity's row labels below: it's grok's own
        # English UI text, not something this script authors itself.
        label_m = re.search(r"Weekly limit[^\n│]*", pane)
        if not label_m:
            return None
        # Anchored to start searching *after* the label match, not the
        # whole pane — a stale render of the previously-open tab (e.g.
        # "Context usage"'s own "(0.71%)" text) can still be on screen a
        # frame after Tab is sent, and that lives before "Weekly limit"
        # in the captured text, never after it.
        rest = pane[label_m.end():]
        pct_m = re.search(r"(\d+)%", rest)
        reset_m = re.search(r"Resets:\s*([^\n│]+)", rest)
        if not pct_m or not reset_m:
            return None
        return label_m.group(0).strip(), int(pct_m.group(1)), reset_m.group(1).strip()
    finally:
        _tmux("send-keys", "-t", _PROBE_SESSION, "Escape")
        time.sleep(0.2)
        _tmux("kill-session", "-t", _PROBE_SESSION)


def status():
    if not _check_enabled:
        return {"pct_used": None, "rows": [], "note": t("note_grok_skipped"), "kind": "not-checked"}
    result = _live_usage_limit()
    if result is None:
        # Deliberately "no-usage-api", not "auth-needed": unlike
        # Antigravity's empty-rows case (confirmed to specifically mean
        # sign-in-needed), a None here can just as easily mean the tmux
        # probe timed out or grok's popup layout moved — not a login
        # problem, so it shouldn't claim OFFLINE via health_reason_auth.
        return {"pct_used": None, "rows": [], "note": t("note_grok_no_usage"), "kind": "no-usage-api"}
    label, pct_used, reset_text = result
    row = (label, pct_used, _reset_with_countdown(reset_text))
    return {"pct_used": pct_used, "rows": [row], "note": None, "kind": "ok"}


def list_models():
    # `grok models --help` -> "List available models and exit" (verified
    # 2026-08-17, local audit: full `grok --help` command list). Same
    # caution class as Antigravity's list_models() above: the subcommand's
    # *existence* is confirmed, its auth behavior on a bare invocation is
    # not — this account has never run it. Callers must only reach this
    # from the explicit `models` subcommand, never status/menu code.
    try:
        out = subprocess.run(["grok", "models"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    return parse_model_lines(out)


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
    # See sai/providers/codex.py's launch() comment: routed through
    # wrap_launch so a persisted `background on` runs this inside a
    # reattachable tmux session — no-op passthrough otherwise.
    args = session.wrap_launch(NAME, args)
    os.execvp(args[0], args)
