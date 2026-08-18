# Architecture

selectorai is a small Python application (stdlib-only except for the
interactive picker, which uses Textual from an isolated venv) plus a
dependency-free bash fallback. This document is the module contract — both
for contributors and for keeping the layout honest.

## Layout

```
selectorai.py            # thin executable entry point: from sai.cli import main
selectorai.sh            # legacy bash fallback — feature-frozen, launches + quota only
sai/                     # the Python package (all logic lives here)
  __init__.py
  paths.py               # every filesystem path constant: state dir, cache, i18n, themes
  i18n.py                # t(), language loading/resolution, cmd_lang
  bigfont.py             # block-letter font + render_big
  themes.py              # theme listing/selection, cmd_theme
  timeutil.py            # fmt_ago, countdowns, reset-date parsing
  sysinfo.py             # machine load/mem/disk/uptime, who-is-connected
  cache.py               # status cache (per-provider TTLs), TerminalProgress, fetch_all_statuses
  health.py              # online/warning/offline classification + service-status probes
  models.py              # per-provider model listing (safe sources only, long cache)
  session.py             # tmux background-session persistence: wrap_launch, reattach descriptor, cmd_background
  auth.py                # login capture with clean-URL reconstruction, cmd_auth
  installer.py           # cmd_setup: guided end-to-end onboarding
  cli.py                 # main(): global flags, dispatch, cmd_menu, cmd_status, venv bootstrap/re-exec
  providers/
    __init__.py          # ORDER + registry assembled from the modules below
    base.py              # shared helpers + the status-dict shape contract
    claude.py
    codex.py
    antigravity.py
    grok.py
  ui/
    __init__.py
    picker.py            # Textual app (sections, key handling, restart sentinels)
    plain.py             # numbered fallback menu
i18n/{en,es,ru}.json     # every user-facing string, one flat JSON per language
themes/*.tcss            # Textual stylesheets — a theme is a file, never code
tests/                   # offline tests only — no test may invoke a real AI CLI
docs/                    # deep-dive notes, research, this file
```

## The provider contract

Each `sai/providers/<name>.py` module exposes:

| Symbol | Type | Meaning |
|---|---|---|
| `NAME` | str | registry key, lowercase (`"claude"`) |
| `LABEL` | str | display name (`"Claude Code"`) |
| `BIN` | str | executable name to probe with `shutil.which` |
| `INSTALL_CMD` | str | shell one-liner official installer |
| `UPDATE_CMD` | list[str] | argv for self-update |
| `LOGIN_CMD` | list[str] | argv for the login flow (device-code style preferred) |
| `LOGIN_STATUS_CMD` | list[str] \| None | argv for a non-interactive auth check, if one exists |
| `status()` | fn → dict | quota status — see shape below |
| `last_used_epoch()` | fn → int | newest activity timestamp from the CLI's own local files, 0 = never |
| `launch(yolo, prompt, cont)` | fn | exec the CLI with the fixed preset flags (never returns on success) |
| `list_models()` | fn → list[str] \| None | available models, or None when unknowable — must be safe to call (no auth side effects) |

`status()` returns exactly:

```python
{"pct_used": int | None,          # worst-case % used across buckets, None = unknown
 "rows": [(label, pct_used, reset_info), ...],   # one row per quota bucket
 "note": str | None,              # shown when rows is empty
 "kind": "ok" | "auth-needed" | "not-checked" | "no-usage-api"}  # why it looks this way
```

Adding a provider = one new module + one entry in `providers/__init__.py`
ORDER. Nothing else changes.

## Hard-won rules (violate these and you re-learn them the painful way)

1. **Never probe a provider CLI speculatively.** An unauthenticated
   `agy -p ...` opens a real Google OAuth browser popup; the same class of
   risk applies to any CLI whose auth behavior you haven't confirmed. Live
   status probes are opt-in (`--check-antigravity`) and cached with long
   backoff TTLs precisely because of this.
2. **Never mutate shared terminal state** (`stty`, escape codes that
   persist). A full-screen TUI launched afterwards reads that state and
   there is no way to hand control back to fix it. Textual owns the
   terminal inside the picker; nothing else touches it.
3. **Launches are `exec`'d, never piped.** Codex refuses to start as a TUI
   when stdout is not a terminal; capturing launch output broke it outright.
4. **Every user-facing string goes through `t()`** and lives in all three
   `i18n/*.json` files. No inline English in code paths users see.
5. **Verified vs. assumed is always marked.** If a behavior wasn't
   confirmed against the real CLI (`--help`, live run, or shipped docs),
   the code comment and the docs say so.
6. **Tests never invoke real AI CLIs.** They stub `status()` dicts and run
   the Textual app headless via `run_test()`. Real CLIs cost quota and can
   pop auth windows on the machine running the tests.
7. **State lives in `~/.selectorai/`**, never in the repo. The repo is
   safe to `git clean` at any time.
