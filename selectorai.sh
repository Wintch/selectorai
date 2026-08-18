#!/usr/bin/env bash
# selectorai — installs/updates your AI CLIs and recommends which one to use
# based on how much quota is left and how long since you last used it.
set -uo pipefail

STATE_DIR="$HOME/.selectorai"
LAUNCH_LOG="$STATE_DIR/launch.log"
mkdir -p "$STATE_DIR"

# Off by default: probing Antigravity ("agy -p /usage") while not logged in
# triggers its real interactive Google OAuth flow (confirmed in
# ~/.gemini/antigravity-cli/log/*.log: "Print mode: not authenticated, trying
# silent auth" -> "silent auth failed" -> "triggering interactive OAuth" ->
# opens a browser). Only probe it live when explicitly asked (--check-antigravity,
# or persisted on via `check-antigravity on` below).
CHECK_ANTIGRAVITY_FILE="$STATE_DIR/check_antigravity"
[ -f "$CHECK_ANTIGRAVITY_FILE" ] && CHECK_ANTIGRAVITY=1 || CHECK_ANTIGRAVITY=0

# No equivalent CHECK_GROK gate: confirmed (not just precautionary) that
# there's no live usage check to gate in the first place — see
# provider_status_grok() below.

# Active providers. To add a new one: list its name here and fill in the
# provider_* case branches below.
PROVIDERS=(claude codex antigravity grok)

# ---------------------------------------------------------------------------
# Per-provider metadata
# ---------------------------------------------------------------------------

provider_bin() {
  case "$1" in
    claude) echo "claude" ;;
    codex) echo "codex" ;;
    antigravity) echo "agy" ;;
    grok) echo "grok" ;;
  esac
}

provider_label() {
  case "$1" in
    claude) echo "Claude Code" ;;
    codex) echo "Codex CLI" ;;
    antigravity) echo "Antigravity (Google)" ;;
    grok) echo "Grok Build (xAI)" ;;
  esac
}

provider_installed() {
  command -v "$(provider_bin "$1")" >/dev/null 2>&1
}

provider_install() {
  case "$1" in
    claude) curl -fsSL https://claude.ai/install.sh | bash ;;
    # Official native installer (no npm/Node dependency), confirmed against
    # github.com/openai/codex. Only runs when the binary isn't there yet.
    codex) curl -fsSL https://chatgpt.com/codex/install.sh | sh ;;
    antigravity) curl -fsSL https://antigravity.google/cli/install.sh | bash ;;
    grok) curl -fsSL https://x.ai/cli/install.sh | bash ;;
  esac
}

provider_update() {
  case "$1" in
    claude) claude update ;;
    codex) codex update ;;
    antigravity) agy update ;;
    grok) grok update ;;
  esac
}

# Each provider's own login entry point, verified against its real --help:
# `claude auth --help` -> `login` subcommand; `codex login --help` /
# `grok login --help` -> `--device-auth` explicitly requests the URL+code
# flow (phone-friendly, vs. defaulting to auto-opening a local browser);
# `agy --help` has no separate login subcommand at all — bare `agy`
# auto-detects a missing session and runs its own local-browser-or-URL flow.
provider_login_cmd() {
  case "$1" in
    claude) echo "claude auth login" ;;
    codex) echo "codex login --device-auth" ;;
    antigravity) echo "agy" ;;
    grok) echo "grok login --device-auth" ;;
  esac
}

provider_login_status_cmd() {
  case "$1" in
    claude) echo "claude auth status" ;;
    codex) echo "codex login status" ;;
    antigravity) echo "" ;;  # no non-interactive status subcommand exposed
    grok) echo "" ;;  # no non-interactive status subcommand exposed either
  esac
}

