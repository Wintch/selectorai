"""Every filesystem path constant selectorai touches, in one place: the
package's own layout under REPO_ROOT (source, safe to `git clean`) and the
user's mutable state under STATE_DIR (~/.selectorai — never the repo, see
docs/ARCHITECTURE.md rule 7).
"""
from pathlib import Path

# This file lives at <repo>/sai/paths.py, so two .parent hops (not one)
# reach the repo root — unlike the pre-split THEMES_DIR/I18N_DIR, which
# were Path(__file__).parent off the single top-level selectorai.py.
REPO_ROOT = Path(__file__).resolve().parent.parent

# The thin executable entry point (see selectorai.py). Referenced by the
# venv bootstrap re-exec in sai/cli.py, which must exec *this* script, not
# a module file inside sai/ — os.execv needs a real file to hand back to
# the interpreter, and sai/cli.py isn't runnable standalone.
ENTRY_SCRIPT = REPO_ROOT / "selectorai.py"

I18N_DIR = REPO_ROOT / "i18n"
THEMES_DIR = REPO_ROOT / "themes"

# Mutable state, always under the user's home, never the repo.
STATE_DIR = Path.home() / ".selectorai"
LAUNCH_LOG = STATE_DIR / "launch.log"
LANG_FILE = STATE_DIR / "lang"
THEME_FILE = STATE_DIR / "theme"
CACHE_FILE = STATE_DIR / "cache.json"
CHECK_ANTIGRAVITY_FILE = STATE_DIR / "check_antigravity"
CHECK_GROK_FILE = STATE_DIR / "check_grok"
