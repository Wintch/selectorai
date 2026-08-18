# Prior art

Research snapshot: **August 2026**. Survey of adjacent/competing projects in
three sub-areas: account/quota-switchers, tmux/session-persistence managers,
and local-model integration (the last is its own section, appended below).

Per this project's documentation rule: **confidence is marked per project**
(`verified-repo`/`verified-docs` > `multiple-sources` > `single-source`), and
nothing unmarked should be treated as more solid than a single blog post.
Check the linked source before relying on a specific claim.

---

## The landscape, in three niches

By August 2026 the space has filled in and split into three recognizable
categories. selectorai sits closest to the first but borrows ideas from all
three.

### 1. Account/profile switchers

Solve "I have multiple accounts per CLI and want to swap credentials fast."

- **aisw (AI Switcher)** — [github.com/burakdede/aisw](https://github.com/burakdede/aisw) (`multiple-sources`)
  Profile manager for switching accounts across Claude Code, Codex CLI,
  Gemini CLI, Antigravity CLI. Bundles per-tool profiles into named
  cross-tool "contexts," stores credentials in the OS keyring (Keychain /
  Secret Service / Credential Manager) with a 0600-file fallback, snapshots
  before every switch for rollback on failure, and has a "guard mode" that
  binds a repo/workspace to an expected account and blocks the wrong one.
  Deliberately no daemon/proxy — writes directly into each tool's native
  config file.
- **CC Switch** (farion1231/cc-switch, +cc-switch-cli, +cc-switch-web) —
  [github.com/farion1231/cc-switch](https://github.com/farion1231/cc-switch) (`multiple-sources`)
  Desktop/TUI/web "all-in-one assistant" spanning Claude Code, Codex, Gemini
  CLI, OpenCode, OpenClaw, Grok Build, Hermes Agent: config switching, MCP
  server management, system-prompt/Skills management, and a local proxy for
  OpenAI-compatible providers behind Claude/Codex. The CLI variant ships
  both an interactive TUI and scriptable subcommands from one binary. Also
  does 30-day per-app/per-model usage tracking, per-provider latency
  checks, and rotating config backups + WebDAV sync.

### 2. Quota/usage trackers

Solve "show me remaining quota/health" — the closest functional overlap
with selectorai's own status display.

- **ccusage** — [github.com/ryoppippi/ccusage](https://github.com/ryoppippi/ccusage) (`multiple-sources`)
  Analyzes local JSONL usage logs; per its current README now spans 16
  agent CLIs (Claude Code, Codex, OpenCode, Amp, Droid, Codebuff, Hermes
  Agent, pi-agent, Goose, OpenClaw, Kilo, Kimi, Qwen, Copilot CLI, Gemini
  CLI, Grok Build CLI) — essentially selectorai's exact tool set already
  covered by one project. Notable: `ccusage statusline` (compact
  status-bar snippet), "5-Hour Blocks" reporting that groups usage into
  Claude's real billing windows instead of generic day/month buckets,
  responsive terminal tables, and a shared-core-plus-per-provider-adapter
  architecture with an MCP server exposing its own data to other agents.
- **Quotio** — [github.com/nguyenphutrong/quotio](https://github.com/nguyenphutrong/quotio) (`multiple-sources`)
  Native macOS menu-bar app unifying Claude, OpenAI, Gemini, Qwen, Vertex
  AI, Antigravity behind a local proxy (CLIProxyAPI), with real-time
  per-account quota dashboards and two named failover strategies (Round
  Robin vs. Fill First). Has a passive quota-check mode that works without
  running the proxy — "just tell me my quotas" as a first-class,
  standalone use case.
- **Claude-Code-Usage-Monitor** — [github.com/Maciek-roboblog/Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) (`multiple-sources`)
  Local, privacy-first Rich-terminal monitor with burn-rate + P90
  percentile forecasting ("exhausts in ~47 min"), explicit
  official-data-vs-local-estimate confidence labeling, WCAG-aware
  theming, and reset-aware pacing math.
- **caut** (coding_agent_usage_tracker) — [github.com/Dicklesworthstone/coding_agent_usage_tracker](https://github.com/Dicklesworthstone/coding_agent_usage_tracker) (`multiple-sources`)
  Consolidates quota/rate-limit/cost across Codex, Claude, Gemini, Cursor,
  Copilot via pluggable per-provider data-source strategies (CLI wrapper,
  cookie, OAuth token, direct API, local log scan) with graceful
  degradation. First-class machine-readable output: `--json` /
  `--format md` under a *versioned* schema (`caut.v1`) explicitly designed
  for AI-agent consumption. Explicit fail-safe philosophy: missing
  creds/timeouts degrade to warnings, never a crash.
- **Hermes Agent — Credential Pools** (feature, not standalone) —
  [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/docs/user-guide/features/credential-pools) (`multiple-sources`)
  Same-provider multi-key rotation with four named strategies (fill_first,
  round_robin, least_used, random) and error-type-differentiated handling:
  429 retries once before rotating, 402 rotates immediately with a
  1-hour cooldown, 401 attempts token refresh before rotating. Same-provider
  key pool is tried before cross-provider fallback.
- **claude-code-router (CCR)** — [github.com/musistudio/claude-code-router](https://github.com/musistudio/claude-code-router) (`multiple-sources`)
  Local HTTP proxy (localhost:3456) every CLI points at instead of talking
  to providers directly; routing rules, credential pools, ordered
  fallback models, and cost-optimization routing (cheap subtasks to local
  models) managed centrally via a desktop UI.

### 3. Parallel-agent orchestrators (adjacent, different problem)

- **AgentGrid**, **Codeman**, **TokenTelemetry** — orchestrate/observe
  *multiple concurrently running* agents rather than switching between
  them serially. AgentGrid is a cost-tracking task-assignment dashboard;
  Codeman streams persistent tmux sessions to a browser; TokenTelemetry is
  a 100%-local token/cost/tool-call observability dashboard. (`multiple-sources`)
  This is a genuinely different niche — parallel orchestration, not
  serial pick-and-launch — and is called out explicitly below under "not
  adopted" for scoping reasons, not because the ideas are bad.

### Session-persistence / tmux managers (adjacent, third axis)

A separate research pass covered the "reattach to a running agent after
SSH reconnect" problem specifically, since it's directly relevant to
selectorai's SSH-session-start launch model:

- **claude-squad**, **ccmanager**, **agent-deck** — all converge on the
  same recipe: one TUI, per-managed-CLI tmux session (or git worktree),
  status derived from output/state parsing, one keypress to attach.
  (`multiple-sources`/`single-source`)
- **tmux-claude-session-manager** (craftzdog) —
  [github.com/craftzdog/tmux-claude-session-manager](https://github.com/craftzdog/tmux-claude-session-manager) (`multiple-sources`)
  Reads Claude Code's *own* published session-state files (no scraping),
  prefixes managed tmux sessions (`claude-*`) so a picker can cleanly
  enumerate "sessions we manage," and jumps to the originating window
  before popping the session, not just a blind attach.
- **zellij-claude** — [github.com/UrosNikolic/zellij-claude](https://github.com/UrosNikolic/zellij-claude) (`multiple-sources`)
  Cross-references on-disk status files against live PIDs/panes to avoid
  showing stale sessions as reattachable — combining two detection
  strategies rather than trusting either alone.
- **Claude Code's own `claude agents` / `/background`** —
  [code.claude.com/docs/en/agent-view](https://code.claude.com/docs/en/agent-view) (`verified-repo`)
  The gold-standard reference design for this whole niche: a per-user
  supervisor daemon independent of any terminal (`~/.claude/daemon/`),
  state on disk (`roster.json`, `jobs/<id>/state.json`), three-tier
  session identity (auto name / short ID / durable custom name), a
  dashboard grouped by state with "needs input" sorted first, and a
  "peek" interaction (Space) that shows recent output/the blocking
  question and lets you reply *without* fully attaching. Codex's
  `/detach` + `codex resume` and Grok Build's `grok dashboard` follow the
  same shape (background daemon or transcript replay, needs-input-first
  sorting).
- **tmux-resurrect / tmux-continuum** —
  [github.com/tmux-plugins/tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect) (`multiple-sources`)
  Solves a different failure mode (full host reboot survival, not just
  client detach) — not selectorai's target scenario, but its "capture
  pane contents so restore isn't blank" trick is directly reusable via
  plain `tmux capture-pane -p`.
- **Plain `ssh host -t 'tmux attach || tmux new -s agents'` idiom** —
  [implicator.ai writeup](https://www.implicator.ai/tmux-keeps-ai-coding-agents-running-for-days-after-you-disconnect/) (`multiple-sources`)
  The tool-free baseline: one deterministic tmux session name plus
  `tmux has-session` liveness detection is sufficient for the common
  case — no daemon required.

---

## What selectorai does differently

None of the projects above combine **install + health/quota display +
rotation-aware launch** specifically as a lightweight, dependency-light
hook that runs at the start of an SSH session. Concretely:

- The account switchers (aisw, CC Switch) manage credentials but don't
  install the CLIs or show live health/quota at session start.
- The quota trackers (ccusage, Quotio, caut, Claude-Code-Usage-Monitor)
  show usage but don't install, launch, or manage session persistence.
- The proxy/router tools (CCR, Hermes) solve automatic failover but
  require running a persistent local proxy process — a heavier
  architecture than selectorai's direct config-file / env-var approach.
- The tmux managers (claude-squad, ccmanager, Agent of Empires) solve
  parallel multi-session orchestration — a different problem from
  selectorai's serial "which CLI, which account, launch it" flow.
- selectorai is stdlib-only Python (+ an isolated-venv Textual picker)
  with a dependency-free bash fallback, meant to be dropped into a
  `.bashrc`/SSH `ForceCommand` with near-zero footprint — none of the
  above target that install profile.

---

## Ideas adopted

- **Versioned, machine-readable status output** (from caut's `caut.v1`
  schema idea) — selectorai's `status()` provider contract already
  returns a stable dict shape (`pct_used`, `rows`, `note`, `kind`);
  documented in `docs/ARCHITECTURE.md` as a contract, not an incidental
  return value.
- **Per-provider data-source strategy with graceful degradation** (from
  caut and Ollama/local-model detection) — selectorai's `health.py`
  classifies online/warning/offline and never crashes the whole status
  display when one provider's probe fails or times out.
- **Never probe speculatively; live checks are opt-in** (independently
  arrived at, reinforced by seeing the same caution in caut's "fail-safe
  philosophy" and Olla's adaptive backoff) — codified as a hard rule in
  `ARCHITECTURE.md`: unauthenticated probes can pop OAuth browser windows,
  so live checks are behind explicit flags with long-backoff caches.
- **Billing-window-aware quota display over generic day/month buckets**
  (from ccusage's "5-Hour Blocks") — worth modeling selectorai's reset
  countdowns around each provider's actual reset semantics rather than a
  generic calendar bucket, where that data is knowable.
- **Cheap liveness probe before a heavier list call** (from the Ollama
  `/api/version` → `/api/tags` two-step, also mirrored in Olla's
  per-backend health table) — the same two-step shape applies to any
  provider status check: fast "is it up" before slower "what's on it."
- **`tmux capture-pane -p | tail -n 3..5` as a zero-integration "what was
  it doing" preview** (from Codex's `/status` and tmux-resurrect) — cheap,
  generic, no per-CLI parsing needed if selectorai ever adds a reattach
  flow.

## Ideas deliberately not adopted

- **Running a persistent local proxy** (claude-code-router, Quotio's
  CLIProxyAPI) — adds a background process, a port to manage, and a new
  failure mode (proxy itself going down) for a tool meant to be a thin
  hook at SSH-session start. selectorai writes config/env directly
  instead.
- **A supervisor daemon of its own** (Claude Code's `claude agents`
  model) — the right architecture for a tool that *owns* the agent
  process, but selectorai doesn't own or wrap the CLI's runtime; where a
  CLI already has its own daemon (Claude Code does), the plan is to shell
  out to its native commands rather than reimplement one.
- **Parallel multi-agent orchestration** (AgentGrid, Codeman,
  TokenTelemetry, claude-squad-style worktree fan-out) — explicitly a
  different product shape (many concurrent agents) than selectorai's
  serial pick-one-and-launch model. Out of scope by design, not by
  oversight.
- **OS-keyring-backed credential storage with snapshot/rollback** (aisw) —
  a genuinely good idea for a tool whose *job* is credential switching;
  less relevant where selectorai mostly reads each CLI's own existing
  auth state rather than owning/rotating credentials itself. Revisit if
  selectorai ever grows multi-account rotation.
- **Cross-machine session listing over Tailscale** (ccmux/skz.dev) —
  validates that a per-host daemon exposing a roster is an extensible
  primitive, but multi-host scope is explicitly beyond selectorai's
  current single-host design.
- **MCP server exposing selectorai's own status data to other agents**
  (ccusage's `@ccusage/mcp`) — plausible future extension, not adopted
  now; selectorai's status output stays a plain CLI/dict contract until
  there's a concrete consumer.

---

## Local models (Ollama & friends)

Every serious coding CLI in the 2026 landscape treats a local model server
as just another OpenAI-compatible (or Ollama-native / Anthropic-Messages-
compatible) HTTP endpoint on `localhost:11434` — no login, no API key, no
quota tracking. Auth only reappears if the user opts into a vendor's cloud
add-on (e.g. `ollama signin` for Ollama Cloud). The consistent shape across
every integration surveyed:

1. **Probe a cheap liveness endpoint** — Ollama: `GET /` (plaintext
   "Ollama is running") or `GET /api/version`; LM Studio: `GET
   /v1/models`; llama.cpp/vLLM/SGLang: `GET /health`.
2. **List models via a backend-specific endpoint** — Ollama:
   `GET /api/tags` (JSON array with name/size/digest/quantization); LM
   Studio: `GET /api/v0/models`; others: `GET /v1/models`. Ollama's
   `GET /api/ps` additionally distinguishes models *currently loaded in
   memory* (instant response) from merely downloaded (cold-load delay on
   first use).
3. **Auto-populate a model picker from that response** rather than
   requiring hand-entered model IDs.
4. **Hand inference off through the OpenAI-compatible `/v1/` path** most
   of these CLIs already speak.

### Per-integration notes

- **Codex CLI `--oss` flag** —
  [docs.ollama.com/integrations/codex](https://docs.ollama.com/integrations/codex) (`multiple-sources`)
  `codex --oss` points Codex at `http://localhost:11434/v1/`, defaulting
  to `gpt-oss:20b`; `ollama launch codex` auto-detects Ollama and writes a
  dedicated profile in one command. Also supports LM Studio/MLX via the
  same mechanism. No login required for local inference. Recommended
  minimum context window cited as 32k–64k tokens (docs disagree on the
  exact figure — verify before hardcoding). RAM requirement for
  `gpt-oss:20b` is in the ~16GB+ class per general Ollama model-page
  guidance, not confirmed in Codex's own docs — verify against Ollama's
  model page before gating on a specific number.
- **`ollama launch <app>`** —
  [ollama.com/blog/codex](https://ollama.com/blog/codex) (`multiple-sources`)
  Ollama ships no agentic coding CLI of its own; instead it's a generic
  app-launcher that auto-configures third-party CLIs (Codex, Claude Code,
  OpenCode, others) against a local or Ollama-Cloud model. As of Jan 2026
  it also exposes an Anthropic-Messages-API-compatible endpoint alongside
  its native `/api/*` and OpenAI-compatible `/v1/*`, so one Ollama
  instance can back almost any CLI regardless of expected wire protocol.
  This is effectively prior art for exactly selectorai's "given app X,
  write the right profile for local model Y" problem, at smaller scope.
- **OpenCode** —
  [opencode.ai/docs](https://opencode.ai/docs/) (`multiple-sources`)
  75+ providers including first-class Ollama/LM Studio/vLLM support.
  Single static binary (`curl -fsSL https://opencode.ai/install | bash` or
  `npm install -g opencode-ai`). Interactively: `/models` → ctrl+a → pick
  "Ollama," auto-discovers models from the running server with zero
  manual model-ID entry and no real API key needed.
- **Aider** —
  [aider.chat/docs/llms/ollama.html](https://aider.chat/docs/llms/ollama.html) (`multiple-sources`)
  `aider --model ollama_chat/<model>` (note the `ollama_chat/` prefix, not
  the legacy/incomplete `ollama/`) plus `export
  OLLAMA_API_BASE=http://127.0.0.1:11434`. No API key. Auto-sizes context
  window to request + 8k reply tokens by default; per-model overrides via
  `.aider.model.settings.yml`.
- **Crush** —
  [charmbracelet-crush.mintlify.app/advanced/local-models](https://charmbracelet-crush.mintlify.app/advanced/local-models) (`multiple-sources`)
  Custom provider block (`type: ollama` or generic OpenAI-compat,
  `base_url: http://localhost:11434/v1/`); `discover_models: true` (or an
  empty models list) triggers auto-discovery from the live server, merged
  with any hand-entered models.
- **gptme** —
  [gptme.org/docs/providers.html](https://gptme.org/docs/providers.html) (`single-source`)
  `export OPENAI_BASE_URL=http://127.0.0.1:11434/v1` + `gptme -m
  local/<model-name>`. Treats any OpenAI-compatible local server
  identically under a generic `local/` namespace — backend-agnostic
  naming worth copying regardless of which specific backend is running.
- **Ollama REST API** —
  [github.com/ollama/ollama/blob/main/docs/api.md](https://github.com/ollama/ollama/blob/main/docs/api.md) (`verified-repo`)
  `/api/tags`, `/api/version`, `/api/ps`, and the bare `/` banner — see
  the probe/list pattern above. No auth on any of these.
- **pi (badlogic/pi-mono) design proposal** —
  [github.com/badlogic/pi-mono/issues/1321](https://github.com/badlogic/pi-mono/issues/1321) (`single-source`)
  An open design doc in a sibling launcher project that is almost exactly
  selectorai's local-provider problem: 500ms-timeout `/api/tags` probe at
  startup, register Ollama via its OpenAI-compatible `/v1/` endpoint,
  `OLLAMA_HOST` env-var override for non-default hosts, manual config
  entries take precedence over auto-detected ones, and an explicit
  `ollamaAutoDetect: false` opt-out flag. Nearly a ready-made spec.
- **Olla** —
  [thushan.github.io/olla/concepts/health-checking](https://thushan.github.io/olla/concepts/health-checking/) (`multiple-sources`)
  Multi-backend health-check/discovery proxy; the useful artifact here is
  its per-backend endpoint table (Ollama `/` + `/api/tags`, LM Studio
  `/v1/models` + `/api/v0/models`, llama.cpp/vLLM `/health` + `/v1/models`)
  and its adaptive-backoff polling model (doubling interval up to 12x,
  capped at 60s) that re-triggers discovery specifically on the
  Unhealthy→Healthy transition rather than on a fixed timer.
- **LM Studio CLI (`lms`)** —
  [lmstudio.ai/docs/cli](https://lmstudio.ai/docs/cli) (`multiple-sources`)
  `lms ls` (downloaded) / `lms ps` (loaded-in-memory) mirror Ollama's
  tags/ps split. `lms load`/`unload` with `--gpu=max|auto|0.0-1.0` is the
  LM Studio equivalent of `ollama run`/`ollama stop` if selectorai ever
  wants to actively manage (not just detect) a local backend.

### Recommendation: least-effort integration path

> **Model "local" as a provider type with no quota/auth concept, health-
> checked via Ollama's `GET /` → `GET /api/tags` two-step (following the
> pi-mono #1321 spec almost verbatim: short timeout, `OLLAMA_HOST`
> override, manual-config-wins precedence, explicit opt-out flag), and
> point already-installed CLIs at it rather than adding a new agent.**
>
> Of the CLIs surveyed, **OpenCode is the standout least-effort target**
> to wire up first: single-command install (`curl -fsSL
> https://opencode.ai/install | bash`), zero-auth local-model
> auto-discovery already built into the tool, and no config-file
> templating footguns to paper over. Aider and Crush are viable seconds
> but each carry a small footgun selectorai's template would need to
> hide from the user (Aider's `ollama_chat/` vs. `ollama/` prefix trap;
> Crush needing an explicit `discover_models: true` or provider block).
> Codex's `--oss` flag is also low-effort and directly relevant since
> Codex is already a selectorai-managed CLI — `ollama launch codex`
> effectively does the profile-writing selectorai would otherwise
> implement itself.
