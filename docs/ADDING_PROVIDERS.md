# Adding a provider

selectorai's provider list is deliberately closed off from the rest of the
codebase behind one contract — see the table in
[`docs/ARCHITECTURE.md`](ARCHITECTURE.md#the-provider-contract). This is
the practical, do-this-then-that version of that table: what a new
`sai/providers/<name>.py` module needs, in what order to build it, and the
mistakes this project already made once so you don't have to repeat them.

## The shape

Every provider module exposes exactly this surface (see
`sai/providers/base.py` for the shared status-dict contract, and any
existing module — `claude.py` is the simplest — for a real example):

```python
NAME              # str, registry key, lowercase
LABEL             # str, display name
BIN               # str, executable name for shutil.which
INSTALL_CMD       # str, shell one-liner
UPDATE_CMD        # list[str], argv
LOGIN_CMD         # list[str], argv
LOGIN_STATUS_CMD  # list[str] | None
status()          # -> dict, see shape below
last_used_epoch() # -> int, 0 = never
launch(yolo, prompt, cont)  # exec's, never returns on success
list_models()     # -> list[str] | None
```

`status()` returns exactly:

```python
{"pct_used": int | None,
 "rows": [(label, pct_used, reset_info), ...],
 "note": str | None,
 "kind": "ok" | "auth-needed" | "not-checked" | "no-usage-api"}
```

## Step by step

1. **Read the CLI's own `--help` and shipped docs first.** Not a blog post,
   not a chat summary, not this project's memory of a similar CLI — the
   actual `<binary> --help`, `<binary> <subcommand> --help`, and anything
   under the tool's own `docs/` if it ships one (Grok's `~/.grok/docs/`
   is a real example: it's what proved `/usage` is TUI-only, saving a
   wasted implementation attempt). Every fact you write down from this
   pass is **verified**; anything you couldn't check this way — including
   anything carried over from research notes like
   [`docs/CANDIDATES.md`](CANDIDATES.md) — is **assumed**, and must say so
   in both the code comment and the docs. See rule 5 in
   `docs/ARCHITECTURE.md`.

