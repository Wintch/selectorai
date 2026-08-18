#!/usr/bin/env python3
# selectorai — installs/updates your AI CLIs and recommends which one to use
# based on how much quota is left and how long since you last used it.
# Python port of selectorai.sh. Same state dir, same log format.
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zoneinfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

STATE_DIR = Path.home() / ".selectorai"
LAUNCH_LOG = STATE_DIR / "launch.log"
LANG_FILE = STATE_DIR / "lang"
CACHE_FILE = STATE_DIR / "cache.json"
DEFAULT_CACHE_TTL = 60  # seconds
FORCE_REFRESH = False

# Off by default: probing Antigravity ("agy -p /usage") while not logged in
# triggers its real interactive Google OAuth flow (confirmed in
# ~/.gemini/antigravity-cli/log/*.log: "Print mode: not authenticated, trying
# silent auth" -> "silent auth failed" -> "triggering interactive OAuth" ->
# opens a browser). Only probe it live when explicitly asked (--check-antigravity,
# or persisted on via `check-antigravity on` — see cmd_check_antigravity).
CHECK_ANTIGRAVITY = False
CHECK_ANTIGRAVITY_FILE = STATE_DIR / "check_antigravity"

# No equivalent CHECK_GROK gate: confirmed (not just precautionary) that
# there's no live usage check to gate in the first place — see
# provider_status_grok() for why.

PROVIDERS = ["claude", "codex", "antigravity", "grok"]

PROVIDER_BIN = {"claude": "claude", "codex": "codex", "antigravity": "agy", "grok": "grok"}
PROVIDER_LABEL = {
    "claude": "Claude Code",
    "codex": "Codex CLI",
    "antigravity": "Antigravity (Google)",
    "grok": "Grok Build (xAI)",
}
PROVIDER_INSTALL_CMD = {
    "claude": "curl -fsSL https://claude.ai/install.sh | bash",
    "codex": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
    "antigravity": "curl -fsSL https://antigravity.google/cli/install.sh | bash",
    "grok": "curl -fsSL https://x.ai/cli/install.sh | bash",
}
PROVIDER_UPDATE_CMD = {
    "claude": ["claude", "update"],
    "codex": ["codex", "update"],
    "antigravity": ["agy", "update"],
    "grok": ["grok", "update"],
}
# Each provider's own login entry point, verified against its real --help:
# `claude auth --help` -> `login` subcommand; `codex login --help` /
# `grok login --help` -> `--device-auth` explicitly requests the URL+code
# flow (phone-friendly, vs. defaulting to auto-opening a local browser);
# `agy --help` has no separate login subcommand at all — bare `agy`
# auto-detects a missing session and runs its own local-browser-or-URL flow.
PROVIDER_LOGIN_CMD = {
    "claude": ["claude", "auth", "login"],
    "codex": ["codex", "login", "--device-auth"],
    "antigravity": ["agy"],
    "grok": ["grok", "login", "--device-auth"],
}
PROVIDER_LOGIN_STATUS_CMD = {
    "claude": ["claude", "auth", "status"],
    "codex": ["codex", "login", "status"],
    "antigravity": None,  # no non-interactive status subcommand exposed
    "grok": None,  # no non-interactive status subcommand exposed either
}

# ---------------------------------------------------------------------------
# i18n — default English, plus Russian and Spanish. Strings live in
# i18n/<code>.json next to this script, not inline in the code, so adding
# or editing a translation doesn't mean touching Python. `t(key, **kwargs)`
# looks up STRINGS[LANG][key] and falls back to English, then the raw key.
# ---------------------------------------------------------------------------

I18N_DIR = Path(__file__).resolve().parent / "i18n"
LANG_CODES = ["en", "ru", "es"]
LANG = "en"  # overwritten in main() before anything is printed


def _load_strings():
    strings, names = {}, {}
    for code in LANG_CODES:
        try:
            data = json.loads((I18N_DIR / f"{code}.json").read_text(encoding="utf-8"))
        except Exception:
            data = {}
        names[code] = data.pop("_name", code)
        strings[code] = data
    return strings, names


STRINGS, LANG_NAMES = _load_strings()


def t(key, **kwargs):
    s = STRINGS.get(LANG, STRINGS["en"]).get(key) or STRINGS["en"].get(key, key)
    return s.format(**kwargs) if kwargs else s


def _prompt(text):
    """input() that fails quietly instead of a raw traceback when stdin
    has no more input (piped, closed, or Ctrl-D/Ctrl-C mid-prompt)."""
    try:
        return input(text)
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def resolve_lang(override):
    if override and override in LANG_CODES:
        return override
    env = os.environ.get("SELECTORAI_LANG")
    if env and env in LANG_CODES:
        return env
    if LANG_FILE.exists():
        saved = LANG_FILE.read_text().strip()
        if saved in LANG_CODES:
            return saved
    return "en"


def cmd_lang(argv):
    global LANG
    if argv:
        choice = argv[0]
        if choice not in LANG_CODES:
            print(t("lang_invalid", choice=choice, options=", ".join(LANG_CODES)))
            sys.exit(1)
    else:
        print("Pick a language / Elegí un idioma / Выберите язык:")
        for i, code in enumerate(LANG_CODES, start=1):
            print(f"  {i}) {LANG_NAMES[code]} ({code})")
        raw = (_prompt("> ") or "").strip()
        if raw in LANG_CODES:
            choice = raw
        else:
            try:
                choice = LANG_CODES[int(raw) - 1]
            except (ValueError, IndexError):
                print("Invalid choice.")
                sys.exit(1)
    LANG_FILE.write_text(choice)
    LANG = choice
    print(t("lang_saved", lang=LANG_NAMES[choice]))


