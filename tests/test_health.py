#!/usr/bin/env python3
"""Plain-python3 test: sai.health.classify()'s truth table, including the
service_state param cases (see sai/health.py's docstring). Pure function
over status dicts — no subprocess, no CLI, nothing to fake.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sai import health  # noqa: E402


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


def st(kind="ok", pct=None):
    return {"pct_used": pct, "rows": [], "note": None, "kind": kind}


def main():
    print("test_health:")

    # --- kind-driven ---
    check(
        "auth-needed -> OFFLINE/health_reason_auth",
        health.classify("claude", st(kind="auth-needed")) == (health.OFFLINE, "health_reason_auth"),
    )

    # --- pct-driven, including the 80/100 boundaries ---
    check(
        "pct 100 (exact boundary) -> OFFLINE/health_reason_quota",
        health.classify("claude", st(pct=100)) == (health.OFFLINE, "health_reason_quota"),
    )
    check(
        "pct 137 (over 100) -> OFFLINE/health_reason_quota",
        health.classify("claude", st(pct=137)) == (health.OFFLINE, "health_reason_quota"),
    )
    check(
        "pct 80 (exact boundary) -> WARNING/health_reason_low_quota",
        health.classify("claude", st(pct=80)) == (health.WARNING, "health_reason_low_quota"),
    )
    check(
        "pct 99 -> WARNING/health_reason_low_quota",
        health.classify("claude", st(pct=99)) == (health.WARNING, "health_reason_low_quota"),
    )
    check(
        "pct 79 (just under the WARNING boundary) -> ONLINE/None",
        health.classify("claude", st(pct=79)) == (health.ONLINE, None),
    )
    check(
        "pct 0 -> ONLINE/None",
        health.classify("claude", st(pct=0)) == (health.ONLINE, None),
    )

    # --- unknown != unhealthy ---
    check(
        "kind not-checked, pct None -> ONLINE/None",
        health.classify("antigravity", st(kind="not-checked")) == (health.ONLINE, None),
    )
    check(
        "kind no-usage-api, pct None -> ONLINE/None",
        health.classify("grok", st(kind="no-usage-api")) == (health.ONLINE, None),
    )
    check(
        "kind ok but pct unparseable (None) -> ONLINE/None",
        health.classify("codex", st(kind="ok", pct=None)) == (health.ONLINE, None),
    )

    # --- service_state param: nothing in the codebase passes this yet
    # (wired for a later stage — see sai/health.py's docstring), but the
    # handling has to already be correct. ---
    check(
        "service_state=outage overrides an otherwise-healthy status -> OFFLINE/health_reason_service",
        health.classify("claude", st(pct=10), service_state="outage")
        == (health.OFFLINE, "health_reason_service"),
    )
    check(
        "service_state=outage overrides even a quota-exhausted status",
        health.classify("claude", st(pct=100), service_state="outage")
        == (health.OFFLINE, "health_reason_service"),
    )
    check(
        "service_state=outage overrides an auth-needed status too",
        health.classify("claude", st(kind="auth-needed"), service_state="outage")
        == (health.OFFLINE, "health_reason_service"),
    )
    check(
        "service_state=degraded upgrades a clean ONLINE -> WARNING/health_reason_degraded",
        health.classify("claude", st(pct=10), service_state="degraded")
        == (health.WARNING, "health_reason_degraded"),
    )
    check(
        "service_state=degraded doesn't downgrade an existing OFFLINE (auth-needed) verdict",
        health.classify("claude", st(kind="auth-needed"), service_state="degraded")[0] == health.OFFLINE,
    )
    check(
        "service_state=degraded doesn't downgrade an existing OFFLINE (quota) verdict",
        health.classify("claude", st(pct=100), service_state="degraded")[0] == health.OFFLINE,
    )
    check(
        "service_state=degraded leaves an existing WARNING (low quota) verdict's own reason alone",
        health.classify("claude", st(pct=85), service_state="degraded")
        == (health.WARNING, "health_reason_low_quota"),
    )
    check(
        "service_state=None (default) behaves exactly like omitting the param",
        health.classify("claude", st(pct=10)) == health.classify("claude", st(pct=10), service_state=None),
    )
    check(
        "service_state=operational is a no-op",
        health.classify("claude", st(pct=10), service_state="operational") == (health.ONLINE, None),
    )

    print("test_health: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
