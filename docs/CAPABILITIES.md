# Provider capabilities audit: plugins, skills, MCP, subagents, updates, sessions

Research snapshot: **September 2026**. Scope: what each of selectorai's four
tracked CLIs (`claude`, `codex`, `agy`, `grok`) exposes for (1) listing and
disabling installed plugins/skills, (2) MCP servers, (3) subagents, (4) a
non-interactive version/update check, and (5) session listing/resume beyond
a blind `--continue`. This is the evidence behind a real, concrete problem:
an enabled skill/plugin costs context tokens on **every** session whether or
not it's ever invoked, and there was no map of which provider lets you see
or control that cost before this pass.

Same rule as [`docs/CANDIDATES.md`](CANDIDATES.md) and
[`docs/NOTES.md`](NOTES.md): every claim below is either **verified**
(confirmed against a real command's actual output or a real config file
read) or **unverified** (the `--help` text didn't confirm it, or running the
real command risked a side effect — auth popup, network mutation — so it
wasn't run). Per [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) rule 1, nothing
below was run if it risked triggering auth/OAuth or mutating installed
state; a command's output is only quoted here when it was actually
confirmed safe first (a `list`/`--check`/`--json`-style read, or a local
config file).

## Summary table

| Provider | List plugins (safe) | Disable a specific skill | MCP list (safe) | Version/update check (safe, read-only) | Session listing beyond blind resume |
|---|---|---|---|---|---|
| Claude Code | `claude plugin list` | `claude plugin disable <name>` — and `claude plugin details <name>` shows the real token cost | `claude mcp list` | `claude doctor` | not found (only `-c`/`-r`) |
| Codex CLI | `codex plugin list` — **unverified as safe**, help text says it hits remote marketplaces too | not found; `codex features enable/disable` is feature-flag level, not per-skill | `codex mcp list` | `~/.codex/version.json` (read-only file, already fresh) | `codex resume` (bare, no `--last`) opens a picker |
| Antigravity (`agy`) | `agy plugin list` | **not found** — 5 builtin skills have no discovered disable path at all | `agy mcp list` | **not found safe** — `agy update --help` doesn't confirm read-only | not found (only `--conversation <id>`) |
| Grok Build | `grok plugin list` — but only grok's own store, **not** the cross-vendor items `grok inspect --json` also loads | not found in grok's own skills, but ships a bundled `learn` skill described as retiring unused skills/plugins/MCP servers | `grok mcp list` | `grok update --check --json` — clean, confirmed safe | `grok sessions list` — full history with summaries, confirmed richest of the four |

## Per-provider detail

### Claude Code

- **Plugins**: `claude plugin list` (local, safe) → this account has
  `frontend-design@claude-plugins-official`, scope `user`, `✔ enabled`.
  Subcommands: `list [--json] [--available]`, `install`/`i`,
  `uninstall`/`remove`, `enable <plugin>`, `disable [plugin] [-a|--all] [-s
  user|project|local]`, `marketplace list/add/remove/update`.
- **Real token cost, confirmed live** — `claude plugin details
  frontend-design`:
  ```
  frontend-design — Skills(1) Agents(0) Hooks(0) MCP(0) LSP(0)
  Always-on: ~78 tok (added to every session regardless of use)
  Per-component: frontend-design → always-on ~80 tok / on-invoke ~2.7k tok
  ```
  This is the exact case the project's user flagged (an unused
  `frontend-design` skill still costing context) — now with a real number
  attached instead of a hunch.
- **Where the toggle lives**: `~/.claude/settings.json` →
  `"enabledPlugins": {"frontend-design@claude-plugins-official": true}`.
  Persisted config, not a per-invocation flag. `claude plugin
  init|new <name>` scaffolds a new skill under `~/.claude/skills/<name>/`,
  auto-loaded next session as `<name>@skills-dir`.
- **MCP**: `claude mcp list` (local, safe) → "No MCP servers configured" on
  this account. Full subcommand set: `add/add-json/
  add-from-claude-desktop/get/list/login/logout/remove/
  reset-project-choices/serve`.
