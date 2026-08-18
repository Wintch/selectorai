"""Claude Code provider."""
import os
import re
import subprocess
from pathlib import Path

from sai import session
from sai.i18n import t
from sai.providers.base import _extract
from sai.timeutil import _reset_with_countdown

NAME = "claude"
LABEL = "Claude Code (Anthropic)"
BIN = "claude"
INSTALL_CMD = "curl -fsSL https://claude.ai/install.sh | bash"
UPDATE_CMD = ["claude", "update"]
# Verified against `claude auth --help` -> `login` subcommand.
LOGIN_CMD = ["claude", "auth", "login"]
LOGIN_STATUS_CMD = ["claude", "auth", "status"]

# `claude models --help` (verified 2026-08-17, local audit) has no
# dedicated `models` subcommand at all — it just reprints the general
# --help text. The only place model names show up anywhere in the CLI is
# the --help text's own alias list. MODELS_STATIC (read by sai.models,
# not part of the provider contract itself) tells callers this list came
# from that static text, not a live query, so they can say so instead of
# implying it's fresh.
MODELS_STATIC = True
_STATIC_MODEL_ALIASES = ["fable", "opus", "sonnet", "haiku"]


def last_used_epoch():
    f = Path.home() / ".claude" / "history.jsonl"
    return int(f.stat().st_mtime) if f.exists() else 0


def status():
    try:
        out = subprocess.run(
            ["claude", "-p", "/usage"], capture_output=True, text=True, timeout=20
        ).stdout
    except Exception:
        out = ""
    session = _extract(out, r"Current session: (\d+)(?=% used)")
    s_reset = _extract(out, r"^Current session:.*resets (.*)$", re.M)
    week = _extract(out, r"Current week \(all models\): (\d+)(?=% used)")
    w_reset = _extract(out, r"^Current week \(all models\):.*resets (.*)$", re.M)
    fable = _extract(out, r"Current week \(Fable\): (\d+)(?=% used)")
    f_reset = _extract(out, r"^Current week \(Fable\):.*resets (.*)$", re.M)

    if session is None and week is None:
        return {"pct_used": None, "rows": [], "note": t("note_claude_login_expired"), "kind": "auth-needed"}
    session_i, week_i = int(session or 0), int(week or 0)
    rows = [
        (t("label_session_5h"), session_i, _reset_with_countdown(s_reset or t("unknown"))),
        (t("label_weekly"), week_i, _reset_with_countdown(w_reset or t("unknown"))),
    ]
    if fable is not None:
        rows.append((t("label_weekly_fable"), int(fable), _reset_with_countdown(f_reset or t("unknown"))))
    pct_used = session_i if session_i >= week_i else week_i
    return {"pct_used": pct_used, "rows": rows, "note": None, "kind": "ok"}


def list_models():
    # Static, not a probe — see MODELS_STATIC above for why there's
    # nothing to safely call here. list(...) so callers can't mutate the
    # module-level constant through the returned list.
    return list(_STATIC_MODEL_ALIASES)


def launch(yolo, prompt, cont):
    # Default: --permission-mode auto — Claude Code's own classifier
    # (rules-based allow/soft_deny/hard_deny, see `claude auto-mode
    # --help`) decides what to auto-approve, instead of bypassing
    # permission checks entirely. --yolo keeps the full bypass available
    # for when that's actually wanted, same shape as Codex's --yolo.
    if yolo:
        args = ["claude", "--dangerously-skip-permissions"]
    else:
        args = ["claude", "--permission-mode", "auto"]
    if cont:
        args.append("--continue")
    print(t("launch_claude", flags=" ".join(args[1:])))
    if prompt:
        args.append(prompt)
    # See sai/providers/codex.py's launch() comment: routed through
    # wrap_launch so a persisted `background on` runs this inside a
    # reattachable tmux session — no-op passthrough otherwise.
    args = session.wrap_launch(NAME, args)
    os.execvp(args[0], args)
