#!/usr/bin/env python3
"""Plain-python3 test: sai.health's service-status parsers, fed captured/
fake JSON bodies including malformed ones, plus fetch_one/fetch_service_states
exercised through a monkeypatched urllib.request.urlopen (never a real
network call — same "_FakeRun refuses anything unrecognized" shape as
test_status_shapes.py's subprocess stub, just for urlopen instead), plus
classify()'s service_state fold-in end-to-end through render_health_line().
"""
import io
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sai import health  # noqa: E402


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


class _FakeUrlopen:
    """Drop-in for urllib.request.urlopen: returns canned bytes for a
    known URL (or raises a canned exception, simulating a timeout/HTTP
    error), and raises loudly on anything else — so a bug that would
    otherwise reach the real network fails the test instead of silently
    making a live call. Mirrors test_status_shapes.py's _FakeRun for
    subprocess.run, same idea applied to urlopen."""

    def __init__(self, canned):
        self.canned = canned  # {url: bytes|str|Exception}
        self.calls = []

    def __call__(self, req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else req
        self.calls.append(url)
        if url not in self.canned:
            raise AssertionError(f"unexpected urlopen call, would hit real network: {url!r}")
        body = self.canned[url]
        if isinstance(body, Exception):
            raise body
        data = body.encode("utf-8") if isinstance(body, str) else body
        return io.BytesIO(data)


# --- Statuspage/incident.io indicator parsing (claude, codex) ---------------


def test_statuspage_indicator_none_is_operational():
    check(
        'indicator "none" -> operational',
        health._parse_statuspage_indicator({"status": {"indicator": "none"}}) == health.SERVICE_OPERATIONAL,
    )


def test_statuspage_indicator_minor_is_degraded():
    check(
        'indicator "minor" -> degraded',
        health._parse_statuspage_indicator({"status": {"indicator": "minor"}}) == health.SERVICE_DEGRADED,
    )


def test_statuspage_indicator_major_and_critical_are_outage():
    check(
        'indicator "major" -> outage',
        health._parse_statuspage_indicator({"status": {"indicator": "major"}}) == health.SERVICE_OUTAGE,
    )
    check(
        'indicator "critical" -> outage',
        health._parse_statuspage_indicator({"status": {"indicator": "critical"}}) == health.SERVICE_OUTAGE,
    )


def test_statuspage_indicator_unrecognized_is_none():
    check(
        "unrecognized indicator value -> None (unknown, not a guess)",
        health._parse_statuspage_indicator({"status": {"indicator": "something_new"}}) is None,
    )


def test_statuspage_malformed_shapes_dont_raise():
    # _parse_statuspage_indicator itself has no try/except (see health.py's
    # comment on _fetch_one) — it's meant to be called only through
    # _fetch_one in real use, but must still degrade to None on a
    # dict.get() miss rather than raising, since dict.get is what it
    # actually uses (no KeyError risk) — confirming that contract directly.
    check("missing 'status' key -> None", health._parse_statuspage_indicator({}) is None)
    check("missing 'indicator' key -> None", health._parse_statuspage_indicator({"status": {}}) is None)


# --- Google Cloud incidents.json parsing (antigravity) ----------------------


def _incident(end=None, status_impact="SERVICE_DISRUPTION"):
    entry = {"status_impact": status_impact}
    if end is not None:
        entry["end"] = end
    else:
        entry["end"] = None
    return entry


def test_google_incidents_none_active_is_operational():
    # Real shape seen live 2026-08-17: 4 entries, all already resolved
    # (every one had a real `end` timestamp) -> operational.
    data = [_incident(end="2026-07-16T12:25:00+00:00"), _incident(end="2026-06-26T19:00:00+00:00")]
    check("all incidents resolved -> operational", health._parse_google_incidents(data) == health.SERVICE_OPERATIONAL)


def test_google_incidents_empty_list_is_operational():
    check("empty incidents array -> operational", health._parse_google_incidents([]) == health.SERVICE_OPERATIONAL)


def test_google_incidents_active_outage_wins():
    data = [
        _incident(end=None, status_impact="SERVICE_OUTAGE"),
        _incident(end="2026-06-26T19:00:00+00:00", status_impact="SERVICE_DISRUPTION"),
    ]
    check(
        "one active SERVICE_OUTAGE among others -> outage",
        health._parse_google_incidents(data) == health.SERVICE_OUTAGE,
    )


def test_google_incidents_active_non_outage_is_degraded():
    data = [_incident(end=None, status_impact="SERVICE_DISRUPTION")]
    check(
        "active but not SERVICE_OUTAGE -> degraded",
        health._parse_google_incidents(data) == health.SERVICE_DEGRADED,
    )


def test_google_incidents_missing_end_key_counts_as_active():
    # "end == null (or missing)" per health.py's docstring — an entry with
    # no `end` key at all (not just end: null) must still count as active.
    data = [{"status_impact": "SERVICE_INFORMATION"}]
    check(
        "active incident with no 'end' key at all -> degraded (still counted active)",
        health._parse_google_incidents(data) == health.SERVICE_DEGRADED,
    )


# --- fetch_service_states: grok always None, never touches the network -----


def test_fetch_service_states_grok_always_none_no_url_entry():
    check("grok has no entry in _SERVICE_URLS", "grok" not in health._SERVICE_URLS)
    check("grok not in SERVICE_PROBED_PROVIDERS", "grok" not in health.SERVICE_PROBED_PROVIDERS)


def test_fetch_service_states_happy_path_via_fake_urlopen():
    # Real confirmed shapes (see health.py's parser docstrings, live-curled
    # 2026-08-17): all three probed providers reporting "all clear" through
    # the *actual* fetch_service_states path (urlopen -> json.loads ->
    # parser), not just the pure parser functions tested above.
    canned = {
        "https://status.claude.com/api/v2/status.json": '{"status":{"indicator":"none"}}',
        "https://status.openai.com/api/v2/status.json": '{"status":{"indicator":"none"}}',
        "https://status.cloud.google.com/incidents.json": "[]",
    }
    fake = _FakeUrlopen(canned)
    orig_urlopen = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        result = health.fetch_service_states(["claude", "codex", "antigravity", "grok"])
    finally:
        urllib.request.urlopen = orig_urlopen
    check("claude -> operational via the real fetch path", result["claude"] == health.SERVICE_OPERATIONAL)
    check("codex -> operational via the real fetch path", result["codex"] == health.SERVICE_OPERATIONAL)
    check("antigravity -> operational via the real fetch path", result["antigravity"] == health.SERVICE_OPERATIONAL)
    check("grok -> None, no urlopen call made for it at all", result["grok"] is None)
    check("exactly the 3 probed URLs were called, nothing else", set(fake.calls) == set(canned))


def test_fetch_service_states_malformed_body_is_none_not_raise():
    canned = {
        "https://status.claude.com/api/v2/status.json": "not json at all {{{",
        "https://status.openai.com/api/v2/status.json": '{"unexpected": "shape"}',
        "https://status.cloud.google.com/incidents.json": '{"not": "a list"}',
    }
    fake = _FakeUrlopen(canned)
    orig_urlopen = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        result = health.fetch_service_states(["claude", "codex", "antigravity"])
    finally:
        urllib.request.urlopen = orig_urlopen
    check("invalid JSON body -> None, no raise", result["claude"] is None)
    check("valid JSON but wrong shape (statuspage) -> None", result["codex"] is None)
    check("valid JSON but wrong shape (google, dict not list) -> None", result["antigravity"] is None)


def test_fetch_service_states_timeout_or_http_error_is_none():
    canned = {
        "https://status.claude.com/api/v2/status.json": TimeoutError("simulated timeout"),
        "https://status.openai.com/api/v2/status.json": OSError("simulated connection error"),
    }
    fake = _FakeUrlopen(canned)
    orig_urlopen = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        result = health.fetch_service_states(["claude", "codex"])
    finally:
        urllib.request.urlopen = orig_urlopen
    check("simulated timeout -> None, no raise", result["claude"] is None)
    check("simulated connection error -> None, no raise", result["codex"] is None)


def test_fetch_service_states_runs_in_parallel_not_serial():
    # Each canned entry sleeps 0.3s before returning — if fetch_service_states
    # queried providers serially this would take ~0.9s (3x0.3s); run in
    # parallel threads (as documented) it should take roughly one sleep's
    # worth, not three.
    class _SlowUrlopen(_FakeUrlopen):
        def __call__(self, req, *args, **kwargs):
            time.sleep(0.3)
            return super().__call__(req, *args, **kwargs)

    canned = {
        "https://status.claude.com/api/v2/status.json": '{"status":{"indicator":"none"}}',
        "https://status.openai.com/api/v2/status.json": '{"status":{"indicator":"none"}}',
        "https://status.cloud.google.com/incidents.json": "[]",
    }
    fake = _SlowUrlopen(canned)
    orig_urlopen = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        start = time.time()
        health.fetch_service_states(["claude", "codex", "antigravity"])
        elapsed = time.time() - start
    finally:
        urllib.request.urlopen = orig_urlopen
    check(f"3 providers x 0.3s each finished in parallel ({elapsed:.2f}s, well under 0.9s serial)", elapsed < 0.7)


def test_fetch_service_states_returns_entry_for_every_requested_name():
    # Even a name with no probe at all (unknown, or "grok") must still get
    # a key in the result dict, per fetch_service_states' documented
    # contract — callers shouldn't need a .get() with a default.
    result = health.fetch_service_states(["grok", "not-a-real-provider"])
    check("'grok' key present", "grok" in result and result["grok"] is None)
    check(
        "unrecognized name still gets a key (None)",
        "not-a-real-provider" in result and result["not-a-real-provider"] is None,
    )


# --- classify() + render_health_line() end-to-end with service_state -------


def _st(kind="ok", pct=None):
    return {"pct_used": pct, "rows": [], "note": None, "kind": kind}


def test_classify_service_outage_end_to_end():
    from sai.i18n import t

    state, reason_key = health.classify("claude", _st(pct=10), service_state=health.SERVICE_OUTAGE)
    check("outage -> OFFLINE", state == health.OFFLINE)
    check("outage -> health_reason_service", reason_key == "health_reason_service")
    line = health.render_health_line(state, reason_key)
    check("render_health_line includes the OFFLINE state word", t("health_state_offline") in line)
    check("render_health_line includes the service-outage reason text", t("health_reason_service") in line)


def test_classify_service_degraded_end_to_end():
    state, reason_key = health.classify("codex", _st(pct=10), service_state=health.SERVICE_DEGRADED)
    check("degraded -> WARNING", state == health.WARNING)
    check("degraded -> health_reason_degraded", reason_key == "health_reason_degraded")


def test_render_health_line_no_reason():
    line = health.render_health_line(health.ONLINE, None)
    check("no reason -> line has no ' — ' glue", " — " not in line)
    check("no reason -> line is just the state word, non-empty", bool(line))


def test_render_health_line_with_reason():
    line = health.render_health_line(health.WARNING, "health_reason_low_quota")
    check("with a reason -> line joins state + reason with ' — '", " — " in line)


def main():
    print("test_health_service:")

    test_statuspage_indicator_none_is_operational()
    test_statuspage_indicator_minor_is_degraded()
    test_statuspage_indicator_major_and_critical_are_outage()
    test_statuspage_indicator_unrecognized_is_none()
    test_statuspage_malformed_shapes_dont_raise()

    test_google_incidents_none_active_is_operational()
    test_google_incidents_empty_list_is_operational()
    test_google_incidents_active_outage_wins()
    test_google_incidents_active_non_outage_is_degraded()
    test_google_incidents_missing_end_key_counts_as_active()

    test_fetch_service_states_grok_always_none_no_url_entry()
    test_fetch_service_states_happy_path_via_fake_urlopen()
    test_fetch_service_states_malformed_body_is_none_not_raise()
    test_fetch_service_states_timeout_or_http_error_is_none()
    test_fetch_service_states_runs_in_parallel_not_serial()
    test_fetch_service_states_returns_entry_for_every_requested_name()

    test_classify_service_outage_end_to_end()
    test_classify_service_degraded_end_to_end()
    test_render_health_line_no_reason()
    test_render_health_line_with_reason()

    print("test_health_service: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
