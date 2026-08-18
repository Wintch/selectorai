# Roadmap

Not a promise, not a backlog with dates — a ranked list of what's next and
why, grounded in the research already done in
[`docs/CANDIDATES.md`](CANDIDATES.md) (free-tier CLI survey, August 2026)
and [`docs/PRIOR_ART.md`](PRIOR_ART.md) (adjacent-project survey, same
month). Read either of those for the full sourcing and confidence markers
(`verified-docs` > `multiple-sources` > `single-source`) behind every claim
below — this file only summarizes the ranking and the reasoning.

Order reflects the project's actual stance: get selectorai's own four
providers and core mechanics solid first (see
[`docs/NOTES.md`](NOTES.md)'s known limitations and open items), then
expand outward — new cloud providers before local-model support, and
ideas borrowed from prior art last, since they extend the tool rather than
complete it.

## Near-term: new provider additions

Ranked using [`docs/CANDIDATES.md`](CANDIDATES.md)'s own criteria (real
recurring quota with a periodic reset first, daily beats weekly beats
monthly; install simplicity; automation-friendliness; a non-interactive
quota query if one exists; documentation confidence).

### 1. Gemini CLI — highest priority

- **Vendor**: Google (`google-gemini/gemini-cli`)
- **Why first**: the only major candidate with a **confirmed daily reset**
  — free tier is 60 req/min *and* 1,000 req/day, shared across Gemini 2.5
  Pro/Flash, resetting at midnight Pacific (`verified-docs`, per Google's
  own quota-and-pricing docs). Solid docs, a real auto-approve flag
  (`--approval-mode yolo` — the modern replacement for the legacy
  `--yolo`), and non-interactive one-shot mode (`gemini -p "prompt"`,
  `--output-format json`).
