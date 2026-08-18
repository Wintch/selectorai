# Free-tier CLI candidates for selectorai

Research snapshot: **August 2026**. Merged from two independent research sweeps
(majors + challengers), deduplicated, and ranked for addition to selectorai.

## Ranking criteria (in order)

1. **Genuinely free recurring quota with a periodic reset** — daily is best,
   weekly is fine. One-time trial credits, "free while the promo lasts"
   rotating model lineups, and BYOK-only tools do not count as a free tier
   for this ranking, even if the CLI itself is free/open-source.
2. **Install simplicity on Linux** — a native binary/install script ranks
   above npm; npm ranks above pip/uv/git-clone build steps. (Node.js is
   available in the target environment, so npm is not a hard blocker.)
3. **Automation-friendliness** — non-interactive/headless flags, an
   auto-approve ("yolo") mode, and a working session-resume flag.
4. **Non-interactive quota query** — whether remaining quota can be checked
   without a human in a browser or TUI. This is rare across the board.
5. **Documentation confidence** — `verified-docs` (confirmed against
   first-party docs) beats `multiple-sources` beats `single-source`.

Per this project's documentation rule: **anything that could not be
confirmed against official/first-party sources is explicitly marked as
unverified below** — do not treat unmarked claims as more solid than they
are; check the cited sources before wiring up quota-parsing logic.

---

## 1. Gemini CLI

