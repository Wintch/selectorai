"""Machine status — pure /proc + stdlib os calls, no subprocess, no tty
ioctl, nothing that can prompt for elevated permission. Shown by default.

Who's connected — opt-in only (`status --who`), never runs by default.
Self-detection uses env vars (SSH_CONNECTION/SSH_TTY/SSH_CLIENT), not
os.ttyname()/ioctl — that call errors out under a non-tty stdin anyway and
is the kind of thing that can trip a permission prompt; env vars need none.
"""
import os
import re
import shutil
import subprocess

from sai.i18n import t


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