2. **Find the install command, and confirm it needs no sudo.** All four
   existing providers install into the user's home directory
   (`~/.local/bin`, `~/.codex/`, etc.) — see
   [`docs/NOTES.md`](NOTES.md#install-methods-all-verified-no-sudo-required).
   A system-wide installer is a strong signal this CLI wasn't built with
   this kind of tool in mind.

3. **Find the login flow, and prefer a device-code / URL flow over an
   auto-opening local browser.** `codex login --device-auth` and
   `grok login --device-auth` exist specifically so the login works the
   same over SSH as it does locally — check for an equivalent flag before
   assuming bare `<binary> login` is the only option.

4. **Before running the CLI at all — even once, even with `--help` — read
   the safety checklist below.** This is the step this project got wrong
   with Antigravity, and it cost a real browser popup mid-session.

5. **Find (or rule out) a non-interactive usage/quota query.** Try
   `<binary> --help` for a `usage`/`status`/`quota` subcommand, then a
   flag on the main command, then a documented but TUI-only slash command
   (which counts as *not* available — see Grok's `/usage`, TUI-only per
   its own docs). If nothing non-interactive exists, `status()` should
   return `kind: "no-usage-api"` and a clear `note`, same as Codex/Grok
   today — don't leave `pct_used` guessing at a number that was never
   really queried.

6. **Find the "last used" signal.** Every existing provider derives this
   from the CLI's own local history file mtime (`~/.claude/history.jsonl`,
   etc.), never from selectorai's own launch log — see
   [`docs/NOTES.md`](NOTES.md#last-used--solves-the-original-problem) for
   why. Check the CLI's own data directory for something equivalent.

7. **Find the auto-approve ("yolo") flag and its safer default**, and add
   a row to the auto-mode table in
   [`docs/NOTES.md`](NOTES.md#auto-mode-flags-per-provider). Every
   existing provider has a "safer default" (some kind of workspace-scoped
   or classifier-based approval) plus a `--yolo`-triggered full bypass —
   match that shape rather than only wiring up the dangerous flag.

8. **Find the resume flag** (`-c`/`--continue`, or the CLI's own
   equivalent) and confirm whether it's a flag or a subcommand (Codex's
   `resume --last` reroutes the whole invocation, unlike the other three's
   plain `--continue`) — see
   [`docs/NOTES.md`](NOTES.md#resuming---continue---c).

9. **Write the module**, following the skeleton below.

10. **Add one line to `providers/__init__.py`'s `ORDER`** (and the
    `registry` dict). Nothing else in the codebase should need to change —
    if it does, something is reaching into a provider module directly
    instead of going through `sai/providers/__init__.py`'s helpers, and
    that's worth fixing on its own.

11. **Add every new user-facing string to all three `i18n/*.json` files**
    (`en`, `es`, `ru`) with identical key sets — see
    [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) rule 4. `es` uses Argentine
    voseo. Run a quick key-count check (`python3 -c "import json;
    print({l: len(json.load(open(f'i18n/{l}.json'))) for l in
    ('en','es','ru')})"`) before opening a PR — the three counts must
    match.

12. **Add a test file** under `tests/` (stub `status()`/`subprocess`, never
    invoke the real CLI) and register it by just dropping it in — 
    `tests/run_tests.py` discovers `test_*.py` automatically. Run both
    `python3 tests/run_tests.py` and
    `~/.selectorai/venv/bin/python3 tests/run_tests.py` before opening a PR.

## Commented skeleton

```python
"""<Provider Name> provider.

Verified against `<binary> --help` on <date> — note anything you
couldn't confirm live as ASSUMED, right here, not silently.
"""
import os
import subprocess
from pathlib import Path

from sai import session
from sai.i18n import t
from sai.providers.base import _extract  # regex-extract helper, if the
                                          # CLI's usage output is free text
from sai.timeutil import _reset_with_countdown  # if you have a reset time

NAME = "example"                  # registry key — lowercase, no spaces
LABEL = "Example CLI (Vendor)"    # shown everywhere in the UI
BIN = "example"                   # what shutil.which() looks for

# One-liner, no sudo — verified: <how you confirmed this>.
INSTALL_CMD = "curl -fsSL https://example.com/install.sh | bash"
UPDATE_CMD = ["example", "update"]

# Prefer a device-code/URL flow over auto-opening a local browser — see
# ADDING_PROVIDERS.md step 3. LOGIN_STATUS_CMD is None if there's no
# confirmed non-interactive way to check login state.
LOGIN_CMD = ["example", "login", "--device-auth"]
LOGIN_STATUS_CMD = ["example", "login", "status"]  # or None


def last_used_epoch():
    # Prefer the CLI's own local history/log file mtime over anything
    # selectorai tracks itself — see NOTES.md's "Last used" section.
    f = Path.home() / ".example" / "history.jsonl"
    return int(f.stat().st_mtime) if f.exists() else 0


def status():
    # SAFETY: only call the CLI here if a bare/authenticated-or-not
    # invocation is CONFIRMED not to trigger an interactive login flow
    # (OAuth popup, browser open, etc). If that's unverified, gate this
    # behind an opt-in flag instead — see antigravity.py's
    # `_check_enabled` and ARCHITECTURE.md rule 1. If there's no
    # non-interactive usage query at all, skip straight to the
    # "no-usage-api" return below and don't shell out.
    try:
        out = subprocess.run(
            ["example", "usage", "--json"], capture_output=True, text=True, timeout=20
        ).stdout
    except Exception:
        out = ""

    if not out:
        return {"pct_used": None, "rows": [], "note": t("note_example_no_data"),
                 "kind": "no-usage-api"}

    # ... parse `out` into rows ...
    pct_used = 0  # placeholder
    rows = []     # [(label, pct_used, reset_info), ...]
    return {"pct_used": pct_used, "rows": rows, "note": None, "kind": "ok"}


def list_models():
    # Only implement a live call here if a bare invocation is confirmed
    # safe (no auth side effects) — see ARCHITECTURE.md's provider
    # contract table. If unverified, return None and let sai.models'
    # _RISKY_PROVIDERS gate + caution message cover it, following
    # antigravity.py/grok.py's pattern.
    return None


def launch(yolo, prompt, cont):
    # Fixed "preset" flags — the same ones fire on every launch. Safer
    # default first, then the full-bypass flag under --yolo. See
    # NOTES.md's "Auto-mode flags, per provider" table.
    if yolo:
        args = ["example", "--dangerously-skip-permissions"]
    else:
        args = ["example", "--safe-mode"]
    if cont:
        args.append("--continue")
    print(t("launch_example", flags=" ".join(args[1:])))
    if prompt:
        args.append(prompt)
    # Routes through wrap_launch so `background on` (tmux) can pick this
    # launch up — no-op passthrough when tmux is off/unavailable.
    args = session.wrap_launch(NAME, args)
    # EXEC, NEVER PIPE — see the safety checklist below.
    os.execvp(args[0], args)
```

## Safety checklist (read before running the CLI even once)

These are hard-won, not theoretical — each one below is a real incident
from this project's own history, written up in full in
[`docs/NOTES.md`](NOTES.md).

- **Never probe a provider CLI speculatively.** An unauthenticated
  `agy -p "/usage"` opened a real Google OAuth browser popup on this
  machine, mid-session, with no warning — see NOTES.md's
  ["Antigravity's live usage check is opt-in"](NOTES.md#antigravitys-live-usage-check-is-opt-in---check-antigravity)
  section. Before wiring up any live call in `status()` or `list_models()`,
  confirm — against the CLI's own docs or, cautiously, a manual run you're
  watching — that a bare/unauthenticated invocation degrades gracefully
  (prints an error) rather than falling through to an interactive flow.
  If you can't confirm that, gate the call behind an explicit opt-in flag
  with a long-backoff cache, same shape as `--check-antigravity`.
- **Launches are `exec`'d, never piped or captured.** Codex refuses to
  start as a TUI at all when stdout isn't a real terminal — capturing its
  output to parse or log broke it outright. `launch()` must end in
  `os.execvp(...)`, never `subprocess.run(..., capture_output=True)`.
- **Never mutate shared terminal state** (`stty`, raw mode, anything that
  outlives the current process). An earlier version of `auth`'s
  clean-URL flow used `stty cols <N>` to dodge a CLI's own line-wrapping —
  it doesn't auto-revert, and a full-screen TUI launched afterwards reads
  the corrupted width at startup with no way to recover short of `reset`.
  Confirmed live (a Claude Code session box-drawing itself across a huge
  column count) — see NOTES.md's
  ["Logging in (`auth`)"](NOTES.md#logging-in-auth--one-flag-every-provider-clean-url-every-time)
  section. If you need to fix up a CLI's output, do it after the fact
  (like `auth`'s tee-and-reconstruct approach), not by changing the
  terminal underneath it.
- **Mark verified vs. assumed, every time.** A behavior confirmed against
  a live run or a real `--help`/docs page is verified; anything else —
  including something copied from another provider's shape because "it's
  probably the same" — is assumed, and the code comment plus any doc
  reference must say so explicitly. Silent assumptions are how the
  Antigravity popup and the `stty` incident both happened.
- **Tests never invoke real AI CLIs.** Stub `status()` dicts, stub
  `subprocess`/`shutil.which`, and drive the Textual picker through its
  own `run_test()` pilot — see `tests/test_picker_headless.py`. A test
  that shells out to `example`/`claude`/`codex`/`agy`/`grok` for real can
  cost quota or pop an auth window on whatever machine runs the suite.
