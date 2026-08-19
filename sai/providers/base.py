"""Shared helpers for provider modules, plus the status-dict shape contract
they all return (see docs/ARCHITECTURE.md's provider contract table):

    {"pct_used": int | None,        # worst-case % used across buckets
     "rows": [(label, pct_used, reset_info), ...],
     "note": str | None,            # shown when rows is empty
     "kind": "ok" | "auth-needed" | "not-checked" | "no-usage-api"}

`kind` classifies *why* a status looks the way it does, independent of the
rendered `note` text (which is localized and can't be pattern-matched
reliably by callers — see sai/cache.py's antigravity was_skipped check):
  - "ok": real numbers came back.
  - "auth-needed": login expired or sign-in required (Claude's
    login-expired /usage output, Antigravity's no-usage/sign-in-needed
    output).
  - "not-checked": the provider has a live check but it's gated off right
    now (Antigravity when --check-antigravity isn't set).
  - "no-usage-api": there's no usage API to call at all, gated or not
    (Codex's default no-saved-ratelimit path, Grok always).

The rendering helpers below (render_status_rows/provider_summary and
their private tree/grouping helpers) consume that same shape and are kept
here for the same reason: both sai/cli.py (plain `status` command) and
sai/ui/picker.py (detail panel) need them, and neither module may import
the other, so the shared consumer of the shape lives next to the shape
itself instead of in either caller.
"""
import re

from sai.i18n import t


def _extract(text, pattern, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


# Header/decoration line heuristics for parse_model_lines below. Not
# exhaustive by design — this is defensive parsing for output shapes that
# are UNVERIFIED (see sai/providers/antigravity.py and grok.py's
# list_models()), so it only strips things that are clearly not a model
# name rather than trying to enumerate every real header string.
_DECORATION_RE = re.compile(r"^[-=_*~#]+$")
_HEADER_WORDS = {"available models:", "available models", "models:", "model", "name"}


def parse_model_lines(text):
    """Defensively turn a `models`-subcommand's free-form stdout into a
    flat list of model name strings: strip each line, drop empty lines,
    drop obvious decoration (a line that's only "-"/"="/etc) or column
    headers, and keep everything else as-is. Shared by
    sai/providers/antigravity.py and grok.py, whose `models` output shape
    neither one has actually been run against yet (their bare invocation
    risks a real auth popup — see each module's list_models() docstring —
    so this was written against the *documented* "list models" behavior,
    not a captured real transcript)."""
    names = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _DECORATION_RE.match(line):
            continue
        if line.lower() in _HEADER_WORDS:
            continue
        # A short line ending in ":" reads as a section header ("Claude
        # models:"), not a model name — real model names/ids don't end
        # with a bare colon.
        if line.endswith(":") and len(line.split()) <= 3:
            continue
        names.append(line)
    return names


def _render_tree(header, rows):
    lines = [t("status_tree_header", label=header)]
    for i, (label, used, reset) in enumerate(rows):
        connector = "└─" if i == len(rows) - 1 else "├─"
        left = 100 - used
        lines.append(t("status_row", label=f"{connector} {label}", used=used, left=left, reset=reset))
    return lines


def _render_claude_rows(rows):
    """Session stays a flat row, but Weekly and Weekly (Fable) are two
    parallel quotas for different model pools under the same weekly window
    — same shape as a directory with two files in it, or two branches off
    one trunk. Grouping them that way beats two same-looking flat rows."""
    lines = []
    by_label = {label: (used, reset) for label, used, reset in rows}
    weekly_label = t("label_weekly")
    fable_label = t("label_weekly_fable")

    for label, used, reset in rows:
        if label in (weekly_label, fable_label):
            continue
        left = 100 - used
        lines.append(t("status_row", label=label, used=used, left=left, reset=reset))

    branches = []
    if weekly_label in by_label:
        branches.append((t("label_weekly_all"), *by_label[weekly_label]))
    if fable_label in by_label:
        branches.append((t("label_fable_short"), *by_label[fable_label]))
    if branches:
        lines.extend(_render_tree(weekly_label, branches))
    return lines


def render_status_rows(p, status):
    """Same idea as _render_claude_rows, applied to Antigravity: its two
    buckets (Gemini Models / Claude and GPT models) are equally parallel —
    they just don't share a common label prefix to group under, so the
    header is a generic one instead of a real shared label."""
    if not status["rows"]:
        return [f"  {status['note'] or t('status_no_data')}"]
    if p == "claude":
        return _render_claude_rows(status["rows"])
    if p == "antigravity" and len(status["rows"]) > 1:
        return _render_tree(t("label_weekly_limits"), status["rows"])
    lines = []
    for label, used, reset in status["rows"]:
        left = 100 - used
        lines.append(t("status_row", label=label, used=used, left=left, reset=reset))
    if p == "grok":
        # Real numbers came back (this branch only runs when status["rows"]
        # is non-empty), but confirmed live that the bar itself isn't
        # trustworthy: a free account got cut off entirely while this same
        # "Weekly limit (Free)" reading still said 0% used — whatever
        # undocumented limit actually stops you doesn't appear to be the
        # same thing this popup tab tracks. Always shown, not just on a
        # skipped/failed probe, since the risk is specifically in trusting
        # a number that LOOKS fine.
        lines.append(f"  {t('grok_experimental_caveat')}")
    return lines


def provider_summary(status):
    pct = status["pct_used"]
    if pct is None:
        return status["note"] or t("summary_no_data")
    left = 100 - pct
    label, reset = None, None
    for l, u, r in status["rows"]:
        if u == pct:
            label, reset = l, r
            break
    if reset:
        reset = re.sub(r" *\([^)]*\)\s*$", "", reset)
    if label:
        return t("summary_both", left=left, pct=pct, label=label, reset=reset or t("unknown"))
    return t("summary_both_nolabel", left=left, pct=pct)
