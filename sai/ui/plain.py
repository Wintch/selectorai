"""Numbered fallback menu: no tty, or the Textual UI couldn't be set up."""
from sai import health, providers
from sai.i18n import _prompt, t
from sai.providers.base import provider_summary
from sai.sysinfo import machine_status
from sai.timeutil import fmt_ago

_MISSING_STATUS = {"pct_used": None, "rows": [], "note": None, "kind": None}


def _print_rows(provider_ids, statuses, menu_provider, start):
    """Print one numbered row per provider, starting the running count at
    `start` — shared by both sections below so numbering stays continuous
    across the online/offline split (picking by number must still work for
    every provider, offline ones included)."""
    i = start
    for p in provider_ids:
        status = statuses.get(p, _MISSING_STATUS)
        summary = provider_summary(status)
        last = providers.last_used_epoch(p)
        print(f"  {i}) {providers.label(p):<22} {summary:<55} {t('last_used', ago=fmt_ago(last))}")
        menu_provider[i] = p
        i += 1
    return i


def run_plain_picker(provider_list, statuses):
    for line in machine_status():
        print(line)
    print(t("who_hint", cmd="selectorai.py status --who"))
    print()

    # Same grouping as sai/ui/picker.py's sectioned OptionList, done
    # textually instead: an "Available:" group for ONLINE/WARNING
    # providers, then — only if any exist — an offline group. No ⚠
    # marker here (unlike the picker's row label): provider_summary()
    # already surfaces the pct/quota numbers that made it WARNING, so
    # this menu doesn't need a second signal for the same fact.
    online_warn, offline = [], []
    for p in provider_list:
        state, _ = health.classify(p, statuses.get(p, _MISSING_STATUS))
        (offline if state == health.OFFLINE else online_warn).append(p)

    print(t("menu_available"))
    print()
    menu_provider = {}
    next_i = _print_rows(online_warn, statuses, menu_provider, start=1)

    if offline:
        print()
        print(t("health_section_offline"))
        print()
        _print_rows(offline, statuses, menu_provider, start=next_i)

    print()
    choice = (_prompt(t("menu_pick_prompt", n=len(provider_list))) or "").strip() or "1"
    try:
        return menu_provider[int(choice)]
    except (ValueError, KeyError):
        return None