- **Install**: `npm install -g @google/gemini-cli` (Node ≥20; no native
  Linux binary, unlike selectorai's other four providers — worth noting
  in the install step's UX).
- **Open gaps before shipping**: no confirmed non-interactive usage query
  (same shape as Codex/Grok today — `/stats model` is TUI-only and
  reportedly unreliable per community bug reports); exact resume/
  checkpoint CLI syntax unverified. Both are exactly the kind of gap
  `docs/ADDING_PROVIDERS.md`'s process is built to catch before code is
  written, not after.

### 2. iFlow CLI

- **Vendor**: iFlow (心流)
- **Why second**: an attractive headline number (~2,000 req/day,
  reportedly daily-reset) but weaker documentation confidence
  (`multiple-sources` — the reset cadence isn't stated in iFlow's own
  first-party docs) and a known headless-resume bug
  (iflow-ai/iflow-cli#196: `-r` reportedly hangs in headless mode on
  recent versions). Four approval modes including a real `yolo`/`-y`.
- **Install**: `npm i -g @iflow-ai/iflow-cli@latest` (Node ≥22).
- **Ship with caveats surfaced to the user** rather than waiting for
  upstream to publish a first-party reset statement — same "mark verified
  vs. assumed" rule as everything else in this project, just applied to a
  whole provider instead of one behavior.

### 3. Mistral Vibe CLI

- **Vendor**: Mistral AI
- **Why third**: solid docs (`verified-docs`), a native install script,
  and both `--yolo` and `--resume`/`-c` — matches selectorai's provider
  contract cleanly. Ranked below the first two because the free
  "Experiment" tier is explicitly positioned by Mistral for evaluation,
  not sustained agentic use (2 requests/minute cap), and resets monthly
  rather than daily.
- **Install**: `curl -LsSf https://mistral.ai/vibe/install.sh | bash`.

### Considered, not currently prioritized

`docs/CANDIDATES.md` also covers **GitHub Copilot CLI** (best-documented
resume flow of any candidate, but monthly-only reset) and **Kiro CLI**
(viable native-binary install, but selectorai's install step would need to
target the Kiro-specific signup path, not the deprecated legacy Amazon Q
Developer one, or new users get no free tier at all) — both real
candidates, just behind the three above on the daily-reset criterion.
**Cursor CLI** is excluded from this ranking: its free-tier numbers and
reset cadence are no longer published anywhere, first-party or otherwise.

## Local models (Ollama & friends)

A structurally different addition from the cloud providers above — no
account, no OAuth, no quota to poll at all, which sidesteps this project's
single biggest source of past incidents (the Antigravity OAuth popup, see
[`docs/NOTES.md`](NOTES.md)). `docs/PRIOR_ART.md`'s survey of the 2026
landscape found the same two-step health-check shape reused everywhere
(Ollama, LM Studio, llama.cpp, vLLM all converge on it) — the plan below
follows it rather than inventing a new one.

**Detection**: `GET http://localhost:11434/api/tags` with a ~500ms
timeout, doing double duty as liveness *and* model-list in one call
(no separate `/api/version` ping first) — following the design already
worked out in a sibling project's own open design doc,
[pi-mono#1321](https://github.com/badlogic/pi-mono/issues/1321)
(`single-source`, but detailed enough to read as close to a ready-made
spec): short timeout, `OLLAMA_HOST` env-var override for non-default
hosts, manual config taking precedence over auto-detection, and an
explicit opt-out flag rather than silent always-on probing — worth
carrying that same opt-out shape into selectorai's own config, consistent
with how `--check-antigravity` is opt-in rather than assumed-safe.

**Least-effort integration path** (per `docs/PRIOR_ART.md`'s own
recommendation): model "local" as a provider type with no quota/auth
concept at all, and point an *already-installed* CLI at it rather than
adding a whole new agent binary to install/update/launch:

1. **`codex --oss --local-provider ollama`** — the least-effort option of
   all, since Codex is already a selectorai-managed provider. Points
   Codex at `http://localhost:11434/v1/`, defaulting to `gpt-oss:20b`; no
   new install step, no new login flow, no new module beyond a flag
   change in the existing `codex.py` launch path. (`multiple-sources`,
   via `ollama launch codex`/Ollama's own Codex integration docs —
   context-window and RAM-requirement specifics are flagged unverified in
   `docs/PRIOR_ART.md` and should be re-checked before hardcoding either
   number.)
2. **OpenCode** as the standalone alternative, if a dedicated local-model
   CLI (rather than pointing an existing one at Ollama) is ever wanted:
   single-command install (`curl -fsSL https://opencode.ai/install |
   bash`), zero-auth local-model auto-discovery already built in, no
   config-templating footguns to hide from the user — the standout
   least-effort target among the CLIs `docs/PRIOR_ART.md` surveyed for a
   *new* provider module, per that document's own recommendation section.

Aider and Crush are viable but each carry a small footgun a selectorai
integration would need to paper over (Aider's `ollama_chat/` vs.
`ollama/` prefix trap; Crush needing an explicit `discover_models: true`)
— lower priority than the two above unless one becomes specifically
requested.

## Ideas adopted from prior art (future, not scheduled)

`docs/PRIOR_ART.md`'s "Ideas adopted" section already covers what's been
folded into the current design (the provider-contract status shape,
opt-in live checks, graceful degradation). The ideas below are the ones
flagged there as *plausible future extensions*, credited to their source
projects, listed last because they extend the tool rather than complete
its core provider set:

- **Named failover policies (round-robin / fill-first) as an auto-pick
  mode** — from **Quotio**'s two named strategies for its own multi-account
  proxy setup
  ([github.com/nguyenphutrong/quotio](https://github.com/nguyenphutrong/quotio),
  `multiple-sources`). selectorai's picker is manual-pick by design today;
  an opt-in "just pick the healthiest one automatically" mode, modeled on
  Quotio's naming, would sit on top of the existing health
  classification (`sai/health.py`) without touching the provider contract
  itself.
- **A `ccusage statusline`-style compact snippet** — from **ccusage**
  ([github.com/ryoppippi/ccusage](https://github.com/ryoppippi/ccusage),
  `multiple-sources`), which already covers this project's exact
  four-CLI set (plus a dozen more) from local JSONL logs alone. A
  one-line `selectorai statusline` command, reusing the same
  `render_status_rows`/`provider_summary` helpers `sai/providers/base.py`
  already exposes, would be a small addition for embedding current
  status in a shell prompt or tmux status bar.
- **Burn-rate / exhaustion forecasting** — from
  **Claude-Code-Usage-Monitor**
  ([github.com/Maciek-roboblog/Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor),
  `multiple-sources`), which pairs a burn-rate estimate with explicit
  official-data-vs.-local-estimate confidence labeling — worth copying
  that labeling discipline specifically, since selectorai already
  distinguishes verified-live data (Claude, opt-in Antigravity) from
  reactive-only estimates (Codex) and a forecast built on the latter
  should say so as plainly as the rest of this project marks assumptions.

## Explicitly out of scope

Carried straight from `docs/PRIOR_ART.md`'s "Ideas deliberately not
adopted" section — listed here so a future contributor doesn't have to
rediscover the reasoning:

- **A persistent local proxy** (claude-code-router, Quotio's CLIProxyAPI)
  — adds a background process and a new failure mode for a tool meant to
  be a thin hook at SSH-session start.
- **A supervisor daemon of selectorai's own** (Claude Code's `claude
  agents` model) — the right architecture for a tool that *owns* the
  agent process; selectorai doesn't, and shells out to each CLI's native
  commands instead.
- **Parallel multi-agent orchestration** (AgentGrid, Codeman,
  claude-squad-style worktree fan-out) — a genuinely different product
  shape (many concurrent agents) than selectorai's serial
  pick-one-and-launch model.
- **OS-keyring-backed credential storage with snapshot/rollback** (aisw)
  — selectorai reads each CLI's own existing auth state rather than
  owning/rotating credentials itself; revisit only if selectorai ever
  grows multi-account rotation.