# ---------------------------------------------------------------------------
# Big block-letter font — hand-built, verified by rendering it and reading
# the output before committing it here (not eyeballed blind). Covers only
# the characters actually used: the title "SELECTORAI" and the provider
# labels below. Each glyph is a list of 6 row-strings.
# ---------------------------------------------------------------------------

FONT = {
    "A": [" ██ ", "█  █", "█  █", "████", "█  █", "█  █"],
    "C": [" ███", "█   ", "█   ", "█   ", "█   ", " ███"],
    "D": ["███ ", "█  █", "█  █", "█  █", "█  █", "███ "],
    "E": ["████", "█   ", "███ ", "█   ", "█   ", "████"],
    "G": [" ███", "█   ", "█ ██", "█  █", "█  █", " ███"],
    "I": ["████", " █  ", " █  ", " █  ", " █  ", "████"],
    "K": ["█  █", "█ █ ", "██  ", "█ █ ", "█  █", "█  █"],
    "L": ["█   ", "█   ", "█   ", "█   ", "█   ", "████"],
    "N": ["█  █", "██ █", "█ ██", "█  █", "█  █", "█  █"],
    "O": [" ██ ", "█  █", "█  █", "█  █", "█  █", " ██ "],
    "R": ["███ ", "█  █", "███ ", "█ █ ", "█  █", "█  █"],
    "S": [" ███", "█   ", " ██ ", "   █", "   █", "███ "],
    "T": ["████", " █  ", " █  ", " █  ", " █  ", " █  "],
    "U": ["█  █", "█  █", "█  █", "█  █", "█  █", " ██ "],
    "V": ["█  █", "█  █", "█  █", "█  █", " ██ ", " ██ "],
    "X": ["█  █", "█  █", " ██ ", " ██ ", "█  █", "█  █"],
    "Y": ["█  █", "█  █", " ██ ", " █  ", " █  ", " █  "],
    " ": ["  ", "  ", "  ", "  ", "  ", "  "],
}


def render_big(text):
    rows = ["" for _ in range(6)]
    for ch in text.upper():
        glyph = FONT.get(ch, FONT[" "])
        for i in range(6):
            rows[i] += glyph[i] + " "
    return [r.rstrip() for r in rows]


# ---------------------------------------------------------------------------
# Picker theme — the "front" kept separate from the picker's actual logic
# (widget structure, key handling, selection) on purpose: each theme is
# just a Textual stylesheet file under themes/, nothing else changes.
# Dropping in a new themes/<name>.tcss makes it selectable automatically —
# no code touched. Reference screens: green monochrome MU-TH-UR-style HUD
# for "mother" (default), cyan/amber/red Nostromo deorbital-descent
# computer for "nostromo".
# ---------------------------------------------------------------------------

THEMES_DIR = Path(__file__).resolve().parent / "themes"
THEME_FILE = STATE_DIR / "theme"
DEFAULT_THEME = "mother"


def list_themes():
    if not THEMES_DIR.is_dir():
        return []
    return sorted(p.stem for p in THEMES_DIR.glob("*.tcss"))


def current_theme():
    if THEME_FILE.exists():
        saved = THEME_FILE.read_text().strip()
        if saved in list_themes():
            return saved
    return DEFAULT_THEME if DEFAULT_THEME in list_themes() else (list_themes() or [None])[0]


