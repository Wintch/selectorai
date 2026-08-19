# Notes — deep dive, findings, incidents

This is the project's research log: what was actually tried against each
provider's real CLI, what broke, and why the code ended up shaped the way
it did. The [README](../README.md) is the concise public-facing version —
this file is where the evidence lives. Every claim below is either
**verified** (confirmed against a real `--help`, a live run, or a
provider's own shipped docs) or explicitly marked **unverified**/
**live-unverified** — see [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) rule 5.

## Table of contents

- [Guided setup (`setup`)](#guided-setup-setup--a-walkthrough-not-a-new-mechanism)
- [Fast startup, progress bar, caching](#fast-startup-live-progress-bar--smart-caching)
- [Interactive picker internals](#interactive-picker-arrow-keys-big-letters-retro-terminal-look)
- [Themes](#themes--the-front-kept-separate-from-the-pickers-logic)
- [Language](#language)
- [Reset times: countdown, not just a date](#reset-times-countdown-not-just-a-date)
- [Machine status](#machine-status)
- [Who else is connected (`status --who`)](#who-else-is-connected-status---who)
- [What "status" actually means, per provider](#what-status-actually-means-per-provider)
- [Service status probes](#service-status--a-real-outage-marks-a-provider-offline-too)
- [Model listings (`models`)](#model-listings-models--explicit-only-never-from-statusmenu)
- [State files](#state-files-selectorai)
- ["Last used"](#last-used--solves-the-original-problem)
- [Ordering — by last used, not by quota](#ordering--by-last-used-not-by-quota)
- [Auto-mode flags, per provider](#auto-mode-flags-per-provider)
- [Resuming (`--continue` / `-c`)](#resuming---continue---c)
- [Background sessions (tmux)](#background-sessions-tmux--reattach-after-an-ssh-drop)
- [Logging in (`auth`) — the stty incident](#logging-in-auth--one-flag-every-provider-clean-url-every-time)
- [Used % vs. left %](#used--vs-left---always-shown-together)
- [Install methods](#install-methods-all-verified-no-sudo-required)
- [Antigravity's OAuth-popup incident (`--check-antigravity`)](#antigravitys-live-usage-check-is-opt-in---check-antigravity)
- [Grok's `--check-grok` — tmux-driven TUI scrape](#groks---check-grok--live-but-via-a-tmux-driven-tui-scrape-not-a-flag)
- [Antigravity auth over SSH / Error 400](#antigravity-auth-over-ssh--remote-console)
- [Known limitations](#known-limitations)
- [Next / open items](#next--open-items)

---

## Guided setup (`setup`) — a walkthrough, not a new mechanism

```bash
./selectorai.py setup             # interactive, step by step
./selectorai.py setup --dry-run   # non-interactive: prints what each step WOULD do, changes nothing
```

Nine steps, each skippable (just answer N or hit Enter), each one reusing
the real subcommand it's offering rather than a separate implementation:
language (`lang`'s picker) → this machine's load/mem/disk → every
provider's installed/not-installed state, offering the real install
one-liner for anything missing → each installed provider's sign-in status
(and an offer to run `auth`'s clean-URL login flow) → Antigravity's
live-usage-check opt-in, with the OAuth-popup caveat spelled out → a tmux
availability note → the theme picker (`theme`'s picker) → an offer to
refresh model listings (`models`, with its own caution) → a final
force-refreshed `status`.

Same as `auth`/`--check-antigravity`/every other thing that can pop a
browser or touch quota: `setup` requires a real interactive terminal
(stdin and stdout both a tty) and refuses to run otherwise, printing an
explanation instead. The one exception is `--dry-run`, which never calls
`input()` and never shells out to anything — every offer just prints the
command it would have run. That's the only mode automated tests are
allowed to exercise (see `tests/test_installer.py`); nothing here can
launch a real `claude`/`codex`/`agy`/`grok` process except the one step
that's explicitly supposed to (a confirmed provider install, or a
confirmed sign-in, both of which need you to type `y` yourself, at a
keyboard, in the moment).

## Fast Startup, Live Progress Bar & Smart Caching

Probing live usage from CLI providers (such as Claude Code and Google Antigravity) involves executing separate subprocesses and querying remote APIs, which can take 1.5–4.0s.

To make startup instantaneous while providing smooth feedback:
- **Terminal Progress Bar**: While querying providers on cold runs or `--refresh`, an animated terminal progress bar (`[████████░░░░░░░░] 50% Checking Claude Code...`) displays real-time progress as each provider responds, ensuring you know the system is actively working and not hung. It automatically clears cleanly before launching the TUI.
- **Short-Lived Status Caching**: Results are cached locally in `~/.selectorai/cache.json` for 60 seconds. Subsequent launches within that window start **instantaneously (~0.05s)**. Use `--refresh` or `-r` to force a live network check at any time.
- **Early Re-Exec**: Direct delegation to the dedicated Textual virtual environment eliminates dual-startup overhead.
- **Pure-Python Date Parsing**: ISO and human date strings from provider outputs are parsed in microseconds without spawning external `date` subprocesses.

## Interactive picker: arrow keys, big letters, retro terminal look

The bare `./selectorai.py` (no subcommand, run in a real terminal) opens a
full-screen picker instead of the old numbered list: ↑/↓ to move, Enter to
launch, Q/Esc to quit. Monospace, a big block-letter "SELECTOR AI" title,
boxed panels — styled after real sci-fi-computer HUD references (see
"Themes" below), not hand-waved retro. A few small animated touches: the
title fades in on mount (like a CRT warming up) instead of snapping to full
brightness, a cursor block blinks next to the system-ready line at a normal
terminal cadence (~530ms), and the active-item highlight transitions
smoothly instead of snapping when you move the selection.

Deliberately simple where it counts: each row in the list is just the
provider's name, nothing else crammed in. All the detail — quota per
bucket (as a tree where a provider has parallel buckets, see "Reset times"
below), countdown, last-used — only shows in the panel below the list, for
whichever provider is currently highlighted, updating live as you move the
selection. The list isn't sorted by quota anymore (see "Ordering" below) —
it's sorted by last used instead, most recent at the top, so the AI you
were just in stays the easy default pick next time.

Built on [**Textual**](https://textual.textualize.io/), the current
standard for Python terminal UIs (actively developed by the Rich/Textualize
team) — chosen over hand-rolling raw-mode key reading with `termios`/`tty`
for a concrete reason tied to what already went wrong once in this project:
`Textual.run()` *guarantees* the terminal gets restored on any exit path
(normal, exception, Ctrl-C), the same invariant the `stty` incident (see
"Error 400" section below) taught the hard way needs to hold. Hand-rolled
raw-mode code has to get every exit path right itself; Textual already does.

**This is the one place in the project with a real dependency** — everything
else (`status`, `auth`, `lang`, launching the CLIs) stays stdlib-only.
Handled without touching the system Python at all (this machine has no bare
`pip` — Debian's externally-managed-environment policy):

- First interactive run creates `~/.selectorai/venv` (plain `python3 -m
  venv`, isolated, no sudo) and installs `textual` into it — confirmed ~2s.
- Re-execs itself under that venv's interpreter (`os.execv`, same PID, same
  arguments) so the rest of the run has `textual` importable.
- If that fails for any reason (offline, no `venv` module) it prints why and
  falls back to the old plain numbered menu — same as a non-interactive
  invocation (piped, no tty) always does, skipping the picker entirely.

Verified headless with Textual's own `run_test()` pilot (simulated
arrow-down + Enter, no real terminal involved, since this environment has no
tty to demo it live in): app mounts, all providers list, arrow keys move the
highlight and update the detail panel, Enter returns the right provider.
Try it yourself in a real terminal to see the actual look.

## Themes — the "front" kept separate from the picker's logic

Each theme is a standalone [Textual stylesheet](https://textual.textualize.io/guide/CSS/)
file under `themes/*.tcss` — nothing else about the picker changes between
them. The Python side (`sai/ui/picker.py`'s `_build_app`) only owns
*behavior*: widget structure, key handling, what happens on Enter. It loads
whichever theme is selected via Textual's own `CSS_PATH`, so switching
looks is a file swap, never a code change — dropping a new
`themes/<name>.tcss` in makes it selectable automatically, no code to
touch.

```bash
./selectorai.py theme              # show current theme + pick from a list
./selectorai.py theme nostromo     # set directly
```

Persisted to `~/.selectorai/theme`. Three so far — two modeled on real
sci-fi-computer HUD references, one a user-picked custom palette:

| Theme | Reference | Look |
|---|---|---|
| `mother` (default) | Weyland-Yutani computer HUD — green vector lines on black, rounded boxed panels, filled highlight on the active field | Monochrome green (`#33ff66` / `#1f9945`) |
| `nostromo` | The Nostromo's "DEORBITAL DESCENT" navigation display — cyan-bordered *sharp-cornered* panels, amber/red accents on the data instead of one flat color | Cyan borders/title, amber system line, red detail text |
| `custom` | Not reference-based — a specific palette requested directly | Light-brown title/borders (`#c19a6b`), white picker list and system readout, light-green detail panel (`#90ee90`) |

The disk/memory warning word (`⚠ low` / `⚠ high`) in the system readout
stays yellow in every theme, even `custom` where the rest of that panel is
white — Textual CSS can't target a substring inside one widget's text, so
`_sysinfo_markup()` (`sai/ui/picker.py`) wraps just the `⚠ ...` tail in Rich
markup (`[yellow]...[/yellow]`) before it's set, only inside the Textual
render path. The plain `status`/fallback-menu output is untouched by this —
no markup tags leak into a plain terminal that doesn't interpret them.

Verified headless the same way as the picker itself (Textual's `run_test()`)
— all `.tcss` files load without error and selection works identically
under each, confirming the behavior really doesn't change between themes.
More reference-based themes to come; adding one means a new `.tcss` file,
not touching any Python.

### Changing language or theme from inside the picker

`L` cycles the language, `T` cycles the theme — both shown in the footer
next to the other key hints, both persist immediately (same files
`lang`/`theme` write to) and take effect right away: the picker reloads
itself with the new setting rather than requiring you to quit and rerun.
A theme change alone is a cheap reload (just a different stylesheet); a
language change re-fetches provider status once, since label/note text is
already rendered into the cached data by the time it would otherwise
display — without that refetch, switching language would leave stale text
in the old language on screen until the *next* full run.

## Language

Three languages: **English (default)**, **Русский**, **Español**. Strings
live in `i18n/en.json` / `i18n/es.json` / `i18n/ru.json` — not inline in the
code — so adding a language or fixing a translation means editing a JSON
file, not touching Python. Each file is flat `key: value` plus a `_name`
field (the language's own name, shown in the `lang` picker). `t(key, ...)`
(`sai/i18n.py`) looks them up at runtime; provider flags
(`--dangerously-...`) are left untranslated since they're literal CLI
arguments, not prose.

```bash
./selectorai.py lang                  # interactive picker, saved to ~/.selectorai/lang
./selectorai.py lang ru               # set directly, saved
./selectorai.py --lang es status      # one-off override for this run only, not saved
SELECTORAI_LANG=ru ./selectorai.py    # env var override, useful for a specific shell/profile
```

Precedence: `--lang` flag (this run) → `$SELECTORAI_LANG` → saved
`~/.selectorai/lang` → English.

None of this — i18n, the retro picker, or `theme` — is ported to
`selectorai.sh`. Three-language string tables are far messier to keep
readable in POSIX shell than in JSON+Python, and a Textual-based UI needs
Python anyway. Since `.py` became the primary version, `.sh` stays a
plain-English, genuinely dependency-free fallback (its numbered menu) rather
than carrying any of this too.

## Reset times: countdown, not just a date

Every reset time — Claude's session/weekly/Fable, Codex's rate-limit,
Antigravity's per-bucket resets — shows a countdown next to the absolute
date, e.g. `resets in 2h 39m — Aug 17, 8:50am (...)` for something hours
away vs. `resets in 3d 21h — Aug 21, 4am (...)` for something days out. The
point is telling those two apart at a glance without doing the subtraction
yourself — a handful of rows, but they span wildly different timescales (a
5h session window next to a ~monthly Codex reset).

Computed differently depending on what's already available at parse time:
Codex and Antigravity already produce (or we already parse) a real
timestamp, so the countdown comes straight from that. Claude only ever
prints a human string like `Aug 21, 4am (America/Argentina/Buenos_Aires)` —
turning that into a countdown needed two fixes to how GNU `date -d` reads
it, both confirmed by hand: the trailing `(Zone/Name)` has to become a
leading `TZ="..."` prefix instead of staying in parens, and the comma right
before the time (`"Aug 17, 8:50am"`) makes it fail to parse at all unless
stripped first (`"Aug 17 8:50am"` works). If parsing ever fails for some
future format change, it just falls back to the plain absolute date — same
as before this existed, never an error.

Ported to both `selectorai.py` and `selectorai.sh` — this one isn't
Python-specific, so it stayed in sync in both.

## Machine status

Printed by default on `status` and on the plain menu view — pure `/proc` +
`os.getloadavg()`/`shutil.disk_usage()` reads, no subprocess, nothing that
needs elevated permission:

- **Load** — 1/5/15 min load average vs. CPU count → `OK, plenty of headroom` /
  `moderate` / `HIGH` (ratio of load1 to CPU count: <0.7 / <1.0 / ≥1.0).
- **Memory** — % used of total, from `MemTotal`/`MemAvailable`.
- **Disk (/)** — % used and GB free on the root filesystem.
- **Uptime**.

## Who else is connected (`status --who`)

Opt-in only — never runs unless you pass `--who`, so a plain `status` or menu
launch never touches session/login data. Two reasons it's gated:

1. It's extra info you don't always need.
2. An earlier version tried to identify "your own" session via
   `os.ttyname(0)` (tty ioctl) to tell it apart from others in `who`'s
   output — that call errors outright when stdin isn't a real tty (confirmed
   locally: `Inappropriate ioctl for device`) and is the kind of syscall that
   can trigger a permission prompt depending on context. Dropped it entirely.

Self-detection (local vs. remote) now uses only environment variables —
`SSH_CONNECTION` / `SSH_TTY` / `SSH_CLIENT` — which need no device access at
all. "Am I alone" is decided from `who`'s output: no other users, and no
non-loopback host in parentheses (that's how `who` marks a remote/SSH login)
→ alone. Otherwise it lists every other session with its origin (local vs.
remote-from-`<ip>`) and calls out other usernames or remote IPs explicitly.

## What "status" actually means, per provider

| | Session/weekly % | Data source | Reset info |
|---|---|---|---|
| **Claude Code** | ✅ real, live | `claude -p "/usage"` — this is the only CLI with a working non-interactive usage query confirmed without any extra gating | Exact reset time per bucket (session 5h, weekly, weekly-Fable) |
| **Codex CLI** | ⚠️ only after a failure | No non-interactive command exists (confirmed: not in `codex --help`, not in `codex login status`, not in `codex doctor`; the real data lives behind an internal `account/rateLimits/read` JSON-RPC method used only by the TUI's `app-server`, not worth reverse-engineering for this) | Only known once you actually hit the limit through this script — Codex's own error message includes the exact reset date/time, which gets saved and reused until it passes |
| **Antigravity (`agy`)** | ✅ confirmed live, and opt-in | `agy -p "/usage"`, gated behind `--check-antigravity`. Format confirmed against a real logged-in account (see below) — but the CLI can still trigger a fresh OAuth popup even after a prior successful login, due to upstream session bugs | Exact ISO timestamp per bucket, reformatted to local time |
| **Grok Build (xAI)** | ✅ confirmed live, and opt-in | A tmux-driven scrape of `/info`'s "Usage limit" popup tab, gated behind `--check-grok` — see [below](#groks---check-grok--live-but-via-a-tmux-driven-tui-scrape-not-a-flag) for the full mechanism and why there's no flag or JSON field to poll instead | "Resets: <Month Day, HH:MM>" text, parsed the same way Claude/Codex's human-readable reset strings are (`sai.timeutil._parse_reset_epoch`) |

Grok is a genuinely different case from the other three — not "no data",
but "the data only exists inside a pager-only TUI panel, never headlessly".
Full mechanism, the headless-mode findings that rule out a simpler
approach, and the two-layer live confirmation behind this are in
["Grok's `--check-grok`"](#groks---check-grok--live-but-via-a-tmux-driven-tui-scrape-not-a-flag)
further down this file — kept there rather than duplicated here since it's
long enough to want its own section.

**Why Codex can't just be polled like Claude:** there is no `codex usage`,
no flag, nothing under `codex --help`. `codex doctor` and `codex login
status` don't carry it either. It only shows via the interactive `/status`
slash command inside the TUI. This is a real gap, not an oversight — the
practical workaround already implemented (real error → saved exact reset
date) requires having actually launched Codex through this script at least
once while limited.

## Service status — a real outage marks a provider offline too

Quota/`% used` (above) is per-account and asks the provider's own CLI.
This is a second, independent signal: is the provider's *service itself*
up at all, per its public status page — a real outage means launching is
pointless regardless of what your own quota looks like. Both feed the same
health line (`status`, and the picker's detail panel), and an outage wins
outright over an otherwise-healthy quota reading.

Runs automatically on every `status`/menu call, in parallel with the quota
probe (so it adds no wall time), cached 5 minutes:

| Provider | Source | Verified 2026-08-17 |
|---|---|---|
| Claude Code | `status.claude.com/api/v2/status.json` (Statuspage JSON) — the legacy `status.anthropic.com` now 301s here | live, `indicator: "none"` (all clear) |
| Codex CLI | `status.openai.com/api/v2/status.json` — incident.io behind a Statuspage-compatible API, same `indicator` mapping | live, `indicator: "none"` |
| Antigravity | `status.cloud.google.com/incidents.json` — flat JSON array; an incident with no `end` timestamp is active, `status_impact: "SERVICE_OUTAGE"` maps to outage, anything else active maps to degraded | live, ~112KB, 4 already-resolved entries, none active |
| Grok Build | none — `status.x.ai` serves its real status page fine to a browser, but 403s a non-browser request to anything that looks like its status API (Cloudflare bot protection; a plain request even 404s there, so that path isn't real to begin with), and otherwise only exposes an RSS feed of free-text statuses. Always reports unknown rather than guessing. | live, confirmed 403/404 |

Every probe runs with a 3s timeout in its own thread (so 3 providers cost
~3s total, not 9s) and never raises — any failure just means "unknown",
same as a provider with no probe at all.

## Model listings (`models`) — explicit only, never from status/menu

```bash
./selectorai.py models              # refresh + print every installed provider's models
./selectorai.py models antigravity  # just one
```

Unlike everything above, this never runs automatically — same reasoning
as `--check-antigravity` (see below): two of the four `models` sources
have unverified auth behavior on a bare invocation, so this only ever
fires on explicit request.

| Provider | Source | Verified 2026-08-17 |
|---|---|---|
| Claude Code | Static list from `claude --help`'s own text — there's no `models` subcommand at all (`claude models --help` just reprints the general help) | local audit; printed/cached with a note that it's a static list, not a live query |
| Codex CLI | None — no `models` subcommand anywhere in `codex --help`; model choice is only ever a `-m <name>` flag per-invocation, nothing enumerable | local audit |
| Antigravity | `agy models` — confirmed to exist (`agy models --help` → "List available models") | local audit confirms the subcommand exists; its *auth* behavior on a bare invocation is unverified — same failure class as `agy -p /usage` (see `--check-antigravity` below), so it only ever runs from this explicit command |
| Grok Build | `grok models` — confirmed to exist (`grok --help` → "List available models and exit") | local audit confirms the subcommand exists; auth behavior likewise unverified |

Output parsing for `agy`/`grok` (`sai/providers/base.py`'s
`parse_model_lines`) is defensive on purpose (strip each line, drop blanks
and anything that reads as a header/decoration) — the real output shape has
never actually been captured, since running either command risked the same
OAuth-popup class of problem as the quota probes.

Results are cached in `~/.selectorai/cache.json` for 7 days and shown as a
one-line `Models: ...` in the picker's detail panel, plain `status`, and the
plain fallback menu (`sai/ui/plain.py`, used with no tty or no Textual) —
that display is read-only and never triggers a fetch; run `models` again
to refresh it.

## State files (`~/.selectorai/`)

- `launch.log` — every launch made through this script (timestamp, provider,
  mode — `auto`/`yolo`, with `+continue` appended when resumed). Informational
  only, not read by the script itself.
- `codex.ratelimited.msg` / `codex.ratelimited.until` — set when a
  script-launched Codex run fails with a "usage limit" error. `.msg` holds
  Codex's raw message (e.g. `Sep 14th, 2026 10:37 AM`), `.until` holds that
  same date parsed to a Unix timestamp (when parseable). Auto-clears once
  the date passes, or immediately on the next successful Codex run.
- `background` — the tmux persistence toggle (see below). Absent = on
  (the default once tmux is installed); contains `0` = off.
- `venv/` — the isolated Textual virtualenv (see "Interactive picker" above).
- `lang`, `theme`, `check_antigravity`, `cache.json` — see their respective
  sections above.

## "Last used" — solves the original problem

The old version of this idea only updated when *it* launched the AI. This
one reads each CLI's own local log instead, so it's accurate no matter how
you used it (this script, another terminal, an IDE):

- Claude: mtime of `~/.claude/history.jsonl`
- Codex: mtime of `~/.codex/history.jsonl`
- Antigravity: newest file mtime under `~/.gemini/antigravity-cli/conversations/`
- Grok: unconfirmed (see the status table above) — tries `~/.grok/history.jsonl`
  then newest file mtime under `~/.grok/sessions/`, by convention with the
  others rather than anything actually observed; "never" if neither exists

## Ordering — by last used, not by quota

Used to be sorted by remaining quota (most headroom first) — that "advisor"
is off for good. What's there now instead is simpler to predict: most
recently used first, then the next-most-recent, and so on — whatever you
touched last is always at the top. Providers you've never used (or that
tie some other way) keep `providers.ORDER`'s own order (`sai/providers/__init__.py`:
Claude, Codex, Antigravity, Grok) among themselves, since Python's sort is
stable. Applies to the picker and both fallback menus alike.

## Auto-mode flags, per provider

| Provider | Default (safer) | `--yolo` |
|---|---|---|
| Claude Code | `--permission-mode auto` — Claude's own rules-based classifier (allow/soft_deny/hard_deny, see `claude auto-mode --help`) decides what to auto-approve, real permission checks stay in effect for the rest | `--dangerously-skip-permissions` — full bypass, no classifier involved |
| Codex CLI | `--ask-for-approval never --sandbox workspace-write` (no prompts, but confined to the workspace) | `--dangerously-bypass-approvals-and-sandbox` — no sandbox at all, only meant for already-isolated environments |
| Antigravity | `--dangerously-skip-permissions` (identical flag name to Claude — same underlying CLI framework; unlike Claude, `agy`'s `--mode` only exposes `accept-edits`/`plan`, no equivalent classifier-based `auto`) | same, no separate mode |
| Grok Build | `--permission-mode auto` — confirmed via `grok --help`, the exact same enum as Claude's (`default`/`acceptEdits`/`auto`/`dontAsk`/`bypassPermissions`/`plan`) | `--permission-mode bypassPermissions` — same flag, the full-bypass enum value instead of a separate dangerous flag |

These are the fixed "preset" — the same flags fire on every launch, so behavior
stays predictable. `--yolo`/`--continue` only toggle within that preset; they
don't change its shape or add prompts.

## Resuming (`--continue` / `-c`)

All four CLIs can pick up the most recent session instead of starting fresh
— confirmed directly against each `--help` (`agy`/`grok` not logged in yet
on the machine this was built on, so their behavior is taken from `--help`
text, not a live run):

| Provider | Silent resume (what `-c` wires up) | Manual picker (browse, not wired into the script) |
|---|---|---|
| Claude Code | `-c, --continue` — most recent conversation *in the current directory* | `claude -r` / `--resume [id]` — interactive picker or search |
| Codex CLI | `codex resume --last` — a subcommand, not a flag, so `-c` reroutes the whole invocation through it | `codex resume` (no `--last`); add `--all` to include other working directories |
| Antigravity | `-c, --continue` — same shape as Claude | `agy --conversation <id>` — resume a specific past conversation by ID |
| Grok Build | `-c, --continue` — "most recent session for the current working directory", confirmed via `grok --help`, identical wording to Claude's | `-r, --resume [id_or_title]` — interactive picker, or match by session title (case-insensitive) |

`./selectorai.py --continue` (or `-c`) passes this straight through for
whichever provider gets chosen/launched. It resumes silently (no picker) —
once inside, the full prior conversation is right there, which covers "what
was I doing" without needing a separate preview step. For actually *browsing*
past sessions before picking one, run the manual-picker command for that
provider directly (not wrapped by this script, since it's interactive and
provider-specific).

## Background sessions (tmux) — reattach after an SSH drop

> **live-unverified**: tmux is not installed on the machine this feature
> was built on (no sudo either), so everything below is built from
> `tmux(1)`'s documented conventions plus the prior-art repos in
> [`docs/PRIOR_ART.md`](PRIOR_ART.md)'s tmux section (claude-squad/ccmanager's
> "one session, one keypress to attach" shape; the plain
> `tmux attach || tmux new` idiom; tmux-resurrect's `capture-pane -p`
> preview trick), not confirmed against a real tmux session yet. See
> `sai/session.py`'s module docstring for the same caveat in code.

When `tmux` is installed, every launch runs inside one shared, detached
tmux session (`selectorai`, one window per launched provider) instead of
directly in your terminal — so an SSH drop, a closed laptop lid, or a
`disown`'d terminal doesn't kill the CLI mid-task. On for real if it's
still running when you next open the picker, it offers reattaching first,
ahead of every provider option, along with a peek at the last few lines of
output (`tmux capture-pane`) so you can tell what it was doing before you
reconnect.

```bash
./selectorai.py background        # show current on/off state
./selectorai.py background on     # persist: wrap launches in tmux (the default once tmux is installed)
./selectorai.py background off    # persist: launch directly, no tmux wrapping
```

Default is **on** (absent `~/.selectorai/background` file) whenever `tmux`
is actually on `PATH` — the opposite default from `check-antigravity`,
since surviving a dropped connection is this feature's whole reason to
exist rather than something to opt into. No tmux on `PATH` (or already
running inside a tmux client — no session nesting) means every launch
behaves exactly as it did before this feature existed, no wrapping at all.

## Logging in (`auth`) — one flag, every provider, clean URL every time

```bash
./selectorai.py auth                # log into every installed provider, one after another
./selectorai.py auth antigravity     # just one
./selectorai.py auth claude codex    # a subset
./selectorai.sh auth                 # same, bash version
```

Each provider's real login entry point, verified against its own `--help`
(not guessed):

| Provider | Command this runs |
|---|---|
| Claude Code | `claude auth login` |
| Codex CLI | `codex login --device-auth` — explicitly requests the URL+code flow instead of letting it default to auto-opening a local browser, so it works the same whether you're local or remote |
| Antigravity | bare `agy` — it has no separate login subcommand; it auto-detects there's no session and runs its own local-browser-or-URL flow |
| Grok Build | `grok login --device-auth` — same flag, same phone-friendly reasoning as Codex's |

All four get wrapped the same way, which is the actual point of this
command — this is the generalized fix for the
[Error 400 URL-corruption bug](#known-bug-error-400-invalid_request-on-that-url)
below, applied everywhere a provider might print a long auth URL, not just
Antigravity. Note it deliberately does **not** touch `stty`/terminal width
anymore — an earlier version did, to try to stop the wrap from happening at
all, but that mutates shared pty state a foreground TUI reads at startup; if
that TUI is then running full-screen in raw mode there's no way to hand
control back to undo it, and it's confirmed to get stuck (a live Claude Code
session box-drawing itself across a corrupted-huge column count) — **the
`stty` incident**, referenced elsewhere in this file and in
[`docs/ARCHITECTURE.md`](ARCHITECTURE.md) rule 2. Steps 1–2 below don't
need the terminal's actual width to be right in the first place, so the
mutation was never load-bearing:

1. Runs the real login command through `tee` into a temp log file — you
   still see everything live and can still type into it normally (a
   device-code prompt needs your input), but the raw bytes also land in a
   file untouched by the terminal's own rendering.
2. Scans that file for a block starting at `https://` (or `http://`) up to
   the next blank line, and strips every whitespace character inside it — a
   real URL never contains a literal space, so this safely undoes any
   line-wrap that snuck in regardless of *how* it got wrapped. Prints the
   reconstructed single-line URL at the end, separate from the noisier live
   output above it, so it's easy to find and copy correctly — paste it into
   a browser on **any device** (the whole reason this matters: phone, another
   PC, doesn't need to be the machine you're running this on).
3. Where the provider has one, also runs its own login-status check
   (`claude auth status` / `codex login status`) right after, so you get
   immediate confirmation instead of guessing whether it worked.

Nothing here runs automatically or as a side effect of `status`/the menu —
same principle as `--check-antigravity`: auth flows only fire when you
explicitly ask for them with `auth`.

## Used % vs. left % — always shown together

Earlier versions were inconsistent about this: the detailed status block
showed both `X% used` and `Y% left` per row, but the compact recommendation
line in the menu only showed `Y% left` alone. Now every place that prints a
quota number prints both, explicitly labeled (`"80% left / 20% used (...)"`),
so there's no spot where a bare `%` could be misread as the opposite of what
it means. Internally there's one canonical field, `pct_used`; `left` is
always derived from it (`100 - pct_used`), never stored separately.

## Install methods (all verified, no sudo required)

All four install into the user's home directory, not system paths:

- **Claude Code**: `curl -fsSL https://claude.ai/install.sh | bash` → native binary in `~/.local/bin`, self-updates (`claude update`, confirmed via `claude doctor` → `Auto-updates: enabled`).
- **Codex CLI**: `curl -fsSL https://chatgpt.com/codex/install.sh | sh` → standalone binary in `~/.codex/packages/standalone`, symlinked from `~/.local/bin`. This replaced the old `npm install -g @openai/codex` default (still works, but requires Node and, in this setup, was originally installed system-wide under `/usr/lib` — needed `sudo npm uninstall -g @openai/codex` to remove once migrated).
- **Antigravity**: `curl -fsSL https://antigravity.google/cli/install.sh | bash` → binary at `~/.local/bin/agy`, PATH added to `~/.profile`.
- **Grok Build**: `curl -fsSL https://x.ai/cli/install.sh | bash` → binary at `~/.grok/bin/grok` (also symlinks an `agent` alias), symlinked from `~/.local/bin/grok`, PATH added to `~/.bashrc`. Confirmed live: `Grok 1.0.4 (linux-x86_64)` installed cleanly, no sudo, no Node.

`./selectorai.py install` runs the right one automatically depending on
whether the binary already exists (install vs. update).

## Antigravity's live usage check is opt-in (`--check-antigravity`)

`agy -p "/usage"` used to run automatically on every `status`/menu call.
Confirmed root cause, straight from `~/.gemini/antigravity-cli/log/*.log`
after this popped a real Google login window mid-session — **the
OAuth-popup incident**, the reason behind
[`docs/ARCHITECTURE.md`](ARCHITECTURE.md) rule 1:

```
Print mode: not authenticated, trying silent auth
Print mode: silent auth failed
Print mode: triggering interactive OAuth
consumerOAuth: starting OAuth flow
```

While Antigravity isn't logged in, *any* invocation in print mode — including
a harmless `-p "/usage"` status probe — falls through to a real interactive
OAuth flow and opens a browser window. Both scripts now skip this call by
default and just report "not checked". Pass `--check-antigravity` once
you've logged into `agy` yourself (plain `agy`, interactively, once) to
enable the live probe again:

```bash
./selectorai.py status --check-antigravity
./selectorai.sh status --check-antigravity   # (add --check-antigravity anywhere in the args)
```

Typing that flag every single run gets old once you're actually logged in and
it's working — `check-antigravity on` persists the setting so it's just on,
same idea as `lang`/`theme`:

```bash
./selectorai.py check-antigravity        # show current on/off state
./selectorai.py check-antigravity on     # persist: probe by default from now on
./selectorai.py check-antigravity off    # persist: back to opt-in-only (the default)
```

Saved to `~/.selectorai/check_antigravity` (present = on). The one-off
`--check-antigravity` flag still works on top of this for a single run
either way, without changing the persisted setting.

**Even after logging in, this can still happen unpredictably** — worth
knowing before flipping it to `on` persistently. Confirmed
live: `agy -p "/usage"` returned real data once, then on the very next call
seconds later demanded a fresh interactive OAuth login again — no changes in
between. This tracks with upstream, known-open issues in the CLI itself:
[antigravity-cli#57](https://github.com/google-antigravity/antigravity-cli/issues/57)
("does not remember OAUTH login") and
[antigravity-cli#18](https://github.com/google-antigravity/antigravity-cli/issues/18)
("repeatedly prompts for login on WSL2, leaves stuck processes"). Both
scripts still protect you from a hang either way — the call is wrapped in a
10s timeout, so a re-auth prompt just times out and falls back to "no usage %
available" rather than blocking — but treat `--check-antigravity` as "might
pop a login prompt on any given run," not just the first one.

**Cache backoff to make that tolerable instead of constant.** With `on`
persisted, every picker launch used to mean another live `agy -p "/usage"`
attempt — so on a machine where the session keeps expiring, that's a fresh
popup risk *every single launch*, confirmed in practice. `sai/cache.py`
caches Antigravity's result (success *or* failure) for 30 minutes instead
of the usual 60 seconds other providers get (`_CACHE_TTL_OVERRIDES` in
`fetch_all_statuses`) — not for freshness, a weekly quota doesn't need
per-minute updates, but as a backoff: once a live attempt has happened
(popup or not), later launches within that half hour reuse the cached
result instead of trying again. Turning `--check-antigravity` itself on or
off still forces an immediate re-check regardless of this window (the
`was_skipped` logic already did that). Use `--refresh`/`-r` to force a
fresh attempt sooner than the 30 minutes if you know the session's good
again.

### Real confirmed `/usage` output format

Captured from an actually-authenticated account (previously this was an
unconfirmed guess copied from Claude's format, which never matched anything
— fixed now):

```
Gemini Models	Weekly Limit Remaining	62%	2026-08-22T23:58:13Z
Claude and GPT models	Weekly Limit Remaining	100%	2026-08-24T08:15:03Z
```

Tab-separated, one row per underlying model bucket (Antigravity apparently
routes through more than one provider's quota), reporting **% remaining**
(not "% used" like Claude/Codex — the parser converts: `pct_used = 100 -
remaining`), with an exact ISO 8601 UTC reset timestamp reformatted to local
time for display. The overall `pct_used` shown in the summary line is the
*most* constrained bucket (highest % used) — same "worst case wins"
convention as Claude's session-vs-weekly comparison.

## Grok's `--check-grok` — live, but via a tmux-driven TUI scrape, not a flag

An earlier version of this script concluded Grok had no usage check to gate
at all — confirmed at the time (Grok Build ~1.0.4) that `/usage`/`/cost`
were TUI-only per Grok's own shipped docs, headless mode didn't interpret
slash commands, and a free account's `/usage` inside the real TUI showed
nothing (no credit balance to check). That finding was real for that
version, but it's now **superseded**: re-verified live 2026-08-18 against
Grok Build 1.0.5 on the same free grok.com account, and the picture changed
in two ways.

1. **Headless mode now intercepts *some* slash commands.**
   `grok -p "/info" --output-format json` (alias `/status`, `/session-info`)
   returns real structured JSON instead of sending the literal text to the
   model — confirmed live:
   ```json
   {"text": "**Session ID:** ...\n**Model:** grok-4.6\n**Turn:** 0\n**Context:** 3994 / 500000 tokens (1%)", ...}
   ```
   `/usage`/`/cost` are still *not* intercepted headlessly, though — sent as
   a literal chat prompt, the model tries to research an answer instead
   ("I'll look up how `/usage` is handled here...") rather than the CLI
   returning real data. So headless mode grew a real command, just not the
   billing one.

2. **The actual quota data exists now, but only in a pager-only UI panel.**
   The same `/info` command, run for real inside the interactive TUI (not
   headless), opens a popup with three tabs — `Context usage`, `Usage
   limit`, `Session info` — and the middle one has exactly what was missing
   before:
   ```
   Weekly limit (Free)
   ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  0%
   Resets: August 21, 21:00
   ```
   Confirmed this is genuinely headless-inaccessible, not just unexplored:
   the same `-p "/info" --output-format json` call above never includes it
   — that JSON only ever carries session/context fields, regardless of
   which of `/info`'s three tabs a real interactive render would default
   to. The popup's other two tabs (`Context usage`/`Session info`) are
   reachable the same headless way `/info`'s default text already covers;
   `Usage limit` specifically has no non-interactive path at all.

So there's no flag or JSON field to poll — the only way to reach "Resets:
<date>" is to actually run the TUI and read the screen. `--check-grok` /
`check-grok on` (`sai.providers.grok.status()` → `_live_usage_limit()`)
does exactly that, opening a real `grok` session inside a **throwaway tmux
window** (session name `selectorai-grok-probe`, killed at the end either
way):

1. `tmux new-session -d` a plain `grok` invocation, poll `capture-pane -p`
   for the input prompt border (`│ ❯`) as the ready signal — observed
   between 1s (warm) and ~15-20s (cold/slow network) on this machine.
2. `send-keys "/info"` + `Enter`, wait ~2s for the popup to render.
3. `send-keys "Tab"` up to 3 times, checking the captured pane for "Weekly
   limit" after each — confirmed live that `/info` lands on "Session info"
   first and Tab cycles to "Context usage" then "Usage limit", but the code
   doesn't hardcode that order, just stops as soon as the text shows up.
4. Regex out the label ("Weekly limit (Free)" verbatim — a paid tier
   presumably reads "(Plus)"/"(Heavy)", never observed live so not assumed),
   the percentage, and the "Resets: ..." text.
5. `Escape` then `kill-session`, always, via `finally`.

This is a materially different risk profile than Antigravity's gate — no
OAuth-popup risk, since a free grok.com login doesn't re-prompt mid-session
the way Antigravity's flaky session handling does — but it IS slower (a
real TUI boot every time, not one subprocess call) and coupled to grok's
current popup layout in a way a flag or JSON endpoint wouldn't be, which is
why it's opt-in via the same `--check-*`/`check-* on` shape rather than
default-on. A failed probe (session never ready, or the Tab-cycle never
finds "Weekly limit") reports `kind: "no-usage-api"`, not `"auth-needed"` —
unlike Antigravity's empty-rows case (confirmed to specifically mean
sign-in-needed), a failed Grok probe just as easily means a slow tmux
session or a future popup-layout change, not a login problem.

**Also confirmed live, same account:** only `Grok 4.6` was available to
pick from — likely another free-tier restriction (newer/other models gated
behind a paid plan), not something specific to this machine's install.
Doesn't affect this script either way: `launch()` never passes
`-m/--model` for Grok, same as it doesn't pin a model for Claude, Codex, or
Antigravity — whichever model the account actually has access to is just
whatever `grok` defaults to on its own.

## Antigravity auth over SSH / remote console

Confirmed against the current antigravity.google/docs/cli/install page:

- **Local**: `agy` tries the OS keyring first (Keychain / Secret Service /
  Credential Manager); if there's no saved token it opens your local browser.
- **Remote/SSH**: it detects the SSH session, can't open a local browser, and
  instead prints an authorization URL to copy into a browser on *any other
  device* (your phone works). That browser shows a short alphanumeric code —
  paste that code back into the SSH terminal to finish.
- Not yet tested end-to-end over a real SSH session on the machine this was
  built on — the environment used to build this wasn't one, so
  `agy -p "/usage"` just hung trying (that's why its status check has a
  short 10s timeout instead of Claude's 20s, on top of now being opt-in —
  see `--check-antigravity` above).

### Known bug: "Error 400: invalid_request" on that URL

Open issue, no fix yet as of this writing:
[google-antigravity/antigravity-cli#315](https://github.com/google-antigravity/antigravity-cli/issues/315).
The printed OAuth URL is long enough that a narrow terminal (very common over
SSH, or just a narrow local window/tmux pane) soft-wraps it — and depending
on the terminal, copying that wrapped text inserts a real newline mid-URL.
When it lands mid-parameter, e.g. splitting `prompt=consent` into `prompt=con`
+ `sent`, Google's OAuth endpoint rejects it with exactly `Error 400:
invalid_request — Invalid parameter value for prompt: Invalid prompt: con
sent`. If you hit this, easiest first: use `./selectorai.py auth antigravity`
(or `.sh`) instead of bare `agy` — see "Logging in (`auth`)" above, it
reconstructs the clean URL for you without touching the terminal at all.
Manual alternatives if you want to avoid the script entirely:

- Try completing the URL step from a different browser/device than the one
  you first tried — several reports on Google's own dev forum say a fresh
  mobile-browser attempt got past it when desktop kept failing.
- Or skip OAuth entirely — see the Gemini API key method below, which never
  generates this URL at all.
- Resizing an actual terminal *window* wider also works, if that's easy on
  your setup. Avoid `stty cols <N>` as a manual fix, though — confirmed the
  hard way while building this (the `stty` incident, see "Logging in
  (`auth`)" above): it doesn't auto-revert, and if you later launch a
  full-screen TUI (`claude`, `codex`, `agy` themselves) in that same
  terminal before resetting it, that TUI reads the wrong width at startup
  and renders corrupted with no way to fix it short of `reset`/closing the
  tab. This is exactly why `auth`'s own implementation dropped `stty`
  entirely in favor of the tee+reconstruct approach above.

### Using a Gemini API key instead of account login

The cleanest workaround for the bug above, and also Google's documented
non-interactive/CI path — the CLI never establishes an account session, so
there's no OAuth URL to corrupt in the first place:

1. Create a key in Google AI Studio ("Get API key" → "Create API key").
2. Set `"modelProvider": "gemini"` in `~/.gemini/antigravity-cli/settings.json`.
3. `export GEMINI_API_KEY="..."` (add to `~/.bashrc`/`~/.zshrc` to persist).
4. Run `agy` — it skips the sign-in screen; the header shows "Gemini API key"
   instead of an account email.

Both steps are required — per the docs, setting only the env var with no
`modelProvider` in settings.json has no effect. `/logout` also has no effect
in this mode (there's no stored session to clear); to go back to normal
account login, remove `modelProvider` from settings.json and restart `agy`.

One consequence for this script: API-key mode is billed per-request through
AI Studio, not the account's session/weekly quota buckets — so once you're
on this path, `agy -p "/usage"` (behind `--check-antigravity`) likely won't
report a meaningful `% used` the way it does for an OAuth-logged-in account.
Not yet confirmed live either way.

## Known limitations

- Codex and Antigravity rate-limit/usage detection is reactive, not
  proactive — same fundamental limitation the earlier Claude-only version
  had, just narrowed down to the two CLIs that don't expose a live query.
- Antigravity's session persistence is flaky upstream (see
  antigravity-cli#57/#18 above) — `--check-antigravity` can trigger a fresh
  OAuth prompt on any given run even after a prior successful login, not
  just the first time. Nothing to fix on our end; the 10s timeout keeps it
  from hanging when it happens.
- `guia-ai-limites-instalacion.md` at the repo root is background material
  from an earlier chat summary (Russian, various unverified specifics —
  promo percentages, a referral link, "Grok Build" details). Nothing in it
  was taken as ground truth for this script without independently checking
  it first; treat it as inspiration, not documentation. It's excluded from
  the published repo (see `.gitignore`).

## Next / open items

- Test the SSH auth flow end-to-end.
- Test the tmux background-session feature end-to-end on a machine that
  actually has tmux (see "Background sessions" above — everything there is
  live-unverified).
