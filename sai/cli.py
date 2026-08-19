"""main(): global flags, dispatch, cmd_menu, cmd_status, venv bootstrap/re-exec.

This is the only module selectorai.py (the thin entry point) imports.
"""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from sai import auth, cache, health, models, providers, session
from sai.i18n import cmd_lang, resolve_lang, set_lang, t
from sai.paths import CHECK_ANTIGRAVITY_FILE, CHECK_GROK_FILE, ENTRY_SCRIPT, LAUNCH_LOG, STATE_DIR, THEMES_DIR
from sai.providers import antigravity, grok
from sai.providers.base import render_status_rows
from sai.sysinfo import machine_status, who_status
from sai.themes import cmd_theme, current_theme
from sai.timeutil import fmt_ago
from sai.ui.picker import _REATTACH, _RESTART_LANG, _RESTART_THEME, run_picker, textual_available
from sai.ui.plain import run_plain_picker

# ---------------------------------------------------------------------------
# install / update
# ---------------------------------------------------------------------------


def cmd_install():
    for p in providers.ORDER:
        print(f"== {providers.label(p)} ==")
        if providers.installed(p):
            print(t("install_updating"))
            providers.update(p)
        else:
            print(t("install_installing"))
            providers.install(p)
        print()


# ---------------------------------------------------------------------------
# check-antigravity — persisted opt-in toggle for Antigravity's live probe.
# ---------------------------------------------------------------------------


def cmd_check_antigravity(argv):
    if argv and argv[0] == "on":
        CHECK_ANTIGRAVITY_FILE.write_text("1")
        print(
            "Antigravity live usage check: ON by default now — every `status`/menu run "
            "will call `agy -p \"/usage\"`.\nReminder: Antigravity's own session handling "
            "is flaky upstream (antigravity-cli#57/#18) — even logged in, this can still "
            "pop a fresh Google login prompt on any given run, not just the first one.\n"
            "Turn it back off any time: ./selectorai.py check-antigravity off"
        )
    elif argv and argv[0] == "off":
        CHECK_ANTIGRAVITY_FILE.unlink(missing_ok=True)
        print(
            "Antigravity live usage check: OFF by default (back to opt-in only — pass "
            "--check-antigravity for a single run instead)."
        )
    else:
        state = "on" if CHECK_ANTIGRAVITY_FILE.exists() else "off"
        print(f"Antigravity live usage check is currently: {state}")
        print("  ./selectorai.py check-antigravity on   # persist: always probe")
        print("  ./selectorai.py check-antigravity off  # persist: opt-in only (default)")
        print("  ./selectorai.py --check-antigravity    # probe just for this one run, don't persist")


# ---------------------------------------------------------------------------
# check-grok — persisted opt-in toggle for Grok's live tmux-driven probe.
# ---------------------------------------------------------------------------


def cmd_check_grok(argv):
    if argv and argv[0] == "on":
        CHECK_GROK_FILE.write_text("1")
        print(
            "Grok live usage check: ON by default now — every `status`/menu run will "
            "open a throwaway `grok` session in tmux to read its Usage limit tab "
            "(see sai.providers.grok._live_usage_limit).\nThis takes several seconds "
            "(cold start can be ~15-20s) and depends on grok's current TUI layout, "
            "unlike the other providers' checks.\n"
            "Turn it back off any time: ./selectorai.py check-grok off"
        )
    elif argv and argv[0] == "off":
        CHECK_GROK_FILE.unlink(missing_ok=True)
        print(
            "Grok live usage check: OFF by default (back to opt-in only — pass "
            "--check-grok for a single run instead)."
        )
    else:
        state = "on" if CHECK_GROK_FILE.exists() else "off"
        print(f"Grok live usage check is currently: {state}")
        print("  ./selectorai.py check-grok on   # persist: always probe")
        print("  ./selectorai.py check-grok off  # persist: opt-in only (default)")
        print("  ./selectorai.py --check-grok    # probe just for this one run, don't persist")


# ---------------------------------------------------------------------------
# status / menu
# ---------------------------------------------------------------------------


def log_launch(provider, mode):
    with open(LAUNCH_LOG, "a") as f:
        f.write(f"{int(time.time())}\t{provider}\t{mode}\n")


def print_status_block(p, status, service_state):
    last = providers.last_used_epoch(p)
    print(t("status_last_used", label=providers.label(p), ago=fmt_ago(last)))
    state, reason_key = health.classify(p, status, service_state)
    print(f"  {health.render_health_line(state, reason_key)}")
    for line in render_status_rows(p, status):
        print(line)
    line = models.models_line(p)
    if line:
        print(f"  {line}")
    print()


