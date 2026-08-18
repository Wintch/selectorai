"""Provider health classification: ONLINE / WARNING / OFFLINE, derived from
a status dict's `kind` + `pct_used` (see sai/providers/base.py's contract
docstring for the status shape), plus external service-status probes
(fetch_service_states below) that classify() can factor in via its
service_state param. sai/ui/picker.py and sai/ui/plain.py both call
classify() to decide which section a provider belongs in; sai/cache.py's
fetch_all_statuses/fetch_service_states_cached are the only places that
decide whether to re-query a provider or trust the cache.
"""
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from sai.i18n import t

ONLINE = "online"
WARNING = "warning"
OFFLINE = "offline"

SERVICE_OPERATIONAL = "operational"
SERVICE_DEGRADED = "degraded"
SERVICE_OUTAGE = "outage"

_SERVICE_TIMEOUT = 3  # seconds — fetch_service_states runs all probes in
# parallel threads specifically so this is the wall-clock budget for the
# *whole* call, not per-provider serial time.
_SERVICE_USER_AGENT = "selectorai"


def _parse_statuspage_indicator(data):
    """Statuspage's (and Statuspage-compatible incident.io's) own
    `status.indicator` enum: "none"/"minor"/"major"/"critical". Verified
    live 2026-08-17 via curl against both URLs in _SERVICE_URLS below —
    both returned {"status": {"indicator": "none", ...}, ...} (all-clear
    shape) at check time; the mapping for the other three values is
    Statuspage's own documented enum, not independently observed live."""
    indicator = data.get("status", {}).get("indicator")
    if indicator == "none":
        return SERVICE_OPERATIONAL
    if indicator == "minor":
        return SERVICE_DEGRADED
    if indicator in ("major", "critical"):
        return SERVICE_OUTAGE
    return None  # unrecognized shape/value — unknown, not a guess either way


def _parse_google_incidents(data):
    """Google Cloud's incidents.json is a flat JSON array (verified live
    2026-08-17: curl returned ~112KB, 4 entries, all already resolved —
    i.e. every entry had a real `end` timestamp, none active). An ACTIVE
    incident is one with `end` null or absent; among those, a
    status_impact of "SERVICE_OUTAGE" wins as OUTAGE, anything else active
    (e.g. "SERVICE_DISRUPTION", "SERVICE_INFORMATION" — both seen live,
    always on already-resolved entries) counts as DEGRADED. No active
    incidents at all -> operational."""
    active = [i for i in data if i.get("end") is None]
    if not active:
        return SERVICE_OPERATIONAL
    if any(i.get("status_impact") == "SERVICE_OUTAGE" for i in active):
        return SERVICE_OUTAGE
    return SERVICE_DEGRADED


# provider -> (url, parser). Deliberately no "grok" entry: status.x.ai
# serves its real status page fine to a browser (200) but 403s a
# non-browser client on anything that looks like its status API (verified
# 2026-08-17: `curl -A Mozilla/5.0 https://status.x.ai/api/v2/status.json`
# -> 403, Cloudflare bot protection; a plain/no-UA request even 404s,
# meaning that path isn't real to begin with) and otherwise only exposes
# an RSS feed of free-text statuses, nothing structured enough to map to
# operational/degraded/outage without guessing. fetch_service_states below
# returns None for any provider missing here, so grok always gets None —
# honestly "unsupported", not a disguised guess.
_SERVICE_URLS = {
    "claude": ("https://status.claude.com/api/v2/status.json", _parse_statuspage_indicator),
    "codex": ("https://status.openai.com/api/v2/status.json", _parse_statuspage_indicator),
    "antigravity": ("https://status.cloud.google.com/incidents.json", _parse_google_incidents),
}

# Read by sai/cache.py's fetch_service_states_cached to decide which
# providers are even worth a cache slot — grok (and any future provider
# with no entry above) never gets probed, so caching a permanent None for
# it would just be a no-op cache write repeated forever.
SERVICE_PROBED_PROVIDERS = frozenset(_SERVICE_URLS)