# Real last-used time: read from the CLI's own log, not from this script's
# own history, so it stays accurate even when you use the tool outside of
# this script (fixes "only updates when I launch it through the script").
provider_last_used_epoch() {
  case "$1" in
    claude)
      local f="$HOME/.claude/history.jsonl"
      [ -f "$f" ] && stat -c %Y "$f" 2>/dev/null || echo 0
      ;;
    codex)
      local f="$HOME/.codex/history.jsonl"
      [ -f "$f" ] && stat -c %Y "$f" 2>/dev/null || echo 0
      ;;
    antigravity)
      local ts
      ts=$(find "$HOME/.gemini/antigravity-cli/conversations" -type f -printf '%T@\n' 2>/dev/null \
        | sort -n | tail -1 | cut -d. -f1)
      echo "${ts:-0}"
      ;;
    grok)
      # Unconfirmed — no completed Grok session on this machine yet to
      # observe the real path from (same reasoning as the .py version).
      # Best-effort: history.jsonl convention, then a sessions/ dir.
      local f="$HOME/.grok/history.jsonl" ts
      if [ -f "$f" ]; then
        stat -c %Y "$f" 2>/dev/null || echo 0
      else
        ts=$(find "$HOME/.grok/sessions" -type f -printf '%T@\n' 2>/dev/null \
          | sort -n | tail -1 | cut -d. -f1)
        echo "${ts:-0}"
      fi
      ;;
    *) echo 0 ;;
  esac
}

# Fills in:
#   STATUS_PCT   - worst-case % used (0-100), or -1 if unknown
#   STATUS_ROWS  - array of "Label|UsedPct|ResetInfo" (one per tracked limit)
#   STATUS_NOTE  - free-text note, shown when STATUS_ROWS is empty
provider_status() {
  STATUS_PCT=-1
  STATUS_ROWS=()
  STATUS_NOTE=""
  case "$1" in
    claude) provider_status_claude ;;
    codex) provider_status_codex ;;
    antigravity) provider_status_antigravity ;;
    grok) provider_status_grok ;;
    *) STATUS_NOTE="no status check configured" ;;
  esac
}

# Countdown helpers, e.g. "in 3d 14h" instead of just an absolute date —
# makes it obvious at a glance whether a reset is hours away (a session
# window) or days away (weekly/monthly), for all three providers.
format_countdown() {
  local seconds="$1" d h m
  [ "$seconds" -le 0 ] && { echo "any moment now"; return; }
  d=$((seconds / 86400)); seconds=$((seconds % 86400))
  h=$((seconds / 3600)); seconds=$((seconds % 3600))
  m=$((seconds / 60))
  if [ "$d" -gt 0 ]; then printf 'in %dd %dh' "$d" "$h"
  elif [ "$h" -gt 0 ]; then printf 'in %dh %dm' "$h" "$m"
  else printf 'in %dm' "$m"
  fi
}

# Best-effort: turn a human reset string like 'Aug 21, 4am (America/
# Argentina/Buenos_Aires)' into a Unix epoch via `date -d`. Confirmed by
# hand testing: GNU date needs the trailing '(Zone/Name)' turned into a
# leading `TZ="..."` prefix instead, AND the comma right before the time
# (Claude's own format) stripped out first, or it just fails to parse.
parse_reset_epoch() {
  local text="$1" tz_name="" date_part
  date_part="$text"
  if [[ "$text" =~ \(([^\)]+)\)[[:space:]]*$ ]]; then
    tz_name="${BASH_REMATCH[1]}"
    date_part="${text%(*}"
  fi
  date_part="${date_part//,/}"
  date_part="$(printf '%s' "$date_part" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
  [ -z "$date_part" ] && return 1
  if [ -n "$tz_name" ]; then
    date -d "TZ=\"$tz_name\" $date_part" +%s 2>/dev/null
  else
    date -d "$date_part" +%s 2>/dev/null
  fi
}

# Combine an absolute reset string with a computed countdown — pass a known
# epoch when the caller already has one (Codex's saved rate-limit
# timestamp, Antigravity's parsed ISO time), otherwise it's parsed from the
# text itself (Claude's raw /usage reset strings).
reset_with_countdown() {
  local absolute="$1" epoch="${2:-}" now countdown
  if [ -z "$epoch" ]; then
    epoch=$(parse_reset_epoch "$absolute") || { echo "$absolute"; return; }
  fi
  [ -z "$epoch" ] && { echo "$absolute"; return; }
  now=$(epoch_now)
  countdown=$(format_countdown $((epoch - now)))
  printf '%s — %s' "$countdown" "$absolute"
}