def _fetch_statuses_and_services(installed, force_refresh):
    """Runs the quota-status probe and the service-status probe at the
    same time (two threads, not two sequential blocking calls) so wiring
    in the service check doesn't add wall time on top of what
    fetch_all_statuses already took by itself — see docs/ARCHITECTURE.md's
    health.py entry. Both callers below (cmd_status, build_provider_list)
    need exactly this pair, so it's factored out here instead of repeated."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_statuses = ex.submit(cache.fetch_all_statuses, installed, force_refresh, True)
        fut_services = ex.submit(cache.fetch_service_states_cached, installed, force_refresh)
        return fut_statuses.result(), fut_services.result()


def cmd_status(args, force_refresh=False):
    who_flag = "--who" in args

    for line in machine_status():
        print(line)
    if who_flag:
        for line in who_status():
            print(line)
    else:
        print(t("who_hint", cmd="selectorai.py status --who"))
    print()

    installed = [p for p in providers.ORDER if providers.installed(p)]
    statuses, service_states = _fetch_statuses_and_services(installed, force_refresh)

    for p in providers.ORDER:
        if not providers.installed(p):
            print(t("status_not_installed", label=providers.label(p)) + "\n")
            continue
        print_status_block(p, statuses[p], service_states.get(p))


def build_provider_list(force_refresh=False):
    """Sorted by last-used, most recent first (then the next-most-recent,
    and so on) — not the old quota-based "advisor" ranking (that stays
    off), just recency, which is simpler to predict: whatever you touched
    last is always at the top. Ties (e.g. two never-used providers) keep
    providers.ORDER's own order. Returns (providers, statuses,
    service_states) — statuses is {p: status dict}, service_states is
    {p: "operational"|"degraded"|"outage"|None}, used by both the plain
    picker's grouping and the Textual picker's detail panel/grouping."""
    installed = [p for p in providers.ORDER if providers.installed(p)]
    statuses, service_states = _fetch_statuses_and_services(installed, force_refresh)
    installed.sort(key=lambda p: providers.last_used_epoch(p), reverse=True)
    return installed, statuses, service_states


def _reattach_descriptor():
    """None, or {"windows": [(name, ago_str), ...], "peek_lines": [...]}
    for whichever window was most recently active — the shape both
    sai.ui.picker and sai.ui.plain render (they make no tmux calls of
    their own, see each module's docstring). None whenever there's
    nothing to reattach to: tmux missing, the feature toggled off, or no
    live `selectorai` tmux session with at least one window.

    live-unverified: exercises sai.session's tmux-facing calls end to
    end, none of which have run against a real tmux binary on this
    machine — see sai/session.py's module docstring."""
    if not (session.available() and session.enabled()):
        return None
    windows = session.live_windows()
    if not windows:
        return None
    windows.sort(key=lambda w: w[1], reverse=True)  # most recently active first
    most_recent_name = windows[0][0]
    return {
        "windows": [(name, fmt_ago(epoch)) for name, epoch in windows],
        "peek_lines": session.peek(most_recent_name),
    }


def _bootstrap_textual_venv():
    """Create ~/.selectorai/venv with `textual` installed, if not already
    there. Fully isolated (no system-wide changes, no sudo) — this machine
    has no bare `pip` (Debian's externally-managed-environment policy), so a
    dedicated venv is the correct way to add this, same idea as `pipx`.
    Returns the venv's python executable path, or None on any failure."""
    venv_dir = STATE_DIR / "venv"
    venv_python = venv_dir / "bin" / "python3"
    if venv_python.exists():
        r = subprocess.run([str(venv_python), "-c", "import textual"], stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            return venv_python
    print(t("menu_installing_ui"))
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)], check=True, stderr=subprocess.DEVNULL
        )
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--quiet", "textual"], check=True
        )
        return venv_python
    except Exception:
        return None


