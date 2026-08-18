"""Provider health classification: ONLINE / WARNING / OFFLINE, derived from
a status dict's `kind` + `pct_used` (see sai/providers/base.py's contract
docstring for the status shape). Pure function, no I/O of its own — this
module never probes anything; sai/cache.py's fetch_all_statuses is still
the only place that decides whether to re-query a provider or trust the
cache. sai/ui/picker.py and sai/ui/plain.py both call classify() to decide
which section a provider belongs in.
"""

ONLINE = "online"
WARNING = "warning"
OFFLINE = "offline"


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
