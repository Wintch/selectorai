"""Terminal progress bar & status cache (per-provider TTLs), plus
fetch_all_statuses — the one place that decides whether a cached status is
still good enough or needs a live re-probe.
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sai import health, providers
from sai.i18n import t
from sai.paths import CACHE_FILE
from sai.providers import antigravity

DEFAULT_CACHE_TTL = 60  # seconds


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


def fetch_all_statuses(provider_list, force_refresh=False, show_progress=True):
    now = time.time()
    cache = load_cache() if not force_refresh else {}
    cached_map = cache.get("statuses", {})

    statuses = {}
    to_query = []

    for p in provider_list:
        if not force_refresh and p in cached_map:
            entry = cached_map[p]
            ts = entry.get("timestamp", 0)
            st = entry.get("status")
            if now - ts < _cache_ttl(p) and st is not None:
                if p == "antigravity":
                    # Compare the structured `kind` field, not the
                    # rendered `note` string (which is localized and
                    # would never match once LANG != the language the
                    # cache entry was written under). Entries from before
                    # `kind` existed have no such key, so .get() returns
                    # None here — never equal to "not-checked", so those
                    # entries count as "not skipped" and fall through to
                    # whatever the toggle comparison below decides, which
                    # self-heals old caches into the new shape on next
                    # write instead of needing a migration.
                    was_skipped = st.get("kind") == "not-checked"
                    check_enabled = antigravity.get_check_enabled()
                    if (check_enabled and was_skipped) or (not check_enabled and not was_skipped):
                        to_query.append(p)
                        continue
                # No grok equivalent: its status never depends on a toggle
                # anymore (see sai.providers.grok.status), so plain TTL
                # caching is enough — nothing to detect a mismatch against.
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
        fut_to_p = {ex.submit(providers.status, p): p for p in to_query}
        for fut in as_completed(fut_to_p):
            p = fut_to_p[fut]
            try:
                st = fut.result()
            except Exception as e:
                st = {"pct_used": None, "rows": [], "note": str(e), "kind": "no-usage-api"}
            statuses[p] = st
            if "statuses" not in cache:
                cache["statuses"] = {}
            cache["statuses"][p] = {"timestamp": int(now), "status": st}
            if progress:
                progress.update(1, text=t("progress_checking", provider=providers.label(p)))

    if progress:
        progress.finish(clear=True)

    save_cache(cache)
    return statuses


# Service-status probes (sai.health.fetch_service_states) are a different
# cadence than quota statuses: a status.io/incident.io outage doesn't flap
# minute to minute, and hitting three external status pages on every menu
# open for no reason is just needless network traffic and startup latency.
# 300s isn't in _CACHE_TTL_OVERRIDES above because that dict is keyed by
# provider name under the "statuses" cache key — this is a wholly separate
# "service" key with its own single TTL for every probed provider, not a
# per-provider override of the quota-status cache.
SERVICE_CACHE_TTL = 300


def fetch_service_states_cached(provider_list, force_refresh=False):
    """Same cache-then-probe shape as fetch_all_statuses above, applied to
    sai.health.fetch_service_states instead of providers.status. Returns
    {p: state} for every p in provider_list — providers with no real probe
    (see health.SERVICE_PROBED_PROVIDERS; currently just "grok") short-
    circuit straight to None without a cache read/write, since there's
    nothing to cache."""
    now = time.time()
    cache = load_cache() if not force_refresh else {}
    cached_map = cache.get("service", {})

    states = {}
    to_query = []
    for p in provider_list:
        if p not in health.SERVICE_PROBED_PROVIDERS:
            states[p] = None
            continue
        if not force_refresh and p in cached_map:
            entry = cached_map[p]
            ts = entry.get("timestamp", 0)
            if now - ts < SERVICE_CACHE_TTL:
                states[p] = entry.get("state")
                continue
        to_query.append(p)

    if not to_query:
        return states

    fresh = health.fetch_service_states(to_query)
    cache.setdefault("service", {})
    for p, state in fresh.items():
        states[p] = state
        cache["service"][p] = {"timestamp": int(now), "state": state}
    save_cache(cache)
    return states