def cmd_menu(argv, force_refresh=False):
    yolo, cont = False, False
    prompt_parts = []
    for a in argv:
        if a == "--yolo":
            yolo = True
        elif a in ("--continue", "-c"):
            cont = True
        else:
            prompt_parts.append(a)
    prompt = " ".join(prompt_parts)

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    theme_name = current_theme() if interactive else None
    use_textual = False
    if interactive and not theme_name:
        print(f"No themes found under {THEMES_DIR}/ — using the plain menu instead.")
    elif interactive:
        if textual_available():
            use_textual = True
        else:
            venv_python = _bootstrap_textual_venv()
            if venv_python:
                # Re-exec the entry script under the venv interpreter — not
                # sai/cli.py itself. os.execv needs a real runnable file,
                # and this module isn't one; ENTRY_SCRIPT (selectorai.py at
                # the repo root) is the thing `python3 <path>` can run.
                os.execv(str(venv_python), [str(venv_python), str(ENTRY_SCRIPT)] + sys.argv[1:])
            print(t("menu_ui_failed"))

    provider_list, statuses, service_states = build_provider_list(force_refresh=force_refresh)
    if not provider_list:
        print(t("menu_none_installed", cmd=sys.argv[0]))
        sys.exit(1)

    chosen = None
    if use_textual:
        # L/T inside the picker cycle language/theme, persist the choice,
        # and hand back a sentinel instead of a provider id — loop and
        # reopen the picker instead of treating that as a launch pick. A
        # theme change alone doesn't need fresh data, just a different
        # stylesheet; a language change does, since note/label text is
        # already rendered into `statuses` by the time it gets here.
        while True:
            theme_path = THEMES_DIR / f"{current_theme()}.tcss"
            # Recomputed every loop iteration (cheap: at most two tmux
            # subprocess calls, see sai.session.live_windows/peek), not
            # hoisted above the loop — a language/theme restart reopens
            # the same picker in place, and the reattach offer should
            # reflect the session's live state at that moment, same as
            # provider statuses already do on a lang restart.
            reattach = _reattach_descriptor()
            result = run_picker(provider_list, statuses, service_states, theme_path, reattach=reattach)
            if result == _RESTART_THEME:
                continue
            if result == _RESTART_LANG:
                provider_list, statuses, service_states = build_provider_list(force_refresh=True)
                continue
            chosen = result
            break
        # `chosen is None` here means the user deliberately quit (q/Esc),
        # not a failure — exit quietly instead of falling through to the
        # plain-text picker as if nothing happened.
        if chosen is None:
            sys.exit(0)
    else:
        reattach = _reattach_descriptor()
        chosen = run_plain_picker(provider_list, statuses, service_states, reattach=reattach)
        if chosen is None:
            print(t("menu_invalid"))
            sys.exit(1)

    if chosen == _REATTACH:
        # Same "exec'd, never piped" rule as provider launches (see
        # docs/ARCHITECTURE.md rule 3) — tmux attach-session takes over
        # this terminal exactly like the CLIs it wraps. Never returns on
        # success; no log_launch call here, this isn't a new launch.
        # live-unverified: see sai/session.py's module docstring.
        os.execvp("tmux", ["tmux", "attach-session", "-t", session.SESSION_NAME])

    mode = "yolo" if yolo else "auto"
    if cont:
        mode += "+continue"
    if session.should_wrap():
        mode += "+tmux"
    log_launch(chosen, mode)
    providers.launch(chosen, yolo, prompt, cont)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Early re-exec into the dedicated venv if available, avoiding dual
    # startup overhead. Target ENTRY_SCRIPT (selectorai.py), never this
    # file — sai/cli.py can't be handed to `python3 <path>` as a script.
    venv_python = STATE_DIR / "venv" / "bin" / "python3"
    if venv_python.exists() and sys.executable != str(venv_python):
        try:
            os.execv(str(venv_python), [str(venv_python), str(ENTRY_SCRIPT)] + sys.argv[1:])
        except Exception:
            pass

    argv = sys.argv[1:]

    # --lang/--lang=xx, --check-antigravity, --check-grok, and
    # --refresh/-r/--no-cache are global overrides.
    lang_override = None
    check_antigravity_flag = False
    check_grok_flag = False
    force_refresh = False
    filtered = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--lang" and i + 1 < len(argv):
            lang_override = argv[i + 1]
            i += 2
            continue
        if a.startswith("--lang="):
            lang_override = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--check-antigravity":
            check_antigravity_flag = True
            i += 1
            continue
        if a == "--check-grok":
            check_grok_flag = True
            i += 1
            continue
        if a in ("--refresh", "-r", "--no-cache"):
            force_refresh = True
            i += 1
            continue
        filtered.append(a)
        i += 1
    argv = filtered

    # Flag above is a one-off, this-run-only override. Absent that, fall
    # back to the persisted preference (`check-antigravity on/off`,
    # `check-grok on/off`).
    if not check_antigravity_flag and CHECK_ANTIGRAVITY_FILE.exists():
        check_antigravity_flag = True
    antigravity.set_check_enabled(check_antigravity_flag)
    if not check_grok_flag and CHECK_GROK_FILE.exists():
        check_grok_flag = True
    grok.set_check_enabled(check_grok_flag)

    set_lang(resolve_lang(lang_override))

    if argv and argv[0] == "lang":
        cmd_lang(argv[1:])
    elif argv and argv[0] in ("install", "update"):
        cmd_install()
    elif argv and argv[0] == "status":
        cmd_status(argv[1:], force_refresh=force_refresh)
    elif argv and argv[0] == "auth":
        auth.cmd_auth(argv[1:])
    elif argv and argv[0] == "check-antigravity":
        cmd_check_antigravity(argv[1:])
    elif argv and argv[0] == "check-grok":
        cmd_check_grok(argv[1:])
    elif argv and argv[0] == "background":
        session.cmd_background(argv[1:])
    elif argv and argv[0] == "models":
        models.cmd_models(argv[1:])
    elif argv and argv[0] == "theme":
        cmd_theme(argv[1:])
    elif argv and argv[0] == "setup":
        # Deferred import, not top-level: sai/installer.py imports
        # cmd_status from this module to reuse it (see installer.py's
        # module docstring) — a top-level import here would be a real
        # import cycle, since this module wouldn't finish defining
        # cmd_status before sai.installer needed it.
        from sai.installer import cmd_setup

        cmd_setup(argv[1:])
    else:
        cmd_menu(argv, force_refresh=force_refresh)
