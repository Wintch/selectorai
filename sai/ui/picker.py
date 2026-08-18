"""Textual picker app: sections (title, sysinfo, option list, detail
panel), key handling, and the restart sentinels sai.cli.cmd_menu uses to
tell "language/theme changed, reopen the picker" apart from "a provider
was chosen" or "the user quit".

`textual` is imported lazily, inside textual_available()/run_picker()
rather than at module scope, on purpose: this module must stay importable
under the plain system python3 (no textual installed) for
tests/test_imports.py, exactly like the pre-split script only imported
textual inside its picker function.
"""
from sai import health, models, providers
from sai.bigfont import render_big
from sai.i18n import LANG_CODES, get_lang, set_lang, t
from sai.paths import LANG_FILE, THEME_FILE
from sai.providers.base import render_status_rows
from sai.sysinfo import machine_status
from sai.themes import current_theme, list_themes
from sai.timeutil import fmt_ago

# Sentinel results for run_picker/cmd_menu: distinguishable from a real
# provider id (a short lowercase key like "claude") or None (deliberate
# quit), so cmd_menu knows to reload and reopen the picker instead of
# treating the result as a launch choice.
_RESTART_LANG = "\x00restart-lang\x00"
_RESTART_THEME = "\x00restart-theme\x00"

# Same sentinel idea, different consumer: cmd_menu execs `tmux
# attach-session` instead of relaunching a provider when it sees this one
# back (see sai.session.wrap_launch's module docstring for why that exec,
# not another wrap_launch call, is correct here — the session already
# exists). Never collides with a real provider id (registry keys are
# short lowercase names like "claude", never containing NUL).
_REATTACH = "\x00reattach\x00"


def textual_available():
    try:
        import textual  # noqa: F401

        return True
    except ImportError:
        return False


def _sysinfo_markup(lines):
    """Wrap the "⚠ ..." tail of a warning line (disk/memory low-space,
    high-usage) in Rich markup so it stays yellow regardless of what color
    a theme gives #sysinfo as a whole — CSS can't target a substring
    inside one Static widget's text, only Rich markup embedded in the
    content can. Textual-only: the plain `status`/fallback-menu output
    uses machine_status() directly, unmodified, since raw "[yellow]" tags
    would just print as literal text there instead of being interpreted."""
    out = []
    for line in lines:
        idx = line.find("⚠")
        out.append(f"{line[:idx]}[yellow]{line[idx:]}[/yellow]" if idx != -1 else line)
    return out


def _health_for(p, statuses, service_states):
    """statuses.get(p) can in principle be None (a provider absent from
    the fetched-statuses map) even though every real call site builds
    `statuses` from the very same provider_list — defensive, not expected
    in practice. None is treated as ONLINE/no-reason rather than raising,
    matching health.classify's own "unknown ≠ unhealthy" rule.
    service_states.get(p) is fine to be missing/None too — that's
    classify()'s normal "no external signal" case, not an error."""
    status = statuses.get(p)
    if status is None:
        return health.ONLINE, None
    return health.classify(p, status, service_states.get(p))


