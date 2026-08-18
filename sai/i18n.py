"""i18n — default English, plus Russian and Spanish. Strings live in
i18n/<code>.json under the repo root, not inline in the code, so adding or
editing a translation doesn't mean touching Python. `t(key, **kwargs)`
looks up STRINGS[current lang][key] and falls back to English, then the
raw key.
"""
import json
import os
import sys

from sai.paths import I18N_DIR, LANG_FILE

LANG_CODES = ["en", "ru", "es"]

# Module-level "current language" state, read/written through get_lang()/
# set_lang() rather than a bare global — the old single-file script used
# `global LANG`; callers across package boundaries (sai.cli, sai.ui.picker)
# need the same shared, mutable slot without importing a raw name that
# `from sai.i18n import LANG` would freeze at import time.
_lang = "en"  # overwritten by sai.cli.main() before anything is printed


def get_lang():
    return _lang


def set_lang(code):
    global _lang
    _lang = code


def _load_strings():
    strings, names = {}, {}
    for code in LANG_CODES:
        try:
            data = json.loads((I18N_DIR / f"{code}.json").read_text(encoding="utf-8"))
        except Exception:
            data = {}
        names[code] = data.pop("_name", code)
        strings[code] = data
    return strings, names


STRINGS, LANG_NAMES = _load_strings()


def t(key, **kwargs):
    s = STRINGS.get(_lang, STRINGS["en"]).get(key) or STRINGS["en"].get(key, key)
    return s.format(**kwargs) if kwargs else s


def _prompt(text):
    """input() that fails quietly instead of a raw traceback when stdin
    has no more input (piped, closed, or Ctrl-D/Ctrl-C mid-prompt).
    Lives here rather than in a generic utils module because cmd_lang
    (below) was its first caller; sai.themes imports it for the same
    reason cmd_theme needs it."""
    try:
        return input(text)
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def resolve_lang(override):
    if override and override in LANG_CODES:
        return override
    env = os.environ.get("SELECTORAI_LANG")
    if env and env in LANG_CODES:
        return env
    if LANG_FILE.exists():
        saved = LANG_FILE.read_text().strip()
        if saved in LANG_CODES:
            return saved
    return "en"


def cmd_lang(argv):
    if argv:
        choice = argv[0]
        if choice not in LANG_CODES:
            print(t("lang_invalid", choice=choice, options=", ".join(LANG_CODES)))
            sys.exit(1)
    else:
        print("Pick a language / Elegí un idioma / Выберите язык:")
        for i, code in enumerate(LANG_CODES, start=1):
            print(f"  {i}) {LANG_NAMES[code]} ({code})")
        raw = (_prompt("> ") or "").strip()
        if raw in LANG_CODES:
            choice = raw
        else:
            try:
                choice = LANG_CODES[int(raw) - 1]
            except (ValueError, IndexError):
                print("Invalid choice.")
                sys.exit(1)
    LANG_FILE.write_text(choice)
    set_lang(choice)
    print(t("lang_saved", lang=LANG_NAMES[choice]))