provider_status_claude() {
  local out session s_reset week w_reset fable f_reset
  out=$(timeout 20 claude -p "/usage" 2>/dev/null || true)
  session=$(printf '%s\n' "$out" | grep -oP 'Current session: \K[0-9]+(?=% used)' | head -1)
  s_reset=$(printf '%s\n' "$out" | grep -oP '^Current session:.*resets \K.*$' | head -1)
  week=$(printf '%s\n' "$out" | grep -oP 'Current week \(all models\): \K[0-9]+(?=% used)' | head -1)
  w_reset=$(printf '%s\n' "$out" | grep -oP '^Current week \(all models\):.*resets \K.*$' | head -1)
  fable=$(printf '%s\n' "$out" | grep -oP 'Current week \(Fable\): \K[0-9]+(?=% used)' | head -1)
  f_reset=$(printf '%s\n' "$out" | grep -oP '^Current week \(Fable\):.*resets \K.*$' | head -1)

  if [ -z "$session" ] && [ -z "$week" ]; then
    STATUS_NOTE="couldn't read /usage (login expired?)"
    return
  fi
  session=${session:-0}
  week=${week:-0}
  STATUS_ROWS+=("Session (5h)|$session|$(reset_with_countdown "${s_reset:-unknown}")")
  STATUS_ROWS+=("Weekly|$week|$(reset_with_countdown "${w_reset:-unknown}")")
  [ -n "$fable" ] && STATUS_ROWS+=("Weekly (Fable)|$fable|$(reset_with_countdown "${f_reset:-unknown}")")
  if [ "$session" -ge "$week" ]; then STATUS_PCT=$session; else STATUS_PCT=$week; fi
}

provider_status_codex() {
  # OpenAI doesn't expose usage % through any non-interactive Codex CLI
  # command (it only lives in /status inside the TUI session, via the
  # internal app-server protocol). We don't guess it: we show "?" unless a
  # run launched from this script actually hit a rate-limit error — Codex's
  # own error message includes the exact reset date, which we store as-is
  # (no assumption about a fixed time window).
  local msg_f="$STATE_DIR/codex.ratelimited.msg"
  local until_f="$STATE_DIR/codex.ratelimited.until"
  if [ -f "$until_f" ]; then
    local until now
    until=$(cat "$until_f" 2>/dev/null || echo 0)
    now=$(epoch_now)
    if [ "$until" -gt "$now" ]; then
      STATUS_PCT=100
      STATUS_ROWS+=("Limit|100|$(reset_with_countdown "$(cat "$msg_f" 2>/dev/null || echo unknown)" "$until")")
      return
    fi
    rm -f "$msg_f" "$until_f"
  elif [ -f "$msg_f" ]; then
    STATUS_PCT=95
    STATUS_ROWS+=("Limit|95|unknown (couldn't parse date, last message: $(cat "$msg_f"))")
    return
  fi
  STATUS_NOTE="no usage % available via non-interactive CLI"
}

