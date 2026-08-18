"""Provider registry — ORDER is the list every caller iterates in (menu
rows, `install`, `auth`), and `registry` maps a provider key to its module.
Adding a provider = one new module (see providers/base.py for the shape
contract each must implement) + one entry here. Nothing else changes.

The functions below are thin compatibility helpers so call sites read as
`providers.installed("claude")` rather than reaching into the registry and
a module attribute by hand every time.
"""
import shutil
import subprocess

from sai.i18n import t
from sai.providers import antigravity, claude, codex, grok

ORDER = ["claude", "codex", "antigravity", "grok"]

registry = {
    "claude": claude,
    "codex": codex,
    "antigravity": antigravity,
    "grok": grok,
}


def installed(p):
    return shutil.which(registry[p].BIN) is not None


def label(p):
    return registry[p].LABEL


def install(p):
    subprocess.run(registry[p].INSTALL_CMD, shell=True)


def update(p):
    subprocess.run(registry[p].UPDATE_CMD)


def last_used_epoch(p):
    return registry[p].last_used_epoch()


def status(p):
    mod = registry.get(p)
    if mod is None:
        # Defensive only: every call site iterates ORDER or a subset of
        # it, so this is unreachable in practice — kept because the
        # pre-split provider_status() had the same fallback for an
        # unrecognized key and this is a mechanical port, not a rewrite.
        return {"pct_used": None, "rows": [], "note": t("note_no_status_configured"), "kind": "no-usage-api"}
    return mod.status()


def launch(p, yolo, prompt, cont):
    registry[p].launch(yolo, prompt, cont)
