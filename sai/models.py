"""Per-provider model listings. sai/providers/<name>.py's list_models()
defines *how* to get a provider's models (see docs/ARCHITECTURE.md's
provider contract table); this module owns *when* and *where they're
stored*:

  - cmd_models() (the `models` subcommand) is the ONLY call site that ever
    invokes providers.list_models() for antigravity/grok — same rule as
    Antigravity's --check-antigravity gate (docs/ARCHITECTURE.md rule 1):
    their `models` subcommand's auth behavior on a bare invocation is
    unverified, so it only ever runs on explicit user request, never from
    status/menu code.
  - get_cached_models()/models_line() are the read-only side: the Textual
    detail panel and the plain `status` command call these to show a
    "Models: ..." line, and neither ever triggers a fetch — if nothing's
    cached yet (or the entry aged out), there's simply no line.

Cache shape: cache.json["models"][provider] = {"timestamp": epoch,
"models": list[str] | None, "static": bool}. "static" mirrors a
provider's MODELS_STATIC attribute (see sai/providers/claude.py) at the
time it was fetched, not looked up fresh on every read.
"""
import time

from sai import providers
from sai.cache import load_cache, save_cache
from sai.i18n import t

# Model lists change rarely, and this cache is only ever written by an
# explicit `models` run (never an implicit background refresh) — so unlike
# sai.cache's TTLs, which gate *whether to re-probe*, this TTL only gates
# *whether to still show it*: an entry older than this is treated as
# absent for display (get_cached_models/models_line below) rather than
# shown as if it were still fresh. cmd_models() itself ignores this
# entirely and always fetches on request, TTL or not.
MODELS_CACHE_TTL = 7 * 86400

# Providers whose `models` subcommand exists but has unverified auth
# behavior on a bare invocation — see sai/providers/antigravity.py and
# grok.py's list_models() docstrings. cmd_models() prints an i18n'd
# caution before touching either.
_RISKY_PROVIDERS = ("antigravity", "grok")


def get_cached_models(p):
    """Read-only, never fetches. Returns (models, is_static) if there's a
    usable cache entry for p, else None — "usable" meaning: an entry
    exists, it's not older than MODELS_CACHE_TTL, and its models list is
    non-empty/non-None."""
    entry = load_cache().get("models", {}).get(p)
    if not entry:
        return None
    if time.time() - entry.get("timestamp", 0) > MODELS_CACHE_TTL:
        return None
    models = entry.get("models")
    if not models:
        return None
    return models, bool(entry.get("static", False))


def models_line(p):
    """One formatted "Models: ..." line for display (Textual detail panel,
    plain `status`), or None when there's nothing usable cached — see
    get_cached_models above. Read-only: never calls providers.list_models."""
    cached = get_cached_models(p)
    if cached is None:
        return None
    models, is_static = cached
    joined = ", ".join(models)
    return t("detail_models_static", models=joined) if is_static else t("detail_models", models=joined)


def _print_result(p, models, is_static):
    label = providers.label(p)
    if not models:
        print(t("models_none", label=label))
        return
    joined = ", ".join(models)
    if is_static:
        print(t("models_result_static", label=label, models=joined))
    else:
        print(t("models_result", label=label, models=joined))


def cmd_models(argv):
    requested = [a for a in argv if not a.startswith("-")]
    unknown = [a for a in requested if a not in providers.ORDER]
    for name in unknown:
        print(t("models_unknown_provider", name=name))
    known = [p for p in requested if p in providers.ORDER]
    targets = known if requested else list(providers.ORDER)

    risky_targets = [p for p in targets if p in _RISKY_PROVIDERS and providers.installed(p)]
    if risky_targets:
        print(t("models_caution", providers=", ".join(providers.label(p) for p in risky_targets)))
        print()

    cache = load_cache()
    cache.setdefault("models", {})
    now = int(time.time())

    for p in targets:
        if not providers.installed(p):
            print(t("status_not_installed", label=providers.label(p)))
            continue
        models = providers.list_models(p)
        is_static = getattr(providers.registry[p], "MODELS_STATIC", False)
        cache["models"][p] = {"timestamp": now, "models": models, "static": is_static}
        _print_result(p, models, is_static)

    save_cache(cache)