def cmd_theme(argv):
    themes = list_themes()
    if not themes:
        print(f"No themes found under {THEMES_DIR}/")
        sys.exit(1)

    if argv:
        choice = argv[0]
        if choice not in themes:
            print(f"Unknown theme '{choice}'. Options: {', '.join(themes)}")
            sys.exit(1)
    else:
        cur = current_theme()
        print("Current theme:", cur)
        print()
        for i, name in enumerate(themes, start=1):
            mark = " (current)" if name == cur else ""
            print(f"  {i}) {name}{mark}")
        raw = (_prompt("Pick a theme: ") or "").strip()
        choice = themes[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(themes) else raw
        if choice not in themes:
            print("Invalid choice.")
            sys.exit(1)

    THEME_FILE.write_text(choice)
    print(f"Theme set to: {choice}")


def cmd_check_antigravity(argv):
    if argv and argv[0] == "on":
        CHECK_ANTIGRAVITY_FILE.write_text("1")
        print(
            "Antigravity live usage check: ON by default now — every `status`/menu run "
            "will call `agy -p \"/usage\"`.\nReminder: Antigravity's own session handling "
            "is flaky upstream (antigravity-cli#57/#18) — even logged in, this can still "
            "pop a fresh Google login prompt on any given run, not just the first one.\n"
            "Turn it back off any time: ./selectorai.py check-antigravity off"
        )
    elif argv and argv[0] == "off":
        CHECK_ANTIGRAVITY_FILE.unlink(missing_ok=True)
        print(
            "Antigravity live usage check: OFF by default (back to opt-in only — pass "
            "--check-antigravity for a single run instead)."
        )
    else:
        state = "on" if CHECK_ANTIGRAVITY_FILE.exists() else "off"
        print(f"Antigravity live usage check is currently: {state}")
        print("  ./selectorai.py check-antigravity on   # persist: always probe")
        print("  ./selectorai.py check-antigravity off  # persist: opt-in only (default)")
        print("  ./selectorai.py --check-antigravity    # probe just for this one run, don't persist")


# ---------------------------------------------------------------------------
# Per-provider metadata
# ---------------------------------------------------------------------------


def provider_installed(p):
    return shutil.which(PROVIDER_BIN[p]) is not None


def provider_install(p):
    subprocess.run(PROVIDER_INSTALL_CMD[p], shell=True)


def provider_update(p):
    subprocess.run(PROVIDER_UPDATE_CMD[p])


def provider_last_used_epoch(p):
    if p in ("claude", "codex"):
        f = Path.home() / f".{p}" / "history.jsonl"
        return int(f.stat().st_mtime) if f.exists() else 0
    if p == "antigravity":
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
    if p == "grok":
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
    return 0


def _extract(text, pattern, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


def _format_countdown(seconds):
    if seconds is None:
        return None
    if seconds <= 0:
        return t("countdown_now")
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d > 0:
        return t("countdown_dh", d=d, h=h)
    if h > 0:
        return t("countdown_hm", h=h, m=m)
    return t("countdown_m", m=m)


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_reset_epoch(text):
    """Best-effort: turn a human reset string like 'Aug 21, 4am (America/
    Argentina/Buenos_Aires)' into a Unix epoch. First attempts microsecond-fast
    pure-Python parsing (datetime + zoneinfo) without spawning subprocesses,
    falling back to GNU date only if needed."""
    if not text:
        return None
    m = re.search(r"\(([^)]+)\)\s*$", text)
    tz_name, date_part = None, text
    if m:
        tz_name = m.group(1)
        date_part = text[: m.start()].strip()

    # 1. Fast ISO parse
    try:
        dt = datetime.fromisoformat(date_part.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        pass

    # 2. Fast pure-Python parse for Claude / Codex human dates
    clean = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", date_part).replace(",", "").strip()
    mm = re.match(r"([A-Za-z]+)\s+(\d+)(?:\s+(\d{4}))?\s+(\d+)(?::(\d+))?\s*(am|pm)?", clean, re.I)
    if mm:
        mon_str, day_s, year_s, hour_s, min_s, ampm = mm.groups()
        mon = _MONTHS.get(mon_str.lower()[:3])
        if mon:
            hour = int(hour_s)
            minute = int(min_s) if min_s else 0
            if ampm:
                if ampm.lower() == "pm" and hour != 12:
                    hour += 12
                elif ampm.lower() == "am" and hour == 12:
                    hour = 0
            now = datetime.now()
            year = int(year_s) if year_s else now.year
            tz = None
            if tz_name:
                try:
                    tz = zoneinfo.ZoneInfo(tz_name)
                except Exception:
                    pass
            try:
                dt = datetime(year, mon, int(day_s), hour, minute, tzinfo=tz)
                if not year_s and dt.timestamp() < time.time() - 30 * 86400:
                    dt = dt.replace(year=year + 1)
                return int(dt.timestamp())
            except Exception:
                pass

    # 3. Fallback to `date -d`
    date_part_gnu = date_part.replace(",", "")
    if date_part_gnu:
        date_arg = f'TZ="{tz_name}" {date_part_gnu}' if tz_name else date_part_gnu
        try:
            r = subprocess.run(["date", "-d", date_arg, "+%s"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return int(r.stdout.strip())
        except Exception:
            pass
    return None


def _reset_with_countdown(absolute_text, epoch=None):
    """Combine an absolute reset string with a computed countdown — from a
    known epoch when the caller already has one (Codex's saved rate-limit
    timestamp, Antigravity's parsed ISO time), otherwise by best-effort
    parsing the text itself (Claude's raw /usage reset strings)."""
    if epoch is None:
        epoch = _parse_reset_epoch(absolute_text)
    if epoch is None:
        return absolute_text
    countdown = _format_countdown(epoch - time.time())
    return f"{countdown} — {absolute_text}" if countdown else absolute_text


# provider_status() return shape, kept explicit everywhere to stay coherent
# about used vs. left instead of mixing bare percentages:
#   {"pct_used": int|None, "rows": [(label, pct_used, reset_info), ...], "note": str|None}


def provider_status_claude():
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
        return {"pct_used": None, "rows": [], "note": t("note_claude_login_expired")}
    session_i, week_i = int(session or 0), int(week or 0)
    rows = [
        (t("label_session_5h"), session_i, _reset_with_countdown(s_reset or t("unknown"))),
        (t("label_weekly"), week_i, _reset_with_countdown(w_reset or t("unknown"))),
    ]
    if fable is not None:
        rows.append((t("label_weekly_fable"), int(fable), _reset_with_countdown(f_reset or t("unknown"))))
    pct_used = session_i if session_i >= week_i else week_i
    return {"pct_used": pct_used, "rows": rows, "note": None}


def provider_status_codex():
    msg_f = STATE_DIR / "codex.ratelimited.msg"
    until_f = STATE_DIR / "codex.ratelimited.until"
    if until_f.exists():
        try:
            until = int(until_f.read_text().strip() or 0)
        except ValueError:
            until = 0
        if until > time.time():
            msg = msg_f.read_text().strip() if msg_f.exists() else t("unknown")
            reset = _reset_with_countdown(msg, epoch=until)
            return {"pct_used": 100, "rows": [(t("label_limit"), 100, reset)], "note": None}
        msg_f.unlink(missing_ok=True)
        until_f.unlink(missing_ok=True)
    elif msg_f.exists():
        msg = msg_f.read_text().strip()
        note = t("note_codex_unknown_date", msg=msg)
        return {"pct_used": 95, "rows": [(t("label_limit"), 95, note)], "note": None}
    return {"pct_used": None, "rows": [], "note": t("note_codex_no_cli_usage")}


def _format_iso_reset(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone()
        absolute = dt.strftime("%b %d, %H:%M %Z").strip()
        return _reset_with_countdown(absolute, epoch=dt.timestamp())
    except Exception:
        return iso_str


def provider_status_antigravity():
    if not CHECK_ANTIGRAVITY:
        return {"pct_used": None, "rows": [], "note": t("note_antigravity_skipped")}
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
        return {"pct_used": None, "rows": [], "note": t("note_antigravity_no_usage")}
    pct_used = max(u for _, u, _ in rows)
    return {"pct_used": pct_used, "rows": rows, "note": None}


def provider_status_grok():
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
    return {"pct_used": None, "rows": [], "note": t("note_grok_no_headless_usage")}


def provider_status(p):
    if p == "claude":
        return provider_status_claude()
    if p == "codex":
        return provider_status_codex()
    if p == "antigravity":
        return provider_status_antigravity()
    if p == "grok":
        return provider_status_grok()
    return {"pct_used": None, "rows": [], "note": t("note_no_status_configured")}


def provider_summary(status):
    pct = status["pct_used"]
    if pct is None:
        return status["note"] or t("summary_no_data")
    left = 100 - pct
    label, reset = None, None
    for l, u, r in status["rows"]:
        if u == pct:
            label, reset = l, r
            break
    if reset:
        reset = re.sub(r" *\([^)]*\)\s*$", "", reset)
    if label:
        return t("summary_both", left=left, pct=pct, label=label, reset=reset or t("unknown"))
    return t("summary_both_nolabel", left=left, pct=pct)


def record_codex_ratelimit(text):
    m = re.search(r"try again at ([^.]*)", text)
    if not m:
        return
    msg = m.group(1).strip()
    (STATE_DIR / "codex.ratelimited.msg").write_text(msg)
    clean = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", msg)
    until_f = STATE_DIR / "codex.ratelimited.until"
    try:
        r = subprocess.run(["date", "-d", clean, "+%s"], capture_output=True, text=True, timeout=5)
    except Exception:
        r = None
    if r is not None and r.returncode == 0 and r.stdout.strip():
        until_f.write_text(r.stdout.strip())
    else:
        until_f.unlink(missing_ok=True)


def clear_codex_ratelimit():
    (STATE_DIR / "codex.ratelimited.msg").unlink(missing_ok=True)
    (STATE_DIR / "codex.ratelimited.until").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Machine status — pure /proc + stdlib os calls, no subprocess, no tty ioctl,
# nothing that can prompt for elevated permission. Shown by default.
# ---------------------------------------------------------------------------


def _mem_usage():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])
        total, avail = info.get("MemTotal"), info.get("MemAvailable")
        if not total or avail is None:
            return None, None
        return (total - avail) / total * 100, total / 1024 / 1024
    except Exception:
        return None, None


def _disk_usage():
    try:
        du = shutil.disk_usage("/")
        return du.used / du.total * 100, du.free / (1024**3)
    except Exception:
        return None, None


def _uptime():
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
    except Exception:
        return None
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = [f"{d}d"] if d else []
    if h or d:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


def machine_status():
    lines = []
    try:
        load1, load5, load15 = os.getloadavg()
        ncpu = os.cpu_count() or 1
        ratio = load1 / ncpu
        if ratio < 0.7:
            verdict = t("ms_load_ok")
        elif ratio < 1.0:
            verdict = t("ms_load_moderate")
        else:
            verdict = t("ms_load_high")
        lines.append(t("ms_load", l1=load1, l5=load5, l15=load15, ncpu=ncpu, verdict=verdict))
    except OSError:
        pass

    mem_pct, mem_total_gb = _mem_usage()
    if mem_pct is not None:
        verdict = f"⚠ {t('ms_mem_high')}" if mem_pct >= 80 else t("ms_mem_ok")
        lines.append(t("ms_mem", pct=mem_pct, total=mem_total_gb, verdict=verdict))

    disk_pct, disk_free_gb = _disk_usage()
    if disk_pct is not None:
        verdict = f"⚠ {t('ms_disk_low')}" if disk_pct >= 80 else t("ms_disk_ok")
        lines.append(t("ms_disk", pct=disk_pct, free=disk_free_gb, verdict=verdict))

    uptime = _uptime()
    if uptime:
        lines.append(t("ms_uptime", uptime=uptime))

    return lines


# ---------------------------------------------------------------------------
# Who's connected — opt-in only (`status --who`), never runs by default.
# Self-detection uses env vars (SSH_CONNECTION/SSH_TTY/SSH_CLIENT), not
# os.ttyname()/ioctl — that call errors out under a non-tty stdin anyway and
# is the kind of thing that can trip a permission prompt; env vars need none.
# ---------------------------------------------------------------------------


def _is_remote_session():
    return any(os.environ.get(v) for v in ("SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT"))


def _own_client_ip():
    conn = os.environ.get("SSH_CONNECTION", "")
    parts = conn.split()
    return parts[0] if parts else None


_WHO_LINE_RE = re.compile(r"(\S+)\s+(\S+)\s+(.*?)(?:\s+\(([^)]+)\))?$")


def who_status():
    lines = []
    remote = _is_remote_session()
    own_ip = _own_client_ip()
    if remote:
        origin = t("who_origin_remote_ip", ip=own_ip) if own_ip else t("who_origin_remote")
    else:
        origin = t("who_origin_local")
    lines.append(t("who_self", origin=origin))

    try:
        out = subprocess.run(["who"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        lines.append(t("who_no_who"))
        return lines

    sessions = []
    for line in out.splitlines():
        m = _WHO_LINE_RE.match(line)
        if m:
            user, tty, when, host = m.groups()
            sessions.append((user, tty, when.strip(), host))
    if not sessions:
        lines.append(t("who_no_sessions"))
        return lines

    me = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    remote_hosts = sorted(
        {h for (_, _, _, h) in sessions if h and h not in ("localhost", "127.0.0.1", "::1")}
    )
    other_users = sorted({u for (u, _, _, _) in sessions if u != me})
    total = len(sessions)

    if not remote_hosts and not other_users:
        lines.append(t("who_alone", n=total, user=me or "?"))
    else:
        lines.append(t("who_not_alone", n=total))
        for user, tty, when, host in sessions:
            origin = t("who_origin_remote_from", host=host) if host else t("who_origin_local")
            lines.append(t("who_session_line", user=user, tty=tty, origin=origin, when=when))
        if remote_hosts:
            lines.append(t("who_remote_ips", ips=", ".join(remote_hosts)))
        if other_users:
            lines.append(t("who_other_users", users=", ".join(other_users)))
    return lines


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def fmt_ago(ts):
    if ts <= 0:
        return t("ago_never")
    diff = int(time.time()) - ts
    if diff < 60:
        return t("ago_s", n=diff)
    if diff < 3600:
        return t("ago_m", n=diff // 60)
    if diff < 86400:
        return t("ago_h", n=diff // 3600)
    return t("ago_d", n=diff // 86400)


def log_launch(provider, mode):
    with open(LAUNCH_LOG, "a") as f:
        f.write(f"{int(time.time())}\t{provider}\t{mode}\n")


# ---------------------------------------------------------------------------
# install / update
# ---------------------------------------------------------------------------


def cmd_install():
    for p in PROVIDERS:
        print(f"== {PROVIDER_LABEL[p]} ==")
        if provider_installed(p):
            print(t("install_updating"))
            provider_update(p)
        else:
            print(t("install_installing"))
            provider_install(p)
        print()


# ---------------------------------------------------------------------------
# auth / login — same "clean URL" wrapper for every provider, specific login
# command per provider. Triggered only on explicit request (`auth`), never
# automatically, same principle as --check-antigravity above.
# ---------------------------------------------------------------------------

_URL_BLOCK_RE = re.compile(r"https?://\S.*", re.S)


def run_login_capture(p):
    cmd = PROVIDER_LOGIN_CMD[p]
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
        # one of our own fixed PROVIDER_LOGIN_CMD lists, never user input, so
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

    status_cmd = PROVIDER_LOGIN_STATUS_CMD.get(p)
    if status_cmd:
        print()
        print(t("auth_status_header"))
        subprocess.run(status_cmd)


def cmd_auth(argv):
    if not argv:
        targets = PROVIDERS
    else:
        unknown = [a for a in argv if a not in PROVIDERS]
        if unknown:
            print(f"Unknown provider(s): {', '.join(unknown)}. Options: {', '.join(PROVIDERS)}")
            sys.exit(1)
        targets = argv
    for p in targets:
        if not provider_installed(p):
            print(t("status_not_installed", label=PROVIDER_LABEL[p]))
            continue
        print(f"== {PROVIDER_LABEL[p]} ==")
        run_login_capture(p)
        print()


# ---------------------------------------------------------------------------
# status / menu
# ---------------------------------------------------------------------------


def _render_tree(header, rows):
    lines = [t("status_tree_header", label=header)]
    for i, (label, used, reset) in enumerate(rows):
        connector = "└─" if i == len(rows) - 1 else "├─"
        left = 100 - used
        lines.append(t("status_row", label=f"{connector} {label}", used=used, left=left, reset=reset))
    return lines


def _render_claude_rows(rows):
    """Session stays a flat row, but Weekly and Weekly (Fable) are two
    parallel quotas for different model pools under the same weekly window
    — same shape as a directory with two files in it, or two branches off
    one trunk. Grouping them that way beats two same-looking flat rows."""
    lines = []
    by_label = {label: (used, reset) for label, used, reset in rows}
    weekly_label = t("label_weekly")
    fable_label = t("label_weekly_fable")

    for label, used, reset in rows:
        if label in (weekly_label, fable_label):
            continue
        left = 100 - used
        lines.append(t("status_row", label=label, used=used, left=left, reset=reset))

    branches = []
    if weekly_label in by_label:
        branches.append((t("label_weekly_all"), *by_label[weekly_label]))
    if fable_label in by_label:
        branches.append((t("label_fable_short"), *by_label[fable_label]))
    if branches:
        lines.extend(_render_tree(weekly_label, branches))
    return lines


def render_status_rows(p, status):
    """Same idea as _render_claude_rows, applied to Antigravity: its two
    buckets (Gemini Models / Claude and GPT models) are equally parallel —
    they just don't share a common label prefix to group under, so the
    header is a generic one instead of a real shared label."""
    if not status["rows"]:
        return [f"  {status['note'] or t('status_no_data')}"]
    if p == "claude":
        return _render_claude_rows(status["rows"])
    if p == "antigravity" and len(status["rows"]) > 1:
        return _render_tree(t("label_weekly_limits"), status["rows"])
    lines = []
    for label, used, reset in status["rows"]:
        left = 100 - used
        lines.append(t("status_row", label=label, used=used, left=left, reset=reset))
    return lines


def print_status_block(p, status):
    last = provider_last_used_epoch(p)
    print(t("status_last_used", label=PROVIDER_LABEL[p], ago=fmt_ago(last)))
    for line in render_status_rows(p, status):
        print(line)
    print()


# ---------------------------------------------------------------------------
# Terminal progress bar & status cache
# ---------------------------------------------------------------------------


class TerminalProgress:
    """Thread-safe terminal progress bar with animated spinner.
    Automatically erases itself upon finish when output is a tty,
    providing clean feedback without leaving terminal clutter."""

    def __init__(self, total, title="", enabled=True):
        self.total = max(1, total)
        self.current = 0
        self.enabled = enabled and sys.stdout.isatty()
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.frame_idx = 0
        self.current_action = title
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        if self.enabled:
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._thread.start()

    def _animate(self):
        while not self._stop_event.is_set():
            with self._lock:
                self._render()
            time.sleep(0.08)

    def update(self, advance=1, text=None):
        with self._lock:
            self.current = min(self.total, self.current + advance)
            if text is not None:
                self.current_action = text
            self._render()

    def set_text(self, text):
        with self._lock:
            self.current_action = text
            self._render()

    def _render(self):
        if not self.enabled:
            return
        pct = int(self.current / self.total * 100)
        bar_len = 20
        filled = int(bar_len * self.current / self.total)
        bar = "█" * filled + "░" * (bar_len - filled)
        spinner = self.spinner_frames[self.frame_idx % len(self.spinner_frames)]
        self.frame_idx += 1
        msg = f"\r\033[K{spinner} [{bar}] {pct:3d}%  {self.current_action}"
        sys.stdout.write(msg)
        sys.stdout.flush()

    def finish(self, clear=True):
        if not self.enabled:
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)
        if clear:
            sys.stdout.write("\r\033[K")
        else:
            sys.stdout.write("\n")
        sys.stdout.flush()


def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache):
    try:
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


# Antigravity gets a much longer cache window than everything else — not
# for freshness (a weekly quota doesn't need per-minute updates), but as a
# backoff: its own session handling is flaky upstream (antigravity-cli
# issues #57/#18), so a live check can trigger a fresh Google OAuth popup
# even right after a prior success. With the default 60s TTL, every picker
# launch more than a minute apart re-attempts the risky call — this stretches
# that to once per half hour at most (still forced sooner if the
# --check-antigravity toggle itself just changed — see the was_skipped
# check in fetch_all_statuses, which bypasses this TTL entirely for that
# specific case).
_CACHE_TTL_OVERRIDES = {"antigravity": 1800}


def _cache_ttl(p):
    return _CACHE_TTL_OVERRIDES.get(p, DEFAULT_CACHE_TTL)


def fetch_all_statuses(providers, force_refresh=False, show_progress=True):
    now = time.time()
    cache = load_cache() if not force_refresh else {}
    cached_map = cache.get("statuses", {})

    statuses = {}
    to_query = []

    for p in providers:
        if not force_refresh and p in cached_map:
            entry = cached_map[p]
            ts = entry.get("timestamp", 0)
            st = entry.get("status")
            if now - ts < _cache_ttl(p) and st is not None:
                if p == "antigravity":
                    was_skipped = st.get("note") == t("note_antigravity_skipped")
                    if (CHECK_ANTIGRAVITY and was_skipped) or (not CHECK_ANTIGRAVITY and not was_skipped):
                        to_query.append(p)
                        continue
                # No grok equivalent: its status never depends on a toggle
                # anymore (see provider_status_grok), so plain TTL caching
                # is enough — nothing to detect a mismatch against.
                statuses[p] = st
                continue
        to_query.append(p)

    if not to_query:
        return statuses

    progress = None
    if show_progress and sys.stdout.isatty():
        initial_title = t("progress_connecting")
        progress = TerminalProgress(len(to_query), title=initial_title)

    with ThreadPoolExecutor(max_workers=len(to_query)) as ex:
        fut_to_p = {ex.submit(provider_status, p): p for p in to_query}
        for fut in as_completed(fut_to_p):
            p = fut_to_p[fut]
            try:
                st = fut.result()
            except Exception as e:
                st = {"pct_used": None, "rows": [], "note": str(e)}
            statuses[p] = st
            if "statuses" not in cache:
                cache["statuses"] = {}
            cache["statuses"][p] = {"timestamp": int(now), "status": st}
            if progress:
                progress.update(1, text=t("progress_checking", provider=PROVIDER_LABEL[p]))

    if progress:
        progress.finish(clear=True)

    save_cache(cache)
    return statuses


def cmd_status(args, force_refresh=False):
    who_flag = "--who" in args

    for line in machine_status():
        print(line)
    if who_flag:
        for line in who_status():
            print(line)
    else:
        print(t("who_hint", cmd="selectorai.py status --who"))
    print()

    installed = [p for p in PROVIDERS if provider_installed(p)]
    statuses = fetch_all_statuses(installed, force_refresh=force_refresh, show_progress=True)

    for p in PROVIDERS:
        if not provider_installed(p):
            print(t("status_not_installed", label=PROVIDER_LABEL[p]) + "\n")
            continue
        print_status_block(p, statuses[p])


def build_provider_list(force_refresh=False):
    """Sorted by last-used, most recent first (then the next-most-recent,
    and so on) — not the old quota-based "advisor" ranking (that stays
    off), just recency, which is simpler to predict: whatever you touched
    last is always at the top. Ties (e.g. two never-used providers) keep
    PROVIDERS' own order. Returns (providers, statuses) — statuses is
    {p: status dict}, used both for the plain picker's summary line and
    the Textual picker's detail panel."""
    installed = [p for p in PROVIDERS if provider_installed(p)]
    statuses = fetch_all_statuses(installed, force_refresh=force_refresh, show_progress=True)
    installed.sort(key=lambda p: provider_last_used_epoch(p), reverse=True)
    return installed, statuses


def _plain_picker(providers, statuses):
    """Numbered fallback: no tty, or the Textual UI couldn't be set up."""
    for line in machine_status():
        print(line)
    print(t("who_hint", cmd="selectorai.py status --who"))
    print()
    print(t("menu_available"))
    print()
    menu_provider = {}
    for i, p in enumerate(providers, start=1):
        status = statuses.get(p, {"pct_used": None, "rows": [], "note": None})
        summary = provider_summary(status)
        last = provider_last_used_epoch(p)
        print(f"  {i}) {PROVIDER_LABEL[p]:<22} {summary:<55} {t('last_used', ago=fmt_ago(last))}")
        menu_provider[i] = p
    print()
    choice = (_prompt(t("menu_pick_prompt", n=len(providers))) or "").strip() or "1"
    try:
        return menu_provider[int(choice)]
    except (ValueError, KeyError):
        return None


def _textual_available():
    try:
        import textual  # noqa: F401

        return True
    except ImportError:
        return False


def _bootstrap_textual_venv():
    """Create ~/.selectorai/venv with `textual` installed, if not already
    there. Fully isolated (no system-wide changes, no sudo) — this machine
    has no bare `pip` (Debian's externally-managed-environment policy), so a
    dedicated venv is the correct way to add this, same idea as `pipx`.
    Returns the venv's python executable path, or None on any failure."""
    venv_dir = STATE_DIR / "venv"
    venv_python = venv_dir / "bin" / "python3"
    if venv_python.exists():
        r = subprocess.run([str(venv_python), "-c", "import textual"], stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            return venv_python
    print(t("menu_installing_ui"))
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)], check=True, stderr=subprocess.DEVNULL
        )
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--quiet", "textual"], check=True
        )
        return venv_python
    except Exception:
        return None


def _sysinfo_markup(lines):
    """Wrap the "⚠ ..." tail of a warning line (disk/memory low-space,
    high-usage) in Rich markup so it stays yellow regardless of what color
    a theme gives #sysinfo as a whole — CSS can't target a substring
    inside one Static widget's text, only Rich markup embedded in the
    content can. Textual-only: the plain `status`/fallback-menu output
    uses machine_status() directly, unmodified, since raw "[yellow]" tags
    would just print as literal text there instead of being interpreted."""
    out = []
    for line in lines:
        idx = line.find("⚠")
        out.append(f"{line[:idx]}[yellow]{line[idx:]}[/yellow]" if idx != -1 else line)
    return out


# Sentinel results for _run_textual_picker/cmd_menu: distinguishable from
# a real provider id (a short lowercase key like "claude") or None
# (deliberate quit), so cmd_menu knows to reload and reopen the picker
# instead of treating the result as a launch choice.
_RESTART_LANG = "\x00restart-lang\x00"
_RESTART_THEME = "\x00restart-theme\x00"


def _run_textual_picker(providers, statuses, theme_path):
    """providers: order list of provider keys (see build_provider_list).
    statuses: {p: status dict} from fetch_all_statuses, used to render the
    detail panel. Returns a provider id, None (deliberate quit), or one of
    the _RESTART_* sentinels (language/theme changed from inside the
    picker — see cmd_menu, which reloads and calls this again)."""
    from textual.app import App, ComposeResult
    from textual.containers import Vertical
    from textual.widgets import Footer, OptionList, Static
    from textual.widgets.option_list import Option

    class _SelectorApp(App):
        # The "front" — an external stylesheet, not inline CSS, so a whole
        # different look (see themes/*.tcss) is a file swap, not a code
        # change. This class only owns behavior: widget structure, key
        # handling, what happens on selection.
        CSS_PATH = str(theme_path)
        BINDINGS = [
            ("up", "cursor_up", t("menu_move")),
            ("down", "cursor_down", t("menu_move")),
            ("enter", "select", t("menu_select")),
            ("l", "cycle_lang", t("menu_lang")),
            ("t", "cycle_theme", t("menu_theme")),
            ("q", "quit_app", t("menu_quit")),
            ("escape", "quit_app", t("menu_quit")),
        ]

        def __init__(self):
            super().__init__()
            self.chosen = None
            self._cursor_on = True

        def compose(self) -> ComposeResult:
            yield Static("\n".join(render_big("SELECTOR AI")), id="title")
            with Vertical(id="sysbox"):
                yield Static(f"{t('menu_system_ready')} █", id="sysline")
                yield Static("\n".join(_sysinfo_markup(machine_status())), id="sysinfo")
            # Deliberately simple: just the name. Detailed stats (quota
            # breakdown, tree, countdown, last used) only show for whichever
            # one is currently highlighted, in the detail panel below —
            # not crammed into every row at once.
            options = [Option(PROVIDER_LABEL[p], id=p) for p in providers]
            yield OptionList(*options, id="picker")
            yield Static(id="detail")
            yield Footer()

        def on_mount(self):
            self.query_one("#picker", OptionList).focus()
            self._update_detail(providers[0])

            # Power-on flicker: title fades in rather than snapping to full
            # brightness, like an old CRT warming up.
            title = self.query_one("#title", Static)
            title.styles.opacity = 0.0
            title.styles.animate("opacity", value=1.0, duration=0.6, easing="out_cubic")

            # Blinking cursor block next to the system-ready line, classic
            # terminal cadence (~530ms, matches typical terminal defaults).
            self.set_interval(0.53, self._blink_cursor)

        def _blink_cursor(self):
            self._cursor_on = not self._cursor_on
            block = "█" if self._cursor_on else " "
            self.query_one("#sysline", Static).update(f"{t('menu_system_ready')} {block}")

        def _update_detail(self, p):
            # No big block-letter name repeat here anymore — the OptionList
            # row already shows which provider is highlighted, so this
            # panel goes straight to what it actually adds: the stats.
            status = statuses.get(p)
            lines = render_status_rows(p, status) if status is not None else []
            last = provider_last_used_epoch(p)
            lines = lines + ["", t("last_used", ago=fmt_ago(last))]
            self.query_one("#detail", Static).update("\n".join(lines))

        def on_option_list_option_highlighted(self, event):
            if event.option.id:
                self._update_detail(event.option.id)

        def on_option_list_option_selected(self, event):
            self.chosen = event.option.id
            self.exit(result=self.chosen)

        def action_cursor_up(self):
            self.query_one("#picker", OptionList).action_cursor_up()

        def action_cursor_down(self):
            self.query_one("#picker", OptionList).action_cursor_down()

        def action_select(self):
            self.query_one("#picker", OptionList).action_select()

        def action_quit_app(self):
            self.exit(result=None)

        def action_cycle_lang(self):
            global LANG
            idx = LANG_CODES.index(LANG) if LANG in LANG_CODES else -1
            new_lang = LANG_CODES[(idx + 1) % len(LANG_CODES)]
            LANG_FILE.write_text(new_lang)
            LANG = new_lang
            self.exit(result=_RESTART_LANG)

        def action_cycle_theme(self):
            themes = list_themes()
            cur = current_theme()
            idx = themes.index(cur) if cur in themes else -1
            new_theme = themes[(idx + 1) % len(themes)]
            THEME_FILE.write_text(new_theme)
            self.exit(result=_RESTART_THEME)

    return _SelectorApp().run()


def cmd_menu(argv, force_refresh=False):
    yolo, cont = False, False
    prompt_parts = []
    for a in argv:
        if a == "--yolo":
            yolo = True
        elif a in ("--continue", "-c"):
            cont = True
        else:
            prompt_parts.append(a)
    prompt = " ".join(prompt_parts)

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    theme_name = current_theme() if interactive else None
    use_textual = False
    if interactive and not theme_name:
        print(f"No themes found under {THEMES_DIR}/ — using the plain menu instead.")
    elif interactive:
        if _textual_available():
            use_textual = True
        else:
            venv_python = _bootstrap_textual_venv()
            if venv_python:
                os.execv(str(venv_python), [str(venv_python), os.path.abspath(__file__)] + sys.argv[1:])
            print(t("menu_ui_failed"))

    providers, statuses = build_provider_list(force_refresh=force_refresh)
    if not providers:
        print(t("menu_none_installed", cmd=sys.argv[0]))
        sys.exit(1)

    chosen = None
    if use_textual:
        # L/T inside the picker cycle language/theme, persist the choice,
        # and hand back a sentinel instead of a provider id — loop and
        # reopen the picker instead of treating that as a launch pick. A
        # theme change alone doesn't need fresh data, just a different
        # stylesheet; a language change does, since note/label text is
        # already rendered into `statuses` by the time it gets here.
        while True:
            theme_path = THEMES_DIR / f"{current_theme()}.tcss"
            result = _run_textual_picker(providers, statuses, theme_path)
            if result == _RESTART_THEME:
                continue
            if result == _RESTART_LANG:
                providers, statuses = build_provider_list(force_refresh=True)
                continue
            chosen = result
            break
        # `chosen is None` here means the user deliberately quit (q/Esc),
        # not a failure — exit quietly instead of falling through to the
        # plain-text picker as if nothing happened.
        if chosen is None:
            sys.exit(0)
    else:
        chosen = _plain_picker(providers, statuses)
        if chosen is None:
            print(t("menu_invalid"))
            sys.exit(1)

    mode = "yolo" if yolo else "auto"
    if cont:
        mode += "+continue"
    log_launch(chosen, mode)
    launch_provider(chosen, yolo, prompt, cont)


# Fixed per-provider "preset": the flags used on every launch so behavior
# stays predictable. --yolo/--continue only toggle within that preset, they
# don't change its shape.
def launch_provider(p, yolo, prompt, cont):
    if p == "claude":
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
        os.execvp(args[0], args)

    elif p == "codex":
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
        # isatty(stdout) at startup.
        os.execvp(args[0], args)

    elif p == "antigravity":
        args = ["agy", "--dangerously-skip-permissions"]
        if cont:
            args.append("--continue")
        print(t("launch_antigravity", flags=" ".join(args[1:])))
        if prompt:
            args += ["--prompt-interactive", prompt]
        os.execvp(args[0], args)

    elif p == "grok":
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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Early re-exec into the dedicated venv if available, avoiding dual startup overhead
    venv_python = STATE_DIR / "venv" / "bin" / "python3"
    if venv_python.exists() and sys.executable != str(venv_python):
        try:
            os.execv(str(venv_python), [str(venv_python), os.path.abspath(__file__)] + sys.argv[1:])
        except Exception:
            pass

    argv = sys.argv[1:]

    # --lang/--lang=xx, --check-antigravity, and --refresh/-r/--no-cache
    # are global overrides (no --check-grok: see provider_status_grok)
    lang_override = None
    global CHECK_ANTIGRAVITY, FORCE_REFRESH
    force_refresh = False
    filtered = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--lang" and i + 1 < len(argv):
            lang_override = argv[i + 1]
            i += 2
            continue
        if a.startswith("--lang="):
            lang_override = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--check-antigravity":
            CHECK_ANTIGRAVITY = True
            i += 1
            continue
        if a in ("--refresh", "-r", "--no-cache"):
            force_refresh = True
            FORCE_REFRESH = True
            i += 1
            continue
        filtered.append(a)
        i += 1
    argv = filtered

    # Flag above is a one-off, this-run-only override. Absent that, fall
    # back to the persisted preference (`check-antigravity on/off`).
    if not CHECK_ANTIGRAVITY and CHECK_ANTIGRAVITY_FILE.exists():
        CHECK_ANTIGRAVITY = True

    global LANG
    LANG = resolve_lang(lang_override)

    if argv and argv[0] == "lang":
        cmd_lang(argv[1:])
    elif argv and argv[0] in ("install", "update"):
        cmd_install()
    elif argv and argv[0] == "status":
        cmd_status(argv[1:], force_refresh=force_refresh)
    elif argv and argv[0] == "auth":
        cmd_auth(argv[1:])
    elif argv and argv[0] == "check-antigravity":
        cmd_check_antigravity(argv[1:])
    elif argv and argv[0] == "theme":
        cmd_theme(argv[1:])
    else:
        cmd_menu(argv, force_refresh=force_refresh)


if __name__ == "__main__":
    main()