- **Subagents**: `claude agents [--json] [--agent <a>] [--mcp-config ...]
  [--plugin-dir <path>] [--permission-mode ...]
  [--dangerously-skip-permissions]` — this is a **background-agent
  session dispatcher**, not a listing of custom subagent definitions.
  Custom agents are a plugin/skill-dir concept, not a separate registry.
- **Version/update**: `claude doctor` (local, no login) reports the running
  version (`2.1.272`), channel, and the last auto-update result
  (`success → 2.1.272, 2026-09-15`).

### Codex CLI

- **Plugins**: `codex plugin {add,list,marketplace,remove}`. `codex plugin
  list --help` text explicitly says it lists what's "available from
  configured **and remote** marketplaces" — **not confirmed safe to run
  bare** (likely a network call by default); `--json`/`--available` exist
  for scripting once that's confirmed. Locally, two plugins are already
  cached: `~/.codex/plugins/cache/openai-curated-remote/{deep-research-work,
  plugin-management}`.
- **Features — the real "on/off" switch Codex has**: `codex features list`
  runs entirely local (reads `~/.codex/config.toml`, no network),
  printing every flag with its `stage` (`stable`/`under development`/
  `removed`) and current `true`/`false` state — e.g. `image_generation
  stable true`, `browser_use stable true`, `hooks stable true`. `codex
  features enable|disable <name>` (or `--enable`/`--disable <FEATURE>` on
  any subcommand) writes back to `config.toml`. This is coarser than a
  per-skill toggle (it's a whole capability, not one skill) but it is a
  confirmed, safe, local mechanism.
- **Skills**: **no `codex skill*` subcommand exists at all** (confirmed
  absent from the full `--help`). Skills are plain directories under
  `~/.codex/skills/.system/*` — `imagegen`, `skill-creator`,
  `skill-installer`, `plugin-creator`, `review-agent`, `openai-docs` —
  each with a `SKILL.md` (same frontmatter shape as Claude Code's:
  `name` + `description`) plus `agents/`/`scripts`/`references`/`assets`.
  Confirmed live: `imagegen` is exactly the skill that tried to run
  during this session's car-drawing test and fell back to a CLI drawing
  tool for lack of `OPENAI_API_KEY`/credits (see
  [`docs/NOTES.md`](NOTES.md#cross-provider-cooperation-test--non-interactive-drawing-task-per-provider)).
  **No enable/disable mechanism found** for an individual skill — unverified
  whether one exists via an undiscovered flag, or whether the only lever
  is deleting the directory.
- **MCP**: `codex mcp {list,get,add,remove,login,logout}`. `codex mcp list`
  confirmed local/safe → "No MCP servers configured yet" here.
- **Subagents**: `codex agents` is "Browse all agent sessions on the shared
  local app-server daemon" — a browser of **past sessions**, not
  definable custom subagents like Claude Code's.
- **Version/update, confirmed safe and already fresh**: `~/.codex/
  version.json` = `{"latest_version":"0.154.0","last_checked_at":"...",
  "dismissed_version":null}`, maintained by Codex itself in the
  background. `codex --version` → `codex-cli 0.154.0` — installed already
  matches latest, read entirely from a local file, no network call
  needed for the check itself.

### Antigravity (`agy`)

- **Plugins**: `agy plugin {list,import,install,uninstall,enable,disable,
  validate,link}`. `agy plugin list` confirmed safe (no auth triggered) →
  `"No imported plugins."` — but this only covers **user-imported**
  plugins, not the builtin skills below.
- **MCP**: `agy mcp {add,remove,list,enable,disable}`. `agy mcp list`
  confirmed safe → `"No MCP servers configured."`
- **Agents**: `agy agent`/`agents` ("List available agents") confirmed
  safe, returned empty (exit 0, no auth) — no custom agents configured.
  No separate subcommand to *define* one; `--agent <NAME>` just selects
  an existing one for a session.
- **Version/update — real gap**: `agy update --help` prints a broken/
  minimal help ("Usage of update:", exit 2) with no documented flags, and
  gives no indication whether it's read-only or mutates the installed
  binary. **Not run** — unlike Claude/Codex's confirmed-safe checks, this
  one needs confirming in a disposable environment before it's ever
  wired into anything automatic.
- **The actual finding that matters here: 5 undisableable builtin
  skills.** `~/.gemini/antigravity-cli/builtin/skills/` (read-only
  filesystem check) has real `SKILL.md` files for `antigravity_guide`,
  `generative_ui`, `migrate-workflows`, `permissioned-github`, and
  `agy-customizations`. These don't show up in `agy plugin list` at all
  (which reported zero, with all five present) — and a full audit of
  `~/.gemini/antigravity-cli/settings.json` for any `skill`/`plugin`/
  `mcp`/`agent` key found nothing relevant (only a large
  `permissions.allow` allowlist from past sessions, unrelated). **No
  confirmed way to disable an individual Antigravity builtin skill** —
  this is Antigravity's version of the "frontend-design" problem, except
  without Claude Code's fix.

### Grok Build

- **The big one: `grok inspect --json`** (local, safe, no auth) dumps the
  full manifest of everything a session in this directory actually
  loads. Confirmed live: it lists **26 bundled skills** of grok's own
  (`~/.grok/bundled/skills/*/SKILL.md`) **plus cross-vendor items grok
  detects and loads via an `externalCompat` layer** — 13 cells total:
  `cursor` and `claude` each get full coverage across `skills/rules/
  agents/mcps/hooks/sessions` (6 surfaces apiece, all `enabled: true` by
  default), but `codex` gets only a single `sessions` cell (`enabled:
  true`) — no skills/rules/agents/mcps/hooks entries for codex at all.
  Claude
  Code's `frontend-design` plugin showed up **inside grok's own
  manifest** — `source.type: "plugin"`, `vendor: "claude"`, `enabled:
  true`, pointed at `~/.claude/plugins/marketplaces/
  claude-plugins-official/...`. **Practical implication**: in a repo
  where Claude Code's `frontend-design` is enabled, a Grok session in
  that same repo inherits it too — so disabling it at the Claude Code
  layer (`claude plugin disable frontend-design`) likely relieves the
  cost for *both* CLIs, not just Claude's own sessions. `inspect --json`
  also lists builtin `agents` (`general-purpose`, `explore`, `plan` — the
  same names Claude Code uses) and installed `plugins`/`marketplaces`/
  `mcpServers`/`lspServers`.
- **Plugins (grok's own store only)**: `grok plugin
  {list,install,uninstall,update,enable,disable,details,validate,tag,
  marketplace}`. `grok plugin list` confirmed safe → `"No plugins
  installed"` — the Claude plugin visible via `inspect --json` doesn't
  count as "installed" here; it's detected via compat, not grok's own
  store.
- **MCP**: `grok mcp {list,add,remove,enable,disable,doctor}`. `grok mcp
  list` confirmed safe → `"No MCP servers configured"`.
- **Subagents**: no listing subcommand beyond what `inspect --json`
  already shows (3 builtin: `general-purpose`/`explore`/`plan`).
  `--agent`/`--agents`/`--no-subagents` remain invocation-only flags, not
  a management surface.
- **Version/update, confirmed safe**: `grok update --check --json` →
  ```json
  {"currentVersion":"1.0.30","latestVersion":"1.0.30","updateAvailable":false,"channel":"stable"}
  ```
  Clean, scriptable, no login needed. `grok version --json` gives just
  the current version.
- **Config**: `~/.grok/config.toml` (read) has `[marketplace.sources]`
  (xAI's official marketplace) and already persists `permission_mode =
  "always-approve"` under `[ui]` — confirming the bypass state can live
  in config, not just be passed as a launch flag (no impact on
  `sai/providers/grok.py` today, since `launch()` always passes an
  explicit `--permission-mode` regardless of what's saved — just worth
  knowing the persisted default exists).
- **Sessions — richest of the four**: `grok sessions list` (confirmed
  safe, local) prints real historical sessions with summaries — a
  genuine session browser, not just a blind `-c`.
- **Directly relevant, noted but not evaluated here**: grok ships bundled
  skills named `resume-claude`/`resume-codex`/`resume-cursor` (resuming
  *other* CLIs' sessions from inside grok) and a skill called `learn`,
  described in its own `SKILL.md` as retiring skills, plugins, or MCP
  servers that are never used. Both are exactly the shape of feature
  this project's roadmap is now considering. `learn` got a real trial run
  (2026-09-15) — its map phase completed cleanly, but the reduce phase
  hit the account's own rate limit and the workflow self-paused before
  reaching a synthesized report; full writeup, including a real usage-log
  finding recovered from the partial run, in
  [`docs/NOTES.md`](NOTES.md#groks-own-learn-skill--real-trial-run-killed-by-the-accounts-own-rate-limit).

## Cross-cutting findings

1. **Grok already ships two of the four things being considered here**,
   as grok's own built-in behavior rather than anything selectorai needs
   to build: a clean version-check (`grok update --check --json`) and a
   skill literally aimed at retiring unused skills/plugins/MCP servers
   (`learn`). A real trial of `learn` got killed by the account's own
   rate limit mid-run (see the NOTES.md link above) before reaching a
   synthesized report — the map phase itself worked and independently
   confirmed a real, separate finding (8 of 11 real sessions on this
   machine were the user hunting for a non-interactive Grok quota check),
   but the retire-unused-skills verdict `learn` itself would have reached
   is still unknown pending a retry.
2. **The "always-on context cost" problem isn't confined to Claude
   Code** — Grok's cross-vendor compat layer means Claude's enabled
   plugins get pulled into Grok's context too, in the same repo. The one
   lever that's actually confirmed to reduce cost across *both* CLIs is
   disabling the plugin at Claude Code's own layer
   (`claude plugin disable`), not something split across four separate
   provider-specific mechanisms.
3. **Antigravity is the one real gap**: 5 builtin skills with no
   discovered way to disable any of them, and no confirmed-safe
   update-check either. Both read as genuine upstream limitations for
   now, not something selectorai's code can route around.
4. **Read-only version/update checks are viable for 3 of 4**: Claude
   (`claude doctor`), Codex (`~/.codex/version.json`), Grok (`grok update
   --check --json`) are all confirmed local/safe. Antigravity would need
   its own opt-in gate (same "risk it might mutate/pop a prompt" shape
   already used for `--check-antigravity`'s quota probe) or stay
   excluded until confirmed.
5. **Session listing beyond blind resume** varies a lot: Grok
   (`sessions list`) and Codex (bare `resume` opens a picker) both expose
   something to browse; Claude and Antigravity currently only expose
   blind resume by ID/most-recent, no listing subcommand found in this
   pass.

## Implications for selectorai's roadmap (not yet built)

- A `list_plugins()` / `check_update()` pair could extend the existing
  provider contract ([`docs/ARCHITECTURE.md`](ARCHITECTURE.md)) as two new
  *optional* functions, returning `None` when unsafe/unverified — the same
  shape `list_models()` already uses for exactly this reason (see
  Antigravity/Grok's `list_models()` caution comments in
  `sai/providers/*.py`).
- Per-provider readiness for that today: Claude — both safe. Codex —
  `check_update` safe (pure file read), `list_plugins` needs a
  confirmed-local invocation first. Antigravity — `list_plugins` safe,
  `check_update` unconfirmed/skip. Grok — both safe, plus richer session
  data available for free via `inspect --json`/`sessions list`.
- The "warn about always-on context cost" idea is only actionable with a
  real number on Claude Code today (`claude plugin details`). The other
  three either don't expose a cost figure for their own skills (Codex,
  Grok) or don't expose a disable path at all (Antigravity) — so a
  cross-provider version of this feature would currently be "Claude-code
  accurate, best-effort elsewhere."
- Before designing a selectorai-native "retire unused skill" feature,
  worth *finishing* a trial of Grok's own bundled `learn` skill — the
  first attempt only got through the map phase before a rate limit
  killed the reduce step (see the NOTES.md link above); it may still do
  this well enough that selectorai's job is just surfacing it, not
  reimplementing it, but that isn't confirmed yet either way.
