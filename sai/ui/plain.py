"""Numbered fallback menu: no tty, or the Textual UI couldn't be set up."""
from sai import health, models, providers
from sai.i18n import _prompt, t
from sai.providers.base import provider_summary
from sai.sysinfo import machine_status
from sai.timeutil import fmt_ago
from sai.ui.picker import _REATTACH

_MISSING_STATUS = {"pct_used": None, "rows": [], "note": None, "kind": None}


def _print_rows(provider_ids, statuses, classified, menu_provider, start):
    """Print one numbered row per provider, starting the running count at
    `start` — shared by both sections below so numbering stays continuous
    across the online/offline split (picking by number must still work for
    every provider, offline ones included). `classified` is {p: (state,
    reason_key)}, computed once by the caller (same classify() call it
    already needs for the online/offline grouping) and reused here so the
    health word/reason and the section a provider lands in can never
    disagree with each other."""
    i = start
    for p in provider_ids:
        status = statuses.get(p, _MISSING_STATUS)
        summary = provider_summary(status)
        last = providers.last_used_epoch(p)
        # 25, not 22: the longest LABEL is now "Claude Code (Anthropic)"
        # (23 chars, see sai/providers/claude.py) since every provider
        # label gained a "(Parent Company)" suffix — widened to keep the
        # same >=2-space gap before the summary column that 22 gave the
        # old, shorter labels.
        print(f"  {i}) {providers.label(p):<25} {summary:<55} {t('last_used', ago=fmt_ago(last))}")
        # Indented detail lines below the numbered row, same information
        # the Textual picker's detail panel and `status` command show
        # (see sai/ui/picker.py's _update_detail, sai/cli.py's
        # print_status_block) — the plain menu is the one other surface
        # a provider's health/models can appear on, and it shouldn't be
        # strictly less informative than either of those just because
        # there's no tty for Textual.
        state, reason_key = classified[p]
        print(f"       {health.render_health_line(state, reason_key)}")
        models_line = models.models_line(p)
        if models_line:
            print(f"       {models_line}")
        if p == "grok" and status["rows"]:
            # Same caveat sai/providers/base.py's render_status_rows()
            # attaches for the Textual detail panel and `status` command —
            # this is the plain-menu's own render path (provider_summary()
            # above, not render_status_rows), so it needs its own copy of
            # the same warning rather than inheriting it for free.
            print(f"       {t('grok_experimental_caveat')}")
        menu_provider[i] = p
        i += 1
    return i


def run_plain_picker(provider_list, statuses, service_states, reattach=None):
    """reattach: None, or the {"windows": [(name, ago_str), ...],
    "peek_lines": [...]} descriptor sai.cli._reattach_descriptor()
    builds from sai.session's tmux calls — this module makes no tmux
    calls of its own, same purity rule as sai/ui/picker.py. When present,
    it's offered as entry "0)", ahead of the numbered provider rows
    (which start at 1, unchanged) — same priority-first placement as the
    Textual picker's reattach row."""
    for line in machine_status():
        print(line)
    print(t("who_hint", cmd="selectorai.py status --who"))
    print()

    menu_provider = {}
    if reattach:
        names = ", ".join(name for name, _ in reattach["windows"])
        ago = reattach["windows"][0][1]
        print(f"  0) {t('session_reattach_label', names=names, ago=ago)}")
        for line in reattach["peek_lines"] or [t("session_reattach_no_peek")]:
            print(f"       {line}")
        menu_provider[0] = _REATTACH
        print()

    # Same grouping as sai/ui/picker.py's sectioned OptionList, done
    # textually instead: an "Available:" group for ONLINE/WARNING
    # providers, then — only if any exist — an offline group. No ⚠
    # marker here (unlike the picker's row label): provider_summary()
    # already surfaces the pct/quota numbers that made it WARNING, and
    # each row's own health line (see _print_rows) now spells out the
    # ONLINE/WARNING/OFFLINE word and reason explicitly anyway.
    classified = {
        p: health.classify(p, statuses.get(p, _MISSING_STATUS), service_states.get(p))
        for p in provider_list
    }
    online_warn, offline = [], []
    for p in provider_list:
        state, _ = classified[p]
        (offline if state == health.OFFLINE else online_warn).append(p)

    print(t("menu_available"))
    print()
    next_i = _print_rows(online_warn, statuses, classified, menu_provider, start=1)

    if offline:
        print()
        print(t("health_section_offline"))
        print()
        _print_rows(offline, statuses, classified, menu_provider, start=next_i)

    print()
    choice = (_prompt(t("menu_pick_prompt", n=len(provider_list))) or "").strip() or "1"
    try:
        return menu_provider[int(choice)]
    except (ValueError, KeyError):
        return None
