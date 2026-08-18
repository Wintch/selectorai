"""Machine status — pure /proc + stdlib os calls, no subprocess, no tty
ioctl, nothing that can prompt for elevated permission. Shown by default.

Who's connected — opt-in only (`status --who`), never runs by default.
Self-detection uses env vars (SSH_CONNECTION/SSH_TTY/SSH_CLIENT), not
os.ttyname()/ioctl — that call errors out under a non-tty stdin anyway and
is the kind of thing that can trip a permission prompt; env vars need none.

The same opt-in view also surfaces recent-login history, a NAT warning,
and the box's public IP (see recent_logins()/`_nat_warning_line()`/
`_fetch_public_ip()` below). Purpose, in the user's own words: this view
exists so the person SSHing in can recognize their own access origins
(home IP vs mobile) at a glance, and so AI agents launched from here have
more context about where they're running.
"""
import ipaddress
import os
import re
import shutil
import struct
import subprocess
import urllib.error
import urllib.request
from datetime import datetime

from sai.i18n import t
from sai.timeutil import fmt_ago


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


def _current_user():
    return os.environ.get("USER") or os.environ.get("LOGNAME") or ""


def _who_sessions_lines():
    """The original `who`-command-based session listing, unchanged —
    pulled out of who_status() into its own function so the newer
    wtmp/NAT/public-IP sections below can still run (and be tested) even
    when `who` itself is missing or reports nothing, instead of an early
    `return` from who_status() short-circuiting them."""
    lines = []
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

    me = _current_user()
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


# --- recent logins, parsed straight out of /var/log/wtmp -------------------
#
# `last` is not installed on this machine (verified 2026-08-17), but wtmp
# itself is world-readable here (verified same session: `ls -la
# /var/log/wtmp` -> "-rw-rw-r--"), so plain stdlib `struct` unpacking works
# without shelling out to a helper binary at all.
#
# Record layout — VERIFIED live on this machine 2026-08-17: the format
# string below gives struct.calcsize() == 384, and unpacking the real
# /var/log/wtmp on this box with it produced 113 USER_PROCESS records (out
# of 249 total) with sane usernames/ttys/hosts/timestamps for every single
# one (spot-checked several by hand against `whoami`/`who`/known login
# times) — not just "didn't raise". Field order, from Linux's <utmp.h>:
# ut_type(h), [2 pad bytes], ut_pid(i), ut_line(32s), ut_id(4s),
# ut_user(32s), ut_host(256s), ut_exit.e_termination(h),
# ut_exit.e_exit(h), ut_session(i), ut_tv.tv_sec(i), ut_tv.tv_usec(i),
# ut_addr_v6(4i), [20 pad bytes].
WTMP_PATH = "/var/log/wtmp"
_WTMP_STRUCT = "<hxxi32s4s32s256shhiii4i20x"
_WTMP_RECORD_SIZE = struct.calcsize(_WTMP_STRUCT)  # 384, per the live check above
_UT_USER_PROCESS = 7  # verified: this is the type value every real login
# record in the file above carried; other type values (e.g. runlevel/boot
# markers) showed up too and are exactly what gets filtered out here.


def _parse_wtmp_records(data):
    """Yields (user, host, tv_sec) for every USER_PROCESS record in raw
    wtmp bytes. A trailing partial record (file size not a clean multiple
    of _WTMP_RECORD_SIZE — wtmp can be mid-write) is silently dropped, not
    an error."""
    n = len(data) // _WTMP_RECORD_SIZE
    for i in range(n):
        rec = data[i * _WTMP_RECORD_SIZE : (i + 1) * _WTMP_RECORD_SIZE]
        try:
            fields = struct.unpack(_WTMP_STRUCT, rec)
        except struct.error:
            continue  # malformed record — skip rather than blow up the whole view
        ut_type, _ut_pid, _ut_line, _ut_id, ut_user, ut_host = fields[:6]
        tv_sec = fields[9]
        if ut_type != _UT_USER_PROCESS:
            continue
        user = ut_user.split(b"\x00", 1)[0].decode("utf-8", "replace")
        host = ut_host.split(b"\x00", 1)[0].decode("utf-8", "replace")
        yield user, host, tv_sec