provider_status_antigravity() {
  # Gated behind CHECK_ANTIGRAVITY (--check-antigravity): running this while
  # not logged in makes `agy` pop an actual Google OAuth browser window (see
  # the CHECK_ANTIGRAVITY comment at the top of this file). Skip the call
  # entirely unless explicitly asked. Confirmed live even AFTER logging in
  # this can still happen unpredictably — Antigravity CLI has known
  # session-persistence bugs upstream (google-antigravity/antigravity-cli
  # issues #57 and #18: "does not remember OAUTH login" / "repeatedly
  # prompts for login"). The `timeout 10` below is what keeps that from
  # hanging this script if it happens.
  if [ "$CHECK_ANTIGRAVITY" -ne 1 ]; then
    STATUS_NOTE="not checked (pass --check-antigravity to probe; only do this after 'agy' has logged in once — otherwise it opens a Google OAuth browser popup, and can even after login due to upstream session-persistence bugs)"
    return
  fi
  # Real confirmed format (tab-separated, "% remaining" not "% used", one
  # row per underlying model bucket), e.g.:
  #   Gemini Models\tWeekly Limit Remaining\t62%\t2026-08-22T23:58:13Z
  #   Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-08-24T08:15:03Z
  # Confirmed live and replaces an earlier guess (copied blindly from
  # Claude's "% used" format) that never matched anything real.
  local out label kind remaining_raw reset_iso remaining pct_used reset_fmt reset_epoch max_pct=-1
  out=$(timeout 10 agy -p "/usage" 2>/dev/null || true)
  while IFS=$'\t' read -r label kind remaining_raw reset_iso; do
    [ -z "$label" ] && continue
    remaining=$(printf '%s' "$remaining_raw" | grep -oP '^[0-9]+')
    [ -z "$remaining" ] && continue
    pct_used=$((100 - remaining))
    reset_epoch=$(date -d "$reset_iso" +%s 2>/dev/null || true)
    reset_fmt=$(date -d "$reset_iso" '+%b %d, %H:%M' 2>/dev/null || echo "$reset_iso")
    STATUS_ROWS+=("$label|$pct_used|$(reset_with_countdown "$reset_fmt" "$reset_epoch")")
    [ "$pct_used" -gt "$max_pct" ] && max_pct=$pct_used
  done <<< "$out"
  if [ "$max_pct" -lt 0 ]; then
    STATUS_NOTE="no usage % available (not confirmed via CLI) — run 'agy' once to sign in"
    return
  fi
  STATUS_PCT=$max_pct
}

provider_status_grok() {
  # Confirmed from Grok's own shipped docs (~/.grok/docs/user-guide/
  # 04-slash-commands.md, 14-headless-mode.md) — not guessed: /usage
  # ("View credit usage or manage billing", alias /cost) is a real command,
  # but it's TUI-only. Headless mode (`-p`) sends its argument as a literal
  # chat prompt — it does not interpret slash commands at all — and there
  # is no CLI subcommand for this either (checked the full `grok --help`
  # command list). Billing is credit/USD based (`total_cost_usd` per
  # request), not a session/weekly quota percentage like the other three
  # providers, so nothing here maps onto this script's "% used" model even
  # in principle. Don't even try `grok -p "/usage"`: it would spend real
  # tokens/credits sending the model the literal text "/usage" as a
  # prompt, for a response that still wouldn't contain parseable data.
  STATUS_NOTE="not available — confirmed live on a free account (grok.com login, no API key/billing): /usage and /cost show nothing, there's no credit balance to check at all. The server just cuts you off once you hit an undocumented limit and pushes an upgrade prompt, no reset time given anywhere. Also structurally impossible to check headlessly even on a paid plan: headless mode doesn't interpret slash commands at all"
}

record_codex_ratelimit() {
  local text="$1" msg clean until_epoch
  msg=$(printf '%s\n' "$text" | grep -oP 'try again at \K[^.]*' | head -1)
  [ -z "$msg" ] && return
  printf '%s' "$msg" > "$STATE_DIR/codex.ratelimited.msg"
  clean=$(printf '%s' "$msg" | sed -E 's/([0-9]+)(st|nd|rd|th)\b/\1/')
  until_epoch=$(date -d "$clean" +%s 2>/dev/null || true)
  if [ -n "$until_epoch" ]; then
    printf '%s' "$until_epoch" > "$STATE_DIR/codex.ratelimited.until"
  else
    rm -f "$STATE_DIR/codex.ratelimited.until"
  fi
}

clear_codex_ratelimit() {
  rm -f "$STATE_DIR/codex.ratelimited.msg" "$STATE_DIR/codex.ratelimited.until"
}

# One-line summary built from the current STATUS_* globals, e.g.
# "70% left / 30% used (Session (5h), resets 10:50pm)" — used in the menu
# view. Always shows both used and left, explicitly labeled, to match
# print_status_block below (never a bare, unlabeled %).
provider_summary() {
  if [ "$STATUS_PCT" -lt 0 ]; then
    echo "${STATUS_NOTE:-no data}"
    return
  fi
  local left=$((100 - STATUS_PCT))
  local label="" reset="" row u l r
  for row in "${STATUS_ROWS[@]}"; do
    IFS='|' read -r l u r <<< "$row"
    if [ "$u" -eq "$STATUS_PCT" ]; then label="$l"; reset="$r"; break; fi
  done
  reset=$(printf '%s' "$reset" | sed -E 's/ *\([^)]*\) *$//')
  if [ -n "$label" ]; then
    printf '%d%% left / %d%% used (%s, resets %s)' "$left" "$STATUS_PCT" "$label" "${reset:-unknown}"
  else
    printf '%d%% left / %d%% used' "$left" "$STATUS_PCT"
  fi
}

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