def _build_app(provider_list, statuses, service_states, theme_path, reattach=None):
    """Construct the picker App instance without running it. Split out of
    run_picker() below purely so tests/test_picker_headless.py can drive it
    through Textual's own `app.run_test()` pilot (which needs an
    unstarted instance, not the blocking `.run()` call) instead of a real
    terminal — run_picker()'s observable behavior is unchanged, it's still
    exactly `_build_app(...).run()`.

    reattach: None, or {"windows": [(name, ago_str), ...], "peek_lines":
    [...]} built by sai.cli (see its _reattach_descriptor()) from
    sai.session's tmux calls — this module makes no tmux calls of its own,
    it only renders whatever descriptor it's handed. When present, a
    special reattach row is shown first in the OptionList."""
    from textual.app import App, ComposeResult
    from textual.containers import Vertical
    from textual.widgets import Footer, OptionList, Static
    from textual.widgets.option_list import Option

    class _SelectorApp(App):
        # The "front" — an external stylesheet, not inline CSS, so a whole
        # different look (see themes/*.tcss) is a file swap, not a code
        # change. This class only owns behavior: widget structure, key
        # handling, what happens on selection.
        CSS_PATH = str(theme_path)
        BINDINGS = [
            ("up", "cursor_up", t("menu_move")),
            ("down", "cursor_down", t("menu_move")),
            ("enter", "select", t("menu_select")),
            ("l", "cycle_lang", t("menu_lang")),
            ("t", "cycle_theme", t("menu_theme")),
            ("q", "quit_app", t("menu_quit")),
            ("escape", "quit_app", t("menu_quit")),
        ]

        def __init__(self):
            super().__init__()
            self.chosen = None
            self._cursor_on = True

        def compose(self) -> ComposeResult:
            yield Static("\n".join(render_big("SELECTOR AI")), id="title")
            with Vertical(id="sysbox"):
                yield Static(f"{t('menu_system_ready')} █", id="sysline")
                yield Static("\n".join(_sysinfo_markup(machine_status())), id="sysinfo")
            # Sectioned: ONLINE + WARNING providers first (last-used order
            # preserved within each section — provider_list already comes
            # in that order from sai.cli.build_provider_list), then, only
            # if any OFFLINE providers exist, a disabled separator row
            # (heading text, not a choice) followed by the OFFLINE ones.
            # OFFLINE providers stay NORMAL selectable options on purpose:
            # our data can be stale, so the user may still want to launch
            # one anyway — the detail panel explains why it's listed
            # offline instead of just hiding it.
            online_warn, offline = [], []
            for p in provider_list:
                state, _ = _health_for(p, statuses, service_states)
                (offline if state == health.OFFLINE else online_warn).append((p, state))

            options = []
            # Reattach offer goes first, before any provider row — it's
            # "resume what's already running," a strictly higher-priority
            # choice than "start something new" whenever it's on offer at
            # all (see sai.cli._reattach_descriptor: only built when a
            # live tmux session actually exists).
            if reattach:
                names = ", ".join(name for name, _ in reattach["windows"])
                ago = reattach["windows"][0][1]
                options.append(Option(t("session_reattach_label", names=names, ago=ago), id=_REATTACH))
            for p, state in online_warn:
                label = providers.label(p)
                if state == health.WARNING:
                    label += " ⚠"
                options.append(Option(label, id=p))
            if offline:
                # disabled=True is exactly the right primitive here (see
                # textual 8.2.8's widgets/_option_list.py): a disabled
                # Option is skipped by both action_cursor_up/_down
                # (find_next_enabled) and mouse clicks, and action_first()
                # skips it too on initial mount — so it behaves as a
                # heading, never a choice, with no extra key handling
                # needed here.
                options.append(Option(t("health_section_offline"), disabled=True))
                for p, _ in offline:
                    options.append(Option(providers.label(p), id=p))

            # Render order minus the disabled separator — this is what
            # textual's own action_first() actually highlights on mount,
            # which is no longer necessarily provider_list[0] once an
            # OFFLINE provider that would otherwise sort first (most
            # recently used) gets pushed to the back. on_mount uses this
            # instead of provider_list[0] for that reason.
            self._flat_ids = ([_REATTACH] if reattach else []) + [p for p, _ in online_warn] + [
                p for p, _ in offline
            ]

            # Deliberately simple: just the name. Detailed stats (quota
            # breakdown, tree, countdown, last used) only show for whichever
            # one is currently highlighted, in the detail panel below —
            # not crammed into every row at once.
            yield OptionList(*options, id="picker")
            yield Static(id="detail")
            yield Footer()

        def on_mount(self):
            self.query_one("#picker", OptionList).focus()
            self._update_detail(self._flat_ids[0])

            # Power-on flicker: title fades in rather than snapping to full
            # brightness, like an old CRT warming up.
            title = self.query_one("#title", Static)
            title.styles.opacity = 0.0
            title.styles.animate("opacity", value=1.0, duration=0.6, easing="out_cubic")

            # Blinking cursor block next to the system-ready line, classic
            # terminal cadence (~530ms, matches typical terminal defaults).
            self.set_interval(0.53, self._blink_cursor)

        def _blink_cursor(self):
            self._cursor_on = not self._cursor_on
            block = "█" if self._cursor_on else " "
            self.query_one("#sysline", Static).update(f"{t('menu_system_ready')} {block}")

        def _update_detail(self, p):
            if p == _REATTACH:
                # peek_lines is tmux capture-pane output (see
                # sai.session.peek) — best-effort and can legitimately be
                # empty (dead pane, capture failed), hence the fallback
                # line instead of an empty detail panel.
                lines = [t("session_reattach_detail_header")]
                lines += reattach["peek_lines"] or [t("session_reattach_no_peek")]
                self.query_one("#detail", Static).update("\n".join(lines))
                return
            # No big block-letter name repeat here anymore — the OptionList
            # row already shows which provider is highlighted, so this
            # panel goes straight to what it actually adds: the stats.
            status = statuses.get(p)
            state, reason_key = _health_for(p, statuses, service_states)
            health_line = health.render_health_line(state, reason_key)
            lines = [health_line] + (render_status_rows(p, status) if status is not None else [])
            # Models: read-only from cache (see sai.models' module
            # docstring) — showing this line never triggers a fetch, so a
            # provider nobody's ever run `models` for just shows nothing.
            models_line = models.models_line(p)
            if models_line:
                lines.append(f"  {models_line}")
            last = providers.last_used_epoch(p)
            lines = lines + ["", t("last_used", ago=fmt_ago(last))]
            self.query_one("#detail", Static).update("\n".join(lines))

        def on_option_list_option_highlighted(self, event):
            if event.option.id:
                self._update_detail(event.option.id)

        def on_option_list_option_selected(self, event):
            self.chosen = event.option.id
            self.exit(result=self.chosen)

        def action_cursor_up(self):
            self.query_one("#picker", OptionList).action_cursor_up()

        def action_cursor_down(self):
            self.query_one("#picker", OptionList).action_cursor_down()

        def action_select(self):
            self.query_one("#picker", OptionList).action_select()

        def action_quit_app(self):
            self.exit(result=None)

        def action_cycle_lang(self):
            cur = get_lang()
            idx = LANG_CODES.index(cur) if cur in LANG_CODES else -1
            new_lang = LANG_CODES[(idx + 1) % len(LANG_CODES)]
            LANG_FILE.write_text(new_lang)
            set_lang(new_lang)
            self.exit(result=_RESTART_LANG)

        def action_cycle_theme(self):
            themes = list_themes()
            cur = current_theme()
            idx = themes.index(cur) if cur in themes else -1
            new_theme = themes[(idx + 1) % len(themes)]
            THEME_FILE.write_text(new_theme)
            self.exit(result=_RESTART_THEME)

    return _SelectorApp()


def run_picker(provider_list, statuses, service_states, theme_path, reattach=None):
    """provider_list: order list of provider keys (see sai.cli.build_provider_list).
    statuses: {p: status dict} from fetch_all_statuses, used to render the
    detail panel. service_states: {p: "operational"|"degraded"|"outage"|
    None} from fetch_service_states_cached, folded into classify() for
    both the health line and the ONLINE/WARNING vs OFFLINE grouping.
    reattach: see _build_app's docstring — None or a descriptor dict.
    Returns a provider id, None (deliberate quit), _REATTACH (see
    sai.cli.cmd_menu, which execs `tmux attach-session` on seeing this
    back), or one of the _RESTART_* sentinels (language/theme changed from
    inside the picker — cmd_menu reloads and calls this again)."""
    return _build_app(provider_list, statuses, service_states, theme_path, reattach).run()