def _fetch_one(url, parser):
    """Never raises: any network error, non-200, timeout, or JSON/shape
    parse failure -> None, same "unknown, not unhealthy" contract as
    everything else in this module. This is also why the two _parse_*
    functions above are written without their own try/except — this is
    the one place that needs to catch everything, so they don't have to."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _SERVICE_USER_AGENT})
        with urllib.request.urlopen(req, timeout=_SERVICE_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return parser(data)
    except Exception:
        return None


def fetch_service_states(provider_names):
    """provider_names: any iterable of provider keys (extras or unknown
    ones are fine, see below). Returns {name: "operational"|"degraded"|
    "outage"|None} for every name in provider_names — never raises, never
    blocks longer than ~_SERVICE_TIMEOUT wall-clock total (each probe runs
    in its own thread, so N providers cost the same ~3s as one, not N×3s).
    A provider with no entry in _SERVICE_URLS (currently just "grok") is
    never queried at all and comes back None."""
    names = list(provider_names)
    to_query = [p for p in names if p in _SERVICE_URLS]
    results = {}
    if to_query:
        with ThreadPoolExecutor(max_workers=len(to_query)) as ex:
            fut_to_p = {ex.submit(_fetch_one, *_SERVICE_URLS[p]): p for p in to_query}
            for fut in as_completed(fut_to_p):
                p = fut_to_p[fut]
                try:
                    results[p] = fut.result()
                except Exception:
                    # Defensive only: _fetch_one already catches everything
                    # itself, so fut.result() re-raising would mean a bug
                    # in the executor plumbing, not the probe — still
                    # honors the "never raises" contract either way.
                    results[p] = None
    for p in names:
        results.setdefault(p, None)
    return results


def render_health_line(state, reason_key):
    """The one health line rendered wherever a provider's health is shown
    (Textual detail panel, plain `status` command) — state word alone, or
    state word + reason when classify() gave one. Kept here, next to
    classify() and the reason_key contract, so the two call sites (sai/
    ui/picker.py, sai/cli.py) can't drift out of sync with each other."""
    state_word = t(f"health_state_{state}")
    return state_word if reason_key is None else f"{state_word} — {t(reason_key)}"


def classify(provider_name, status, service_state=None):
    """provider_name: kept as an explicit parameter — unused today, but a
    later stage may need per-provider thresholds or a service-status
    lookup keyed by name, and that's a signature change nobody should have
    to make later. status: one status dict as returned by a provider's
    status() (see sai/providers/base.py). service_state: None (default) |
    "operational" | "degraded" | "outage" — a future external
    service-status probe's verdict, independent of what the CLI's own
    status() call reported. Nothing in this codebase passes anything but
    None yet; the param exists now so that later stage is a one-line wire-up
    instead of a signature change.

    Returns (state, reason_key | None). reason_key is an i18n key
    (health_reason_*) for sai.i18n.t(), never rendered text — callers
    render it themselves so this module stays language-agnostic.
    """
    # "outage" wins outright: a confirmed service-wide outage is a more
    # decisive signal than anything the CLI's own (possibly stale, possibly
    # locally-cached) status() call could say about one account.
    if service_state == "outage":
        return OFFLINE, "health_reason_service"

    kind = status.get("kind")
    pct = status.get("pct_used")

    if kind == "auth-needed":
        state, reason = OFFLINE, "health_reason_auth"
    elif pct is not None and pct >= 100:
        state, reason = OFFLINE, "health_reason_quota"
    elif pct is not None and pct >= 80:
        state, reason = WARNING, "health_reason_low_quota"
    else:
        # kind in ("not-checked", "no-usage-api"), or "ok" with pct still
        # unparseable — unknown is not the same as unhealthy, so both land
        # here as ONLINE with no reason to show.
        state, reason = ONLINE, None

    if service_state == "degraded" and state == ONLINE:
        # "At-least-WARNING": bump a clean ONLINE verdict up, but never
        # downgrade an existing WARNING/OFFLINE verdict, and never clobber
        # its (more specific) reason — a degraded service on top of an
        # already-known problem doesn't need a second reason string.
        state, reason = WARNING, "health_reason_degraded"

    return state, reason
