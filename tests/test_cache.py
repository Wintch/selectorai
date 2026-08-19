#!/usr/bin/env python3
"""Plain-python3 test: sai.cache.fetch_all_statuses's cache-freshness
decision — TTL, the gated-provider (Antigravity/Grok) toggle-mismatch
check, and the language-mismatch check (see docs/NOTES.md's "Fixed bug:
switching --lang mid-cache showed mixed-language reset text").

Points sai.cache.CACHE_FILE at a tempdir (never touches ~/.selectorai,
same convention as tests/test_models.py) and monkeypatches
sai.cache.providers.status to a counting fake — this test is entirely
about whether fetch_all_statuses decides to call that function again, not
about what any real provider's status() returns.
"""
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sai.cache as cache_mod  # noqa: E402
from sai import i18n  # noqa: E402
from sai.providers import antigravity  # noqa: E402


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


def _fake_status_counter():
    calls = {"n": 0}

    def fake(p):
        calls["n"] += 1
        return {"pct_used": 10, "rows": [("x", 10, "resets soon")], "note": None, "kind": "ok"}

    return calls, fake


def _with_tmp_cache(fn):
    orig_cache_file = cache_mod.CACHE_FILE
    orig_status = cache_mod.providers.status
    orig_lang = i18n.get_lang()
    with tempfile.TemporaryDirectory() as tmp:
        cache_mod.CACHE_FILE = Path(tmp) / "cache.json"
        try:
            fn()
        finally:
            cache_mod.CACHE_FILE = orig_cache_file
            cache_mod.providers.status = orig_status
            i18n.set_lang(orig_lang)


def test_same_lang_within_ttl_reuses_cache_no_requery():
    def run():
        i18n.set_lang("en")
        calls, fake = _fake_status_counter()
        cache_mod.providers.status = fake

        cache_mod.fetch_all_statuses(["claude"], show_progress=False)
        check("first call: queried once", calls["n"] == 1)

        cache_mod.fetch_all_statuses(["claude"], show_progress=False)
        check("second call, same lang, within TTL: not requeried", calls["n"] == 1)

    _with_tmp_cache(run)


def test_lang_switch_within_ttl_forces_requery():
    def run():
        i18n.set_lang("en")
        calls, fake = _fake_status_counter()
        cache_mod.providers.status = fake

        cache_mod.fetch_all_statuses(["claude"], show_progress=False)
        check("first call (en): queried once", calls["n"] == 1)

        i18n.set_lang("ru")
        statuses = cache_mod.fetch_all_statuses(["claude"], show_progress=False)
        check("second call (ru), same TTL window: requeried despite fresh timestamp", calls["n"] == 2)
        check("result still returned", statuses["claude"]["kind"] == "ok")

        i18n.set_lang("ru")
        cache_mod.fetch_all_statuses(["claude"], show_progress=False)
        check("third call, lang unchanged from second (ru): not requeried again", calls["n"] == 2)

    _with_tmp_cache(run)


def test_legacy_entry_missing_lang_field_forces_requery():
    """A cache entry written before this field existed (entry.get("lang")
    is None) must self-heal by refetching once, not compare None == None
    and wrongly count as a match."""
    def run():
        i18n.set_lang("en")
        cache = {"statuses": {"claude": {
            "timestamp": int(__import__("time").time()),
            "status": {"pct_used": 5, "rows": [], "note": None, "kind": "ok"},
            # no "lang" key at all
        }}}
        cache_mod.save_cache(cache)

        calls, fake = _fake_status_counter()
        cache_mod.providers.status = fake
        cache_mod.fetch_all_statuses(["claude"], show_progress=False)
        check("legacy entry with no lang field: requeried, not silently reused", calls["n"] == 1)

    _with_tmp_cache(run)


def test_gated_provider_toggle_mismatch_still_forces_requery():
    """Regression guard: the language check must not short-circuit past
    the existing gated-provider (antigravity/grok) toggle check — both
    conditions have to independently gate reuse."""
    def run():
        i18n.set_lang("en")
        cache = {"statuses": {"antigravity": {
            "timestamp": int(__import__("time").time()),
            "status": {"pct_used": None, "rows": [], "note": None, "kind": "not-checked"},
            "lang": "en",
        }}}
        cache_mod.save_cache(cache)

        calls, fake = _fake_status_counter()
        cache_mod.providers.status = fake
        antigravity.set_check_enabled(True)
        try:
            cache_mod.fetch_all_statuses(["antigravity"], show_progress=False)
        finally:
            antigravity.set_check_enabled(False)
        check("same lang, but gate flipped on over a not-checked entry: still requeried", calls["n"] == 1)

    _with_tmp_cache(run)


def main():
    print("test_cache:")
    test_same_lang_within_ttl_reuses_cache_no_requery()
    test_lang_switch_within_ttl_forces_requery()
    test_legacy_entry_missing_lang_field_forces_requery()
    test_gated_provider_toggle_mismatch_still_forces_requery()
    print("test_cache: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
