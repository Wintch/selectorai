"""Picker theme — the "front" kept separate from the picker's actual logic
(widget structure, key handling, selection) on purpose: each theme is
just a Textual stylesheet file under themes/, nothing else changes.
Dropping in a new themes/<name>.tcss makes it selectable automatically —
no code touched. Reference screens: green monochrome MU-TH-UR-style HUD
for "mother" (default), cyan/amber/red Nostromo deorbital-descent
computer for "nostromo".
"""
import sys

from sai.i18n import _prompt
from sai.paths import THEME_FILE, THEMES_DIR

DEFAULT_THEME = "mother"


def list_themes():
    if not THEMES_DIR.is_dir():
        return []
    return sorted(p.stem for p in THEMES_DIR.glob("*.tcss"))


def current_theme():
    if THEME_FILE.exists():
        saved = THEME_FILE.read_text().strip()
        if saved in list_themes():
            return saved
    return DEFAULT_THEME if DEFAULT_THEME in list_themes() else (list_themes() or [None])[0]


def cmd_theme(argv):
    themes = list_themes()
    if not themes:
        print(f"No themes found under {THEMES_DIR}/")
        sys.exit(1)

    if argv:
        choice = argv[0]
        if choice not in themes:
            print(f"Unknown theme '{choice}'. Options: {', '.join(themes)}")
            sys.exit(1)
    else:
        cur = current_theme()
        print("Current theme:", cur)
        print()
        for i, name in enumerate(themes, start=1):
            mark = " (current)" if name == cur else ""
            print(f"  {i}) {name}{mark}")
        raw = (_prompt("Pick a theme: ") or "").strip()
        choice = themes[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(themes) else raw
        if choice not in themes:
            print("Invalid choice.")
            sys.exit(1)

    THEME_FILE.write_text(choice)
    print(f"Theme set to: {choice}")