epoch_now() { date +%s; }

fmt_ago() {
  local ts=$1 now diff
  now=$(epoch_now)
  diff=$(( now - ts ))
  if [ "$ts" -le 0 ]; then echo "never"; return; fi
  if [ "$diff" -lt 60 ]; then echo "${diff}s ago"
  elif [ "$diff" -lt 3600 ]; then echo "$((diff/60))m ago"
  elif [ "$diff" -lt 86400 ]; then echo "$((diff/3600))h ago"
  else echo "$((diff/86400))d ago"
  fi
}

log_launch() {
  printf '%s\t%s\t%s\n' "$(epoch_now)" "$1" "$2" >> "$LAUNCH_LOG"
}

# ---------------------------------------------------------------------------
# install / update
# ---------------------------------------------------------------------------

cmd_install() {
  local p
  for p in "${PROVIDERS[@]}"; do
    echo "== $(provider_label "$p") =="
    if provider_installed "$p"; then
      echo "  already installed, updating..."
      provider_update "$p"
    else
      echo "  not installed, installing..."
      provider_install "$p"
    fi
    echo
  done
}

cmd_check_antigravity() {
  case "${1:-}" in
    on)
      printf '1' > "$CHECK_ANTIGRAVITY_FILE"
      echo "Antigravity live usage check: ON by default now — every 'status'/menu run will call \`agy -p \"/usage\"\`."
      echo "Reminder: Antigravity's own session handling is flaky upstream (antigravity-cli#57/#18) — even logged in, this can still pop a fresh Google login prompt on any given run, not just the first one."
      echo "Turn it back off any time: ./selectorai.sh check-antigravity off"
      ;;
    off)
      rm -f "$CHECK_ANTIGRAVITY_FILE"
      echo "Antigravity live usage check: OFF by default (back to opt-in only — pass --check-antigravity for a single run instead)."
      ;;
    *)
      local state="off"
      [ -f "$CHECK_ANTIGRAVITY_FILE" ] && state="on"
      echo "Antigravity live usage check is currently: $state"
      echo "  ./selectorai.sh check-antigravity on   # persist: always probe"
      echo "  ./selectorai.sh check-antigravity off  # persist: opt-in only (default)"
      echo "  ./selectorai.sh --check-antigravity    # probe just for this one run, don't persist"
      ;;
  esac
}

# No cmd_check_grok / --check-grok: confirmed there's no live usage check
# to gate in the first place — see provider_status_grok() above.

# ---------------------------------------------------------------------------
# auth / login — same "clean URL" wrapper for every provider, specific login
# command per provider. Triggered only on explicit request (`auth`), never
# automatically, same principle as CHECK_ANTIGRAVITY above.
# ---------------------------------------------------------------------------

run_login_capture() {
  local p="$1" login_cmd status_cmd logfile url
  login_cmd=$(provider_login_cmd "$p")
  status_cmd=$(provider_login_status_cmd "$p")

  # Deliberately does NOT touch `stty cols` anymore. An earlier version
  # widened the pty to dodge a CLI's own word-wrap, but that mutates shared
  # terminal state a foreground TUI (this provider's login flow, or a later
  # `claude`/`codex`/`agy` session) reads at startup — if that TUI is then
  # running full-screen in raw mode, there's no way to hand control back to
  # restore it, and it stays stuck rendering at the wrong width (confirmed
  # live: a Claude Code session box-drawing itself across a corrupted-huge
  # column count). The tee+reconstruct step below already fixes the actual
  # URL regardless of whether it got wrapped on screen, so mutating the
  # terminal was never load-bearing — just removed.
  logfile=$(mktemp)
  # shellcheck disable=SC2086 # $login_cmd is one of our own fixed strings above, never user input
  $login_cmd 2>&1 | tee "$logfile"

  # Isolate the block starting at the first "http" line up to the next blank
  # line, then strip every whitespace char inside it — a real URL never
  # contains a literal space, so this safely undoes any inserted line wrap.
  url=$(awk '/http/{f=1} f{print} f && /^[[:space:]]*$/{exit}' "$logfile" | tr -d '[:space:]')
  if [ -n "$url" ]; then
    echo
    echo "Clean auth URL (paste this in a browser on any device, then bring back the code it gives you): $url"
  fi
  rm -f "$logfile"

  if [ -n "$status_cmd" ]; then
    echo
    echo "  -- checking login status --"
    # shellcheck disable=SC2086
    $status_cmd
  fi
}

