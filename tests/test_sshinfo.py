#!/usr/bin/env python3
"""Plain-python3 test for the --who additions in sai/sysinfo.py: wtmp
parsing (synthetic file, never the real /var/log/wtmp), NAT classification
(canned `ip route get` text, never a real subprocess call), and the
public-IP line (fetcher monkeypatched — no network in this test at all).

Never touches ~/.selectorai, never reads the real wtmp, never runs `ip`/
`who`/curls anything.
"""
import os
import struct
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sai.sysinfo as sysinfo  # noqa: E402
from sai.i18n import t  # noqa: E402


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


def _pack_wtmp_record(ut_type, user="", host="", tv_sec=0):
    """Build one 384-byte synthetic wtmp record using the exact same
    struct format sai.sysinfo uses to unpack real ones — see the format
    string's own live-verification comment in sai/sysinfo.py."""
    return struct.pack(
        sysinfo._WTMP_STRUCT,
        ut_type,          # h  ut_type
        0,                # i  ut_pid
        b"pts/0",         # 32s ut_line
        b"",              # 4s ut_id
        user.encode(),    # 32s ut_user
        host.encode(),    # 256s ut_host
        0, 0,             # hh ut_exit.{e_termination,e_exit}
        0,                # i  ut_session
        tv_sec,           # i  tv_sec
        0,                # i  tv_usec
        0, 0, 0, 0,       # 4i ut_addr_v6
    )


def test_wtmp_record_size_matches_live_verification():
    # The comment above _WTMP_STRUCT in sai/sysinfo.py claims this — pin it
    # so a future edit to the format string fails loudly here too.
    check("record size is 384 bytes (live-verified format)", sysinfo._WTMP_RECORD_SIZE == 384)
    check("_pack_wtmp_record produces exactly one record", len(_pack_wtmp_record(7)) == 384)


def test_recent_logins_filters_sorts_and_limits():
    records = [
        _pack_wtmp_record(sysinfo._UT_USER_PROCESS, user="alice", host="", tv_sec=1000),
        _pack_wtmp_record(sysinfo._UT_USER_PROCESS, user="alice", host=":0", tv_sec=2000),
        _pack_wtmp_record(sysinfo._UT_USER_PROCESS, user="alice", host="203.0.113.5", tv_sec=3000),
        # other user — must never show up in alice's recent_logins
        _pack_wtmp_record(sysinfo._UT_USER_PROCESS, user="bob", host="", tv_sec=9000),
        # non-USER_PROCESS record for alice with the largest tv_sec of all —
        # must be filtered out by type, not just outrun by sorting
        _pack_wtmp_record(8, user="alice", host="", tv_sec=99999),
        _pack_wtmp_record(sysinfo._UT_USER_PROCESS, user="alice", host="198.51.100.9", tv_sec=1500),
    ]
    data = b"".join(records)

    with tempfile.TemporaryDirectory() as tmp:
        wtmp_path = Path(tmp) / "wtmp"
        wtmp_path.write_bytes(data)

        orig_wtmp, orig_user = sysinfo.WTMP_PATH, os.environ.get("USER")
        sysinfo.WTMP_PATH = str(wtmp_path)
        os.environ["USER"] = "alice"
        try:
            all_logins = sysinfo.recent_logins(max_n=10)
            limited = sysinfo.recent_logins(max_n=2)
        finally:
            sysinfo.WTMP_PATH = orig_wtmp
            if orig_user is None:
                os.environ.pop("USER", None)
            else:
                os.environ["USER"] = orig_user

    check("only alice's 4 USER_PROCESS records come back", len(all_logins) == 4)
    check("bob's record (tv_sec=9000) is excluded", ("", 9000) not in all_logins)
    check(
        "sorted newest-first",
        [ts for _, ts in all_logins] == sorted([ts for _, ts in all_logins], reverse=True),
    )
    check("newest is tv_sec=3000 / host 203.0.113.5", all_logins[0] == ("203.0.113.5", 3000))
    check("oldest of the four is tv_sec=1000", all_logins[-1] == ("", 1000))
    check("max_n=2 truncates to 2, still newest-first", limited == all_logins[:2])


