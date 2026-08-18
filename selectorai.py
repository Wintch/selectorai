#!/usr/bin/env python3
# selectorai — thin executable entry point. All logic lives in sai/ (see
# docs/ARCHITECTURE.md for the module layout); this file exists so there's
# a real script path for `./selectorai.py` and for the venv bootstrap
# re-exec in sai.cli to target (os.execv needs a runnable file, not a
# module inside the sai/ package). Running this file the normal way
# (`./selectorai.py`, `python3 selectorai.py`) already puts its own
# directory — the repo root, sai/'s parent — at sys.path[0], so `sai` is
# importable with no path juggling here.
from sai.cli import main

if __name__ == "__main__":
    main()