cmd_auth() {
  local targets=() p a found unknown=()
  if [ "$#" -eq 0 ]; then
    targets=("${PROVIDERS[@]}")
  else
    for a in "$@"; do
      found=0
      for p in "${PROVIDERS[@]}"; do
        [ "$a" = "$p" ] && { targets+=("$a"); found=1; break; }
      done
      [ "$found" -eq 0 ] && unknown+=("$a")
    done
    if [ "${#unknown[@]}" -gt 0 ]; then
      echo "Unknown provider(s): ${unknown[*]}. Options: ${PROVIDERS[*]}"
      exit 1
    fi
  fi

  for p in "${targets[@]}"; do
    if ! provider_installed "$p"; then
      echo "$(provider_label "$p") — not installed"
      continue
    fi
    echo "== $(provider_label "$p") =="
    run_login_capture "$p"
    echo
  done
}

# ---------------------------------------------------------------------------
# status / menu
# ---------------------------------------------------------------------------

print_status_block() {
  local p="$1"
  printf '%s — last used %s\n' "$(provider_label "$p")" "$(fmt_ago "$(provider_last_used_epoch "$p")")"
  if [ "${#STATUS_ROWS[@]}" -eq 0 ]; then
    printf '  %s\n' "${STATUS_NOTE:-no data available}"
  else
    local row label used reset left
    for row in "${STATUS_ROWS[@]}"; do
      IFS='|' read -r label used reset <<< "$row"
      left=$((100 - used))
      printf '  %-16s %3d%% used   %3d%% left   resets %s\n' "$label" "$used" "$left" "$reset"
    done
  fi
  echo
}

render_progress() {
  local current="$1" total="$2" label="$3"
  [ -t 1 ] || return 0
  local pct=$((total > 0 ? current * 100 / total : 100))
  local bar_len=20
  local filled=$((total > 0 ? current * bar_len / total : 20))
  local empty=$((bar_len - filled))
  local bar=""
  local i
  for ((i=0; i<filled; i++)); do bar+="█"; done
  for ((i=0; i<empty; i++)); do bar+="░"; done
  printf '\r\033[K[%s] %3d%%  %s' "$bar" "$pct" "$label"
}

