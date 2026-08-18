"""fmt_ago, countdowns, reset-date parsing — every place selectorai turns a
timestamp into human text, in one place so the parsing heuristics (and
their verified-vs-assumed provenance) aren't duplicated per provider.
"""
import re
import subprocess
import time
import zoneinfo
from datetime import datetime

from sai.i18n import t


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