def recent_logins(max_n=5):
    """Last `max_n` logins for the *current* user, newest first, as
    (host, tv_sec) pairs. Returns None when WTMP_PATH is missing/unreadable
    (caller shows a "no history" line, never an exception) or an empty
    list when the file parses fine but has no records for this user."""
    try:
        with open(WTMP_PATH, "rb") as f:
            data = f.read()
    except OSError:
        return None
    me = _current_user()
    records = [(host, tv_sec) for user, host, tv_sec in _parse_wtmp_records(data) if user == me]
    records.sort(key=lambda r: r[1], reverse=True)
    return records[:max_n]


def _recent_logins_lines():
    lines = [t("who_recent_logins_header")]
    logins = recent_logins()
    if not logins:
        lines.append(t("who_recent_no_history"))
        return lines
    for host, tv_sec in logins:
        # Empty host = local console; a ':N'-style host is an X display
        # number, not a network origin either — both read as "(local)".
        host_disp = host if host and not host.startswith(":") else t("who_recent_host_local")
        when_abs = datetime.fromtimestamp(tv_sec).strftime("%Y-%m-%d %H:%M")
        lines.append(t("who_recent_login_line", host=host_disp, when=when_abs, ago=fmt_ago(tv_sec)))
    return lines


# --- NAT detection: purely local, no external call --------------------------
_RFC1918_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


def _parse_ip_route_src(output):
    """Pull the 'src <ip>' token out of `ip route get` output — kept
    separate from the subprocess call itself so it's testable on canned
    text without exec'ing `ip` at all."""
    m = re.search(r"\bsrc\s+(\S+)", output)
    return m.group(1) if m else None


def _is_rfc1918(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in _RFC1918_NETS)


def _local_src_ip():
    """`ip route get 1.1.1.1` is a routing-table lookup, not a real probe —
    it never sends a packet, it just asks the kernel which local address
    and interface *would* be used to reach that destination. 'ip' missing,
    non-zero exit, or unparseable output -> None, silently; this is a
    nicety, not something worth surfacing an error for."""
    try:
        r = subprocess.run(["ip", "route", "get", "1.1.1.1"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return _parse_ip_route_src(r.stdout)


def _nat_warning_line():
    ip_str = _local_src_ip()
    if ip_str and _is_rfc1918(ip_str):
        return t("who_nat_warning", ip=ip_str)
    return None


# --- public IP: the one external call in this whole module -------------------
def _fetch_public_ip():
    """GET https://api.ipify.org (plain text, no JSON) — the only network
    call in this opt-in (--who only) view. Never raises: no network, DNS
    failure, timeout, non-200, or a response that doesn't even parse as an
    IP address (e.g. a captive-portal HTML page) all collapse to None,
    same as every other "skip silently offline" path in this module."""
    try:
        req = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "selectorai"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            text = resp.read().decode("utf-8", "replace").strip()
        ipaddress.ip_address(text)  # validate shape before trusting/printing it
        return text
    except Exception:
        return None


def who_status():
    lines = []
    remote = _is_remote_session()
    own_ip = _own_client_ip()
    if remote:
        origin = t("who_origin_remote_ip", ip=own_ip) if own_ip else t("who_origin_remote")
    else:
        origin = t("who_origin_local")
    lines.append(t("who_self", origin=origin))

    lines.extend(_who_sessions_lines())
    lines.extend(_recent_logins_lines())

    nat_line = _nat_warning_line()
    if nat_line:
        lines.append(nat_line)

    public_ip = _fetch_public_ip()
    if public_ip:
        lines.append(t("who_public_ip", ip=public_ip))

    return lines
