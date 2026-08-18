"""The two picker front-ends: ui.picker (Textual, interactive tty) and
ui.plain (numbered fallback, everything else). Neither submodule imports
textual at module scope — see ui.picker's docstring — so `import sai.ui`
and its submodules stays safe under a plain interpreter with no textual
installed.
"""