# Queries installed providers in parallel with an animated progress bar
probe_all_providers() {
  local -a installed=()
  local p
  for p in "${PROVIDERS[@]}"; do
    provider_installed "$p" && installed+=("$p")
  done
  local total=${#installed[@]}
  [ "$total" -eq 0 ] && return 0

  local tmpdir
  tmpdir=$(mktemp -d "$STATE_DIR/probe_XXXXXX")
  for p in "${installed[@]}"; do
    (
      provider_status "$p"
      {
        # %q (proper shell-escaping), not hand-rolled single-quotes — a
        # note like "couldn't read /usage (login expired?)" has both an
        # apostrophe and parens in it, which broke the naive '$VAR' form
        # outright (syntax error when this got sourced back in below).
        printf 'STATUS_PCT=%q\n' "$STATUS_PCT"
        printf 'STATUS_NOTE=%q\n' "$STATUS_NOTE"
        printf 'STATUS_ROWS=('
        for r in "${STATUS_ROWS[@]}"; do
          printf '%q ' "$r"
        done
        echo ')'
      } > "$tmpdir/$p.status"
    ) &
  done

  local done_count=0
  local -a remaining=("${installed[@]}")
  render_progress 0 "$total" "Connecting to AI providers..."

  while [ "$done_count" -lt "$total" ]; do
    local new_remaining=()
    for p in "${remaining[@]}"; do
      if [ -f "$tmpdir/$p.status" ]; then
        done_count=$((done_count + 1))
        render_progress "$done_count" "$total" "Checking $(provider_label "$p")..."
      else
        new_remaining+=("$p")
      fi
    done
    remaining=("${new_remaining[@]}")
    [ "$done_count" -lt "$total" ] && sleep 0.05
  done

  [ -t 1 ] && printf '\r\033[K'
  echo "$tmpdir"
}

cmd_status() {
  local tmpdir
  tmpdir=$(probe_all_providers)
  local p
  for p in "${PROVIDERS[@]}"; do
    if ! provider_installed "$p"; then
      printf '%s — not installed\n\n' "$(provider_label "$p")"
      continue
    fi
    if [ -n "$tmpdir" ] && [ -f "$tmpdir/$p.status" ]; then
      # shellcheck disable=SC1090
      source "$tmpdir/$p.status"
    else
      provider_status "$p"
    fi
    print_status_block "$p"
  done
  [ -n "$tmpdir" ] && rm -rf "$tmpdir"
}

# Builds the ranking into RANKED (array of "sort_pct|provider|pct|last|summary")
build_ranking() {
  RANKED=()
  local tmpdir
  tmpdir=$(probe_all_providers)
  local p
  for p in "${PROVIDERS[@]}"; do
    provider_installed "$p" || continue
    if [ -n "$tmpdir" ] && [ -f "$tmpdir/$p.status" ]; then
      # shellcheck disable=SC1090
      source "$tmpdir/$p.status"
    else
      provider_status "$p"
    fi
    local pct=$STATUS_PCT
    local sort_pct=$pct
    [ "$sort_pct" -lt 0 ] && sort_pct=50   # unknown: neither favored nor penalized
    local last summary
    last=$(provider_last_used_epoch "$p")
    summary=$(provider_summary)
    RANKED+=("$sort_pct|$p|$pct|$last|$summary")
  done
  [ -n "$tmpdir" ] && rm -rf "$tmpdir"
  # Fixed order (whatever order PROVIDERS lists them in) — no more sorting
  # by remaining quota. The "pick the one with the most headroom" advisor
  # is off; RANKED is really just "the installed list" now, name kept to
  # avoid touching every call site.
}

cmd_menu() {
  local yolo=0 cont=0 prompt=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --yolo) yolo=1; shift ;;
      --continue|-c) cont=1; shift ;;
      *) prompt="$prompt $1"; shift ;;
    esac
  done
  prompt="${prompt# }"

  build_ranking
  if [ "${#RANKED[@]}" -eq 0 ]; then
    echo "No AI installed. Run: $0 install"
    exit 1
  fi

  echo "Available:"
  echo
  local i=1
  declare -A MENU_PROVIDER
  for entry in "${RANKED[@]}"; do
    IFS='|' read -r sort_pct p pct last summary <<< "$entry"
    printf '  %d) %-22s %-55s last used %s\n' "$i" "$(provider_label "$p")" "$summary" "$(fmt_ago "$last")"
    MENU_PROVIDER[$i]=$p
    i=$((i+1))
  done
  echo
  read -r -p "Pick [1-$((i-1))] (Enter = first): " choice
  choice="${choice:-1}"
  local chosen="${MENU_PROVIDER[$choice]:-}"
  if [ -z "$chosen" ]; then
    echo "Invalid choice."
    exit 1
  fi

  local mode="$([ "$yolo" -eq 1 ] && echo yolo || echo auto)"
  [ "$cont" -eq 1 ] && mode="${mode}+continue"
  log_launch "$chosen" "$mode"
  launch_provider "$chosen" "$yolo" "$prompt" "$cont"
}