def test_recent_logins_missing_file_returns_none():
    orig_wtmp = sysinfo.WTMP_PATH
    sysinfo.WTMP_PATH = str(Path(tempfile.gettempdir()) / "definitely-not-a-real-wtmp-file")
    try:
        result = sysinfo.recent_logins()
        check("missing wtmp -> None (never raises)", result is None)

        # Must still be pointed at the missing path here — restoring WTMP_PATH
        # first would make this fall through to the real /var/log/wtmp and
        # mask the very case this test exists to cover.
        lines = sysinfo._recent_logins_lines()
        check("no-history line uses the i18n string", t("who_recent_no_history") in lines)
    finally:
        sysinfo.WTMP_PATH = orig_wtmp


def test_parse_ip_route_src():
    real_looking = "1.1.1.1 via 192.168.1.1 dev enp5s0 src 192.168.1.144 uid 1000 \n    cache"
    check("extracts src from real-shaped output", sysinfo._parse_ip_route_src(real_looking) == "192.168.1.144")
    check("no src token -> None", sysinfo._parse_ip_route_src("RTNETLINK answers: Network is unreachable") is None)
    check("empty output -> None", sysinfo._parse_ip_route_src("") is None)


def test_rfc1918_classification():
    check("public IP is not RFC1918", sysinfo._is_rfc1918("8.8.8.8") is False)
    check("public IP is not RFC1918 (2)", sysinfo._is_rfc1918("1.1.1.1") is False)
    check("10.0.0.0/8 start", sysinfo._is_rfc1918("10.0.0.1") is True)
    check("10.0.0.0/8 end", sysinfo._is_rfc1918("10.255.255.254") is True)
    check("172.16.0.0/12 inside", sysinfo._is_rfc1918("172.16.0.1") is True)
    check("172.16.0.0/12 just below range", sysinfo._is_rfc1918("172.15.255.255") is False)
    check("172.16.0.0/12 just above range", sysinfo._is_rfc1918("172.32.0.1") is False)
    check("192.168.0.0/16 inside", sysinfo._is_rfc1918("192.168.1.144") is True)
    check("192.168.0.0/16 just above range", sysinfo._is_rfc1918("192.169.0.1") is False)
    check("garbage string -> False, not a crash", sysinfo._is_rfc1918("not-an-ip") is False)


def test_nat_warning_line_end_to_end_on_canned_local_src():
    orig = sysinfo._local_src_ip
    try:
        sysinfo._local_src_ip = lambda: "192.168.1.144"
        line = sysinfo._nat_warning_line()
        check("private src IP -> warning line present", line is not None)
        check("warning line names the local IP", "192.168.1.144" in line)
        check("warning line matches the i18n template", line == t("who_nat_warning", ip="192.168.1.144"))

        sysinfo._local_src_ip = lambda: "8.8.8.8"
        check("public src IP -> no warning", sysinfo._nat_warning_line() is None)

        sysinfo._local_src_ip = lambda: None
        check("unparseable/missing src IP -> no warning, no crash", sysinfo._nat_warning_line() is None)
    finally:
        sysinfo._local_src_ip = orig


def test_who_status_wires_public_ip_line_via_injected_fetcher():
    """Full who_status() assembly, but with every subprocess/network-touching
    helper monkeypatched to canned values — proves the wiring without a
    real `who`/`ip` call or a real HTTP request."""
    orig_sessions = sysinfo._who_sessions_lines
    orig_wtmp = sysinfo.WTMP_PATH
    orig_local_src = sysinfo._local_src_ip
    orig_fetch_ip = sysinfo._fetch_public_ip
    try:
        sysinfo._who_sessions_lines = lambda: ["(stub session line)"]
        sysinfo.WTMP_PATH = str(Path(tempfile.gettempdir()) / "definitely-not-a-real-wtmp-file")
        sysinfo._local_src_ip = lambda: None  # skip NAT line, tested separately above

        sysinfo._fetch_public_ip = lambda: "203.0.113.9"
        lines_with_ip = sysinfo.who_status()
        check("public IP line present when fetcher succeeds", t("who_public_ip", ip="203.0.113.9") in lines_with_ip)

        sysinfo._fetch_public_ip = lambda: None
        lines_without_ip = sysinfo.who_status()
        check(
            "no public-IP line when fetcher fails (skip silently)",
            not any(line.startswith("Public IP") for line in lines_without_ip),
        )
    finally:
        sysinfo._who_sessions_lines = orig_sessions
        sysinfo.WTMP_PATH = orig_wtmp
        sysinfo._local_src_ip = orig_local_src
        sysinfo._fetch_public_ip = orig_fetch_ip


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        print(f"-- {fn.__name__} --")
        fn()
    print(f"All {len(tests)} test(s) in test_sshinfo.py passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
