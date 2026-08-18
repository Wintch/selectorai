"""Codex CLI provider."""
import os
import re
import subprocess
import time
from pathlib import Path

from sai import paths, session
from sai.i18n import t
from sai.timeutil import _reset_with_countdown

NAME = "codex"
LABEL = "Codex CLI (OpenAI)"
BIN = "codex"
INSTALL_CMD = "curl -fsSL https://chatgpt.com/codex/install.sh | sh"
UPDATE_CMD = ["codex", "update"]
# `codex login --help` -> `--device-auth` explicitly requests the URL+code
# flow (phone-friendly, vs. defaulting to auto-opening a local browser).
LOGIN_CMD = ["codex", "login", "--device-auth"]
LOGIN_STATUS_CMD = ["codex", "login", "status"]


def last_used_epoch():
    f = Path.home() / ".codex" / "history.jsonl"
    return int(f.stat().st_mtime) if f.exists() else 0


def status():
    # `paths.STATE_DIR` (not a name imported at module load time) so tests
    # can point it at a tempdir by monkeypatching sai.paths.STATE_DIR
    # before calling status() — see tests/test_status_shapes.py.
    msg_f = paths.STATE_DIR / "codex.ratelimited.msg"
    until_f = paths.STATE_DIR / "codex.ratelimited.until"
    if until_f.exists():
        try:
            until = int(until_f.read_text().strip() or 0)
        except ValueError:
            until = 0
        if until > time.time():
            msg = msg_f.read_text().strip() if msg_f.exists() else t("unknown")
            reset = _reset_with_countdown(msg, epoch=until)
            return {"pct_used": 100, "rows": [(t("label_limit"), 100, reset)], "note": None, "kind": "ok"}
        msg_f.unlink(missing_ok=True)
        until_f.unlink(missing_ok=True)
    elif msg_f.exists():
        msg = msg_f.read_text().strip()
        note = t("note_codex_unknown_date", msg=msg)
        return {"pct_used": 95, "rows": [(t("label_limit"), 95, note)], "note": None, "kind": "ok"}
    return {"pct_used": None, "rows": [], "note": t("note_codex_no_cli_usage"), "kind": "no-usage-api"}


# record_codex_ratelimit/clear_codex_ratelimit: nothing calls these anymore.
# Assumed, not verified against an old revision: the likely old call site
# (capturing a launch's stderr for a "usage limit" error) would have gone
# away once launches became exec'd (see launch() below and
# docs/ARCHITECTURE.md rule 3: exec'd, never piped, so there's no captured
# output left to scan). Kept anyway, not deleted: they're the only way
# `codex.ratelimited.msg`/`.until` (read by status() above) ever get
# written, and re-adding a non-exec capture path (e.g. a `--check-codex`
# probe mirroring Antigravity's) would call straight back into these
# instead of reinventing the parsing. Confirmed dead code, not a bug.
def record_codex_ratelimit(text):
    m = re.search(r"try again at ([^.]*)", text)
    if not m:
        return
    msg = m.group(1).strip()
    (paths.STATE_DIR / "codex.ratelimited.msg").write_text(msg)
    clean = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", msg)
    until_f = paths.STATE_DIR / "codex.ratelimited.until"
    try:
        r = subprocess.run(["date", "-d", clean, "+%s"], capture_output=True, text=True, timeout=5)
    except Exception:
        r = None
    if r is not None and r.returncode == 0 and r.stdout.strip():
        until_f.write_text(r.stdout.strip())
    else:
        until_f.unlink(missing_ok=True)


def clear_codex_ratelimit():
    (paths.STATE_DIR / "codex.ratelimited.msg").unlink(missing_ok=True)
    (paths.STATE_DIR / "codex.ratelimited.until").unlink(missing_ok=True)


def list_models():
    # No `models` subcommand anywhere in `codex --help` (verified
    # 2026-08-17, local audit) — model choice is only ever a `-m <name>`
    # flag on individual invocations, with no enumerable list exposed by
    # the CLI at all. Nothing to return.
    return None


def launch(yolo, prompt, cont):
    if yolo:
        print(t("launch_codex_yolo"))
        extra = ["--dangerously-bypass-approvals-and-sandbox"]
    else:
        print(t("launch_codex_safe"))
        extra = ["--ask-for-approval", "never", "--sandbox", "workspace-write"]
    sub = []
    if cont:
        print(t("launch_codex_resume"))
        sub = ["resume", "--last"]
    args = ["codex"] + sub + extra
    if prompt:
        args.append(prompt)
    # exec'd, same as claude/agy — Codex is a full-screen TUI and checks
    # isatty(stdout) at startup. Routed through wrap_launch so a persisted
    # `background on` (see sai/session.py) transparently runs this inside
    # a reattachable tmux session instead — a no-op argv passthrough when
    # tmux is unavailable/disabled/already-nested.
    args = session.wrap_launch(NAME, args)
    os.execvp(args[0], args)