# Fixed per-provider "preset": the flags used on every launch so behavior
# stays predictable. --yolo/--continue only toggle within that preset, they
# don't change its shape.
launch_provider() {
  local p="$1" yolo="$2" prompt="$3" cont="${4:-0}"
  case "$p" in
    claude)
      # Default: --permission-mode auto — Claude Code's own classifier
      # (rules-based allow/soft_deny/hard_deny, see `claude auto-mode
      # --help`) decides what to auto-approve, instead of bypassing
      # permission checks entirely. --yolo keeps the full bypass available
      # for when that's actually wanted, same shape as Codex's --yolo.
      local args
      if [ "$yolo" -eq 1 ]; then
        args=(--dangerously-skip-permissions)
      else
        args=(--permission-mode auto)
      fi
      [ "$cont" -eq 1 ] && args+=(--continue)
      echo "Launching Claude Code (${args[*]})..."
      if [ -n "$prompt" ]; then
        exec claude "${args[@]}" "$prompt"
      else
        exec claude "${args[@]}"
      fi
      ;;
    codex)
      local args=()
      if [ "$yolo" -eq 1 ]; then
        echo "Launching Codex in YOLO mode (--dangerously-bypass-approvals-and-sandbox)..."
        args=(--dangerously-bypass-approvals-and-sandbox)
      else
        echo "Launching Codex in sandboxed automatic mode (--ask-for-approval never --sandbox workspace-write)..."
        args=(--ask-for-approval never --sandbox workspace-write)
      fi
      # Resume is a subcommand here, not a flag (`codex resume --last ...`),
      # unlike claude/agy where --continue slots in alongside the other args.
      local sub=()
      if [ "$cont" -eq 1 ]; then
        echo "  (resuming most recent session: codex resume --last)"
        sub=(resume --last)
      fi
      # exec'd, same as claude/agy — Codex is a full-screen TUI and checks
      # isatty(stdout) at startup. This used to pipe through `tee` instead
      # (to auto-detect a rate-limit message and save its exact reset
      # date), which broke that check outright: confirmed live, Codex
      # refused to start with "Error: stdout is not a terminal".
      # record_codex_ratelimit/the reactive rate-limit display in
      # provider_status_codex are unreachable now that nothing captures
      # launch output anymore — left in place rather than ripped out, in
      # case a safe way to capture output without breaking the tty (e.g. a
      # pty) is worth adding back later.
      if [ -n "$prompt" ]; then
        exec codex "${sub[@]}" "${args[@]}" "$prompt"
      else
        exec codex "${sub[@]}" "${args[@]}"
      fi
      ;;
    antigravity)
      local args=(--dangerously-skip-permissions)
      [ "$cont" -eq 1 ] && args+=(--continue)
      echo "Launching Antigravity (${args[*]})..."
      if [ -n "$prompt" ]; then
        exec agy "${args[@]}" --prompt-interactive "$prompt"
      else
        exec agy "${args[@]}"
      fi
      ;;
    grok)
      # Same preset shape as Claude: --permission-mode auto by default —
      # confirmed via `grok --help`, same enum as Claude's (default/
      # acceptEdits/auto/dontAsk/bypassPermissions/plan). --yolo swaps to
      # the full bypass value instead of a separate dangerous flag.
      local args
      if [ "$yolo" -eq 1 ]; then
        args=(--permission-mode bypassPermissions)
      else
        args=(--permission-mode auto)
      fi
      [ "$cont" -eq 1 ] && args+=(--continue)
      echo "Launching Grok Build (${args[*]})..."
      if [ -n "$prompt" ]; then
        exec grok "${args[@]}" "$prompt"
      else
        exec grok "${args[@]}"
      fi
      ;;
  esac
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

# --check-antigravity is a global switch, stripped here so it never reaches
# a subcommand as a stray positional arg. No --check-grok: see
# provider_status_grok() above for why there's nothing to gate.
args=()
for a in "$@"; do
  if [ "$a" = "--check-antigravity" ]; then
    CHECK_ANTIGRAVITY=1
  else
    args+=("$a")
  fi
done
set -- "${args[@]}"

case "${1:-}" in
  install|update) cmd_install ;;
  status) cmd_status ;;
  auth) shift; cmd_auth "$@" ;;
  check-antigravity) shift; cmd_check_antigravity "$@" ;;
  *) cmd_menu "$@" ;;
esac