- **Vendor**: Google (`google-gemini/gemini-cli`)
- **Install**: `npm install -g @google/gemini-cli` (Node.js ≥20 required). Alt: `brew install gemini-cli`, or run ad hoc via `npx @google/gemini-cli`. No native Linux binary.
- **Free quota**: OAuth ("Log in with Google") free tier: **60 req/min AND 1,000 req/day**, shared across Gemini 2.5 Pro/Flash. **Resets daily at midnight Pacific Time** (per-minute limit is a rolling window). A separate, smaller path exists via unpaid `GEMINI_API_KEY` (250 req/day, Flash-class only) — not the recommended path. Google states exact numbers are actively adjusted; treat as subject to change.
- **Login**: OAuth browser login (`Log in with Google`, personal or Workspace account).
- **Automation flags**: Non-interactive one-shot via `gemini -p "prompt"` (supports `--output-format json` / `stream-json`). Auto-approve via `--yolo` (legacy) or the newer unified `--approval-mode yolo|auto_edit|default`. The two are mutually exclusive; docs recommend `--approval-mode` going forward.
- **Resume support**: **UNVERIFIED** — official docs reference a "conversation checkpointing" feature to save/resume sessions, but the exact CLI flag/command syntax was not confirmed from a primary source in this pass.
- **Usage query (non-interactive)**: Not available. `/stats model` inside an interactive session shows session token usage, but community bug reports (GitHub #17081, #25598) say it has not reliably shown remaining daily quota. No documented flag to print remaining quota from a script.
- **Confidence**: `verified-docs`
- **Sources**: google-gemini.github.io/gemini-cli/docs/quota-and-pricing.html; github.com/google-gemini/gemini-cli/blob/main/docs/resources/quota-and-pricing.md; github.com/google-gemini/gemini-cli; google-gemini.github.io/gemini-cli/docs/get-started/configuration.html; inventivehq.com/knowledge-base/gemini/how-to-use-yolo-mode
- **Fit for selectorai**: Best overall — the only major candidate with a confirmed **daily** reset, solid docs, and a real auto-approve flag; add it.

---

## 2. GitHub Copilot CLI

- **Vendor**: GitHub / Microsoft
- **Install**: `npm install -g @github/copilot` (Node.js ≥22). Alt native paths: `brew install --cask copilot-cli`, `winget install GitHub.Copilot`, or install script `curl -fsSL https://gh.io/copilot-install | bash` (standalone executables available — no npm required on Linux via the install script). Standalone `copilot` binary reached GA on 2026‑02‑25, distinct from the older `gh copilot` extension.
- **Free quota**: GitHub Copilot Free plan: **2,000 code completions/month + 50 chat/premium requests/month**, shared pool between CLI, IDE Agent Mode, and chat. Free plan is restricted to auto-selected lower-tier models (e.g. Claude Haiku 3.5 / GPT‑4o‑mini class) — no premium models. No overage; usage stops at the cap until reset. **Resets monthly**, on the 1st at 00:00 UTC; unused requests do not roll over.
- **Login**: Interactive `copilot` → `/login` (GitHub OAuth device flow). Non-interactive/CI: fine-grained PAT with "Copilot Requests" permission via `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`.
- **Automation flags**: `--allow-all-tools` (approve all tool/command use — full autopilot); `--allow-tool <name>` / `--deny-tool <name>` for granular control (`--deny-tool` wins over allow). Has a distinct autonomous "Autopilot" mode and a Plan mode.
- **Resume support**: `copilot --resume` lists recent interactive sessions to pick from and resumes with full history — the strongest, most explicitly documented resume flow of all candidates reviewed.
- **Usage query (non-interactive)**: Not available from the CLI. Usage is checked via the web-based "Monitoring your GitHub Copilot usage and entitlements" dashboard.
- **Confidence**: `verified-docs`
- **Sources**: github.blog/changelog/2026-02-25-github-copilot-cli-is-now-generally-available; docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli; docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/allowing-tools; github.com/features/copilot/plans; docs.github.com/copilot/concepts/copilot-billing/understanding-and-managing-requests-in-copilot
- **Fit for selectorai**: Only monthly reset (vs. Gemini's daily), but the best-documented automation flags and resume support of any candidate, plus a script-friendly install path — strong add.

---

## 3. Kiro CLI (successor to Amazon Q Developer CLI)

- **Vendor**: AWS (product now branded Kiro)
- **Install**: Native binary/install script — **recommended path**: `curl -fsSL https://cli.kiro.dev/install | bash` (Mac/Linux). Legacy Amazon Q Developer CLI download is still available (zip/deb/dnf from `desktop-release.q.us-east-1.amazonaws.com`, or `brew install --cask amazon-q`) but is being phased out — use the Kiro path. Kiro CLI stays backward-compatible with the `q` / `q chat` command entry points and auto-migrates config from `~/.aws/amazonq/`.
- **Free quota**: Kiro Free tier: **50 credits/month**, no purchasable top-up on the free plan. **Resets monthly** (renews at the start of the next billing cycle per Kiro billing docs). ⚠️ **Important caveat**: new signups for the *legacy* Amazon Q Developer Free Tier were blocked starting 2026‑05‑15 — new users must sign up via **Kiro** specifically, not the old Amazon Q Developer product, for a free tier to exist at all.
- **Login**: AWS Builder ID (free individual account) via `q login` / browser auth flow; IAM Identity Center for enterprise SSO.
- **Automation flags**: `q chat --no-interactive --trust-all-tools "<prompt>"` — `--trust-all-tools` auto-approves all tool/command execution for headless use.
- **Resume support**: `q chat --resume` resumes the most recent conversation for the current working directory (auto-saved per directory); `/save` and `/load` slash commands for named states. **UNVERIFIED caveat**: some GitHub issues report bare `q --resume` (without `chat`) not working — only `q chat --resume` is confirmed reliable.
- **Usage query (non-interactive)**: Not available from the CLI. AWS suggests CloudWatch/Budgets alerts (console-based) for the legacy product; Kiro shows credit usage on its web dashboard only.
- **Confidence**: `verified-docs`
- **Sources**: aws.amazon.com/blogs/devops/amazon-q-developer-end-of-support-announcement; docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/upgrade-to-kiro.html; kiro.dev/docs/upgrade-guides/migrating-from-q-developer; kiro.dev/docs/billing; docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line-chat-persistence.html; github.com/aws/amazon-q-developer-cli
- **Fit for selectorai**: Viable and native-binary-installable, but selectorai's install script **must target the Kiro signup/install path, not legacy Amazon Q Developer**, or new users get no free tier at all — flag this prominently in the integration.

---

## 4. iFlow CLI

- **Vendor**: iFlow (心流, Chinese platform)
- **Install**: `npm i -g @iflow-ai/iflow-cli@latest` (Node.js ≥22 required). No native Linux binary found.
- **Free quota**: Reported around **~2,000 requests/day**, but this figure comes from third-party reporting, not confirmed first-party docs, and reportedly varies by which underlying model iFlow proxies. **Reset period stated as daily** in third-party sources — **UNVERIFIED against first-party docs**, which do not clearly publish an explicit reset statement.
- **Login**: "Login with iFlow" browser OAuth (recommended), or an iFlow API key (expires every 7 days), or BYOK against an OpenAI-compatible endpoint.
- **Automation flags**: Four approval modes — `yolo` (full auto-approve), `accepting-edits` (file edits only), plan mode, default (no auto-permissions). `-y` for yolo, `-p` for headless prompt mode.
- **Resume support**: `iflow --resume` / `-r`; also `-c` combined with `-p` for headless resume. **UNVERIFIED reliability**: a GitHub issue (iflow-ai/iflow-cli#196) reports `-r` hanging in headless/programmatic mode on recent versions — treat resume-in-automation as unreliable until retested.
- **Usage query (non-interactive)**: Not available. CLI shows a live "context left" indicator in the TUI status bar only, not a quota command.
- **Confidence**: `multiple-sources` (quota figures and reset cadence not first-party confirmed)
- **Sources**: platform.iflow.cn/en/cli/quickstart; github.com/iflow-ai/iflow-cli; github.com/iflow-ai/iflow-cli/issues/196; libraries.io/npm/@iflow-ai%2Fiflow-cli
- **Fit for selectorai**: Attractive daily-reset headline number, but weaker documentation confidence and a known headless-resume bug — add with the quota/reset caveats surfaced to the user.

---

## 5. Cursor CLI (`cursor-agent`)

- **Vendor**: Cursor (Anysphere)
- **Install**: `curl https://cursor.com/install -fsS | bash` — native binary, not npm. Windows: `irm 'https://cursor.com/install?win32=true' | iex`.
- **Free quota**: Cursor no longer publishes fixed numeric Hobby-tier quotas on its pricing page as of 2026 — **UNVERIFIED exact numbers**; check the account dashboard for the live limit. Community-reported approximate figures: **~50 "slow" premium agent requests/month and ~2,000 Tab completions/month**. New accounts also get a one-time one-week Pro trial before dropping to Hobby. No overage path — usage pauses until reset.
- **Reset period**: **Monthly** by community/doc consensus, but Cursor does not publish an exact reset date — **UNVERIFIED** exact cadence/date, check dashboard.
- **Login**: `cursor-agent login` opens browser OAuth against the Cursor account (shared plan/quota with the Cursor IDE). CI/non-interactive: generate a user API key from the Cursor Dashboard; `NO_OPEN_BROWSER=1` prints the login URL instead of opening a browser.
- **Automation flags**: Non-interactive `agent -p "prompt"` (headless/CI mode), `--output-format` for structured output, `--model`, `--mode plan|ask|agent`. **UNVERIFIED**: no explicit `--yolo`-style flag name was confirmed — permission/auto-run behavior appears to be controlled via `--mode` and dashboard/rules settings rather than one flag.
- **Resume support**: `agent ls` lists previous sessions; `agent resume` continues the most recent session; `--continue` resumes previous session; `--resume="chat-id-here"` resumes a specific named session.
- **Usage query (non-interactive)**: Not available. `agent status` only checks auth/login status, not remaining quota — must check the Cursor Dashboard (web).
- **Confidence**: `multiple-sources` (numeric quota figures not confirmed on Cursor's own pricing page)
- **Sources**: cursor.com/docs/cli/overview; cursor.com/docs/cli/reference/authentication; cursor.com/docs/cli/reference/parameters; nxcode.io/resources/news/is-cursor-ai-free-plans-limits-worth-upgrading-2026; usagebar.com/blog/when-does-cursor-usage-reset
- **Fit for selectorai**: Good native-binary install and solid resume support, but the free quota itself is no longer officially published — add with a "verify current limits in-app" caveat, no reliable auto-approve flag confirmed.

---

## 6. Mistral Vibe CLI

- **Vendor**: Mistral AI (released alongside Devstral 2 in 2026 — Mistral's first official coding CLI)
- **Install**: `curl -LsSf https://mistral.ai/vibe/install.sh | bash` — native install script. Open source at `github.com/mistralai/mistral-vibe`.
- **Free quota**: La Plateforme's free "Experiment" tier covers all Mistral models including Codestral/Devstral at **2 requests/minute** with roughly a **1-billion-token/month cap**. Explicitly positioned by Mistral for evaluation, not production/heavy agentic use. Vibe CLI has no separate bundled quota beyond whatever the console.mistral.ai account tier provides.
- **Reset period**: **Monthly** (per the ~1B tokens/month Experiment-tier cap); the 2 RPM rate limit is presumably a per-minute rolling window rather than a resetting bucket.
- **Login**: `vibe --setup` → "Launch browser" to authenticate with a Mistral account (console.mistral.ai), or set `MISTRAL_API_KEY` env var / `~/.vibe/.env`.
- **Automation flags**: `--prompt "..."` for one-shot programmatic execution; `--output text|json|streaming`; `--auto-approve` and `--yolo` both bypass all tool-call confirmations.
- **Resume support**: `--continue` / `-c` (resume most recent session); `--resume` (interactive session picker); `--resume SESSION_ID` (resume specific session, partial-ID match).
- **Usage query (non-interactive)**: Not available as a quota lookup. `--max-price DOLLARS` and `--max-tokens N` are session-level spend/token guardrails, not usage queries.
- **Confidence**: `verified-docs`
- **Sources**: github.com/mistralai/mistral-vibe/blob/main/README.md; mistral.ai/news/devstral-2-vibe-cli; mistral.ai/products/vibe/code
- **Fit for selectorai**: Solid docs, native install script, and both `--yolo` and `--resume` — but the 2 RPM rate limit and "evaluation only" framing make it the weakest of the qualifying six for sustained/automated use; add as a lower-priority option.

---

## Not recommended / no qualifying free tier

| Candidate | Vendor | Reason |
|---|---|---|
| **Qwen Code** | Alibaba | First-party free hosted quota (Qwen OAuth) was fully discontinued 2026‑04‑15; now BYOK-only against third-party providers. No standing free tier remains. |
| **Z.ai GLM free API / ZCode** | Z.ai (Zhipu) | Not a standalone CLI — it's an Anthropic-compatible API endpoint you point an *existing* CLI (e.g. Claude Code) at via `ANTHROPIC_BASE_URL`. GLM‑4.5‑flash itself is genuinely free with a daily-ish reset (**UNVERIFIED exact cap, ~1,000 req/day per third-party trackers, ~1 req/sec**), but it has no CLI of its own for selectorai to install/launch — worth revisiting only as a config preset for an existing supported CLI, not as a new entry. |
| **OpenCode (Zen gateway)** | SST | Zen's "free" models are a rotating $0 promotional slate with no published rate limit or fixed reset cadence — access can vanish or move to paid without notice; fails ranking criterion 1 (no periodic reset). |
| **Crush** | Charm | BYOK-first; no documented always-free quota for Charm's own "Charm Hyper" provider. Free usage entirely depends on whichever third-party provider/key you configure. |
| **Kimi CLI / Kimi Code** | Moonshot AI | No standing free tier for the CLI's API path — platform.moonshot.ai requires a minimum $1 recharge to activate an account. The free surface (kimi.com chat app) is a separate, rate-limited consumer product, not reachable from the CLI. |
| **Cerebras Code CLI** | Cerebras Systems | As of 2026‑07‑21, Cerebras replaced its recurring 1M-tokens/day free tier with a one-time $5 trial credit that does not renew. No recurring free quota remains. |
| **Factory Droid CLI** | Factory AI | No free usage tier at all — account signup is free but productive use requires a paid Pro plan ($20/mo+); no trial-credit grant found. |
| **OpenHands CLI** | OpenHands (ex-OpenDevin) | Open-source local mode is pure BYOK (no vendor quota). OpenHands Cloud's free "Individual" tier has no fixed free token/request number found in sources — reads as a free *account* tier, not a free *usage* allotment. |
| **Trae Agent CLI (trae-cli)** | ByteDance | Pure BYOK against external providers (OpenAI/Anthropic/Gemini/etc.) — no bundled vendor quota. The separate Trae IDE product has a real free plan, but that is **not confirmed to extend to trae-cli**, a different product. |
| **Windsurf / Codeium CLI** | Cognition (ex-Codeium/Windsurf) | No standalone terminal coding-agent CLI exists as of August 2026 — `windsurf` on the shell only launches the IDE GUI. Product was rebranded into "Devin Desktop" (2026‑06‑02) and remains IDE-first. |

---

## Summary of unverified claims requiring follow-up before shipping

- Gemini CLI: exact resume/checkpoint CLI syntax.
- iFlow CLI: daily reset cadence and 2,000 req/day figure (third-party only); headless `-r`/`--resume` reliability.
- Cursor CLI: exact free-tier numeric quota and reset date (Cursor no longer publishes these); existence of any single-flag auto-approve.
- Kiro CLI: reliability of bare `q --resume` vs. `q chat --resume`.
- Z.ai GLM‑4.5‑flash: exact request/day cap and rate limit (has changed more than once per trackers).
