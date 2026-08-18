"""cmd_setup: guided end-to-end onboarding — `./selectorai.py setup`.

A linear walkthrough of every other subcommand, in the order a brand-new
user would actually want them (language first, so the rest of the flow
speaks their language; providers; auth; the risky Antigravity check;
tmux; theme; models; a final status refresh). Every step is skippable
(Enter/N moves on) and reuses the real command it's offering rather than
re-implementing it — see each step below for exactly which function.

Interactive-only, like `auth`/`lang`/`theme`'s own interactive paths: it
calls `input()` through sai.i18n._prompt, so stdin+stdout must both be a
real tty. The one exception is `--dry-run`, which answers every prompt
'no' without ever calling input() and prints what each step WOULD have
run instead of running it — this is what tests/test_installer.py and the
README exercise, since nothing else in this codebase is allowed to spawn
`claude`/`codex`/`agy`/`grok` or write real prefs from an automated run.

Import note: this module imports `cmd_status` from sai.cli (step 9 below)
to reuse its status-block rendering instead of duplicating it. sai/cli.py
therefore imports `cmd_setup` from here with a *deferred* import inside
main()'s dispatch, not at module load time — a top-level import on both
sides would be a real cycle (sai.cli would need sai.installer fully built
before it finishes defining cmd_status, which sai.installer needs).
"""
import subprocess
import sys

from sai import auth, providers, session
from sai.i18n import _prompt, cmd_lang, t
from sai.models import cmd_models
from sai.paths import CHECK_ANTIGRAVITY_FILE
from sai.sysinfo import machine_status
from sai.themes import cmd_theme

# Providers whose LOGIN_STATUS_CMD exists and is confirmed safe to run
# non-interactively (see docs/ARCHITECTURE.md's provider contract table
# and each sai/providers/<name>.py module) — read from the registry
# itself in the loop below, this constant isn't needed; kept out on
# purpose so a future provider gaining/losing a status command doesn't
# need a second place updated.


def _offer(dry_run, ask_key, would_key, **kwargs):
    """The one gate every skippable step goes through. Interactive: prints
    an i18n'd y/N question and returns whether the answer was yes.
    --dry-run: never calls input() at all (this must stay non-interactive
    end to end), instead prints the i18n'd "here's what would happen"
    line for the same step and always returns False, so the step's real
    action (subprocess, file write, `input()` of its own inside a reused
    command) never runs."""
    if dry_run:
        print(t(would_key, **kwargs))
        return False
    raw = (_prompt(t(ask_key, **kwargs)) or "").strip().lower()
    return raw in ("y", "yes")


def _step_providers(dry_run):
    print(t("setup_step_providers"))
    for p in providers.ORDER:
        label = providers.label(p)
        mark = "✓" if providers.installed(p) else "✗"
        print(t("setup_provider_status", mark=mark, label=label))
        if providers.installed(p):
            continue
        install_cmd = providers.registry[p].INSTALL_CMD
        if _offer(dry_run, "setup_confirm_install", "setup_would_install", label=label, cmd=install_cmd):
            providers.install(p)
    print(t("setup_install_hint", cmd="./selectorai.py install"))


def _step_auth(dry_run):
    print(t("setup_step_auth"))
    for p in providers.ORDER:
        if not providers.installed(p):
            continue
        label = providers.label(p)
        print(t("setup_auth_provider_header", label=label))
        status_cmd = providers.registry[p].LOGIN_STATUS_CMD
        if status_cmd:
            joined = " ".join(status_cmd)
            if dry_run:
                print(t("setup_would_run", cmd=joined))
            else:
                subprocess.run(status_cmd)
        else:
            print(t("setup_auth_no_status_check", label=label))
        login_cmd = " ".join(providers.registry[p].LOGIN_CMD)
        if _offer(dry_run, "setup_confirm_login", "setup_would_login", label=label, cmd=login_cmd):
            auth.run_login_capture(p)


def _step_antigravity(dry_run):
    print(t("setup_step_antigravity"))
    if not providers.installed("antigravity"):
        print(t("setup_antigravity_not_installed"))
        return
    print(t("setup_antigravity_caveat"))
    if _offer(dry_run, "setup_confirm_antigravity_on", "setup_would_antigravity_on"):
        CHECK_ANTIGRAVITY_FILE.write_text("1")
        print(t("setup_antigravity_on_done"))
    else:
        print(t("setup_antigravity_hint", cmd="./selectorai.py check-antigravity on"))


def _step_tmux():
    print(t("setup_step_tmux"))
    if session.available():
        print(t("setup_tmux_available", cmd="./selectorai.py background off"))
    else:
        print(t("setup_tmux_missing"))


def cmd_setup(argv):
    dry_run = "--dry-run" in argv

    if not dry_run and not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(t("setup_needs_tty", cmd="./selectorai.py setup"))
        sys.exit(1)

    print(t("setup_title"))
    if dry_run:
        print(t("setup_dry_run_banner"))
    print()

    # 1. Language first, so every later step's own printed text (all
    # through t()) already speaks whatever gets picked here.
    print(t("setup_step_language"))
    if _offer(dry_run, "setup_confirm_language", "setup_would_language"):
        cmd_lang([])
    print()

    # 2. Machine summary — pure /proc reads (see sai.sysinfo), no
    # subprocess, no network, safe to always show including under
    # --dry-run.
    print(t("setup_step_machine"))
    for line in machine_status():
        print(line)
    print()

    # 3. Providers: ✓/✗ + offer the real installer one-liner for
    # anything missing. This is deliberately the ONE place in the whole
    # flow that offers a real `curl | bash` install — the user is
    # present at a keyboard and has to type y themselves.
    _step_providers(dry_run)
    print()

    # 4. Auth: non-interactive status check where one exists, then offer
    # the clean-URL login flow (sai.auth.run_login_capture) — the same
    # device-code-friendly flow `./selectorai.py auth` uses, useful here
    # for exactly the same reason (phone-friendly, remote-SSH-friendly).
    _step_auth(dry_run)
    print()

    # 5. Antigravity's live usage check — off by default repo-wide (see
    # docs/ARCHITECTURE.md rule 1), so this is purely an explain-and-offer
    # step, never something turned on silently.
    _step_antigravity(dry_run)
    print()

    # 6. tmux — informational only, nothing to confirm: either it's there
    # and already doing its default-on thing, or it isn't and the feature
    # just stays dormant until installed. shutil.which only, no subprocess
    # spawn either way, so safe under --dry-run with no special-casing.
    _step_tmux()
    print()

    # 7. Theme — same "reuse the interactive path" shape as language.
    print(t("setup_step_theme"))
    if _offer(dry_run, "setup_confirm_theme", "setup_would_theme"):
        cmd_theme([])
    print()

    # 8. Model listings — reuses cmd_models() wholesale, including its
    # own i18n'd caution about antigravity/grok possibly prompting a
    # browser login (see sai.models._RISKY_PROVIDERS).
    print(t("setup_step_models"))
    if _offer(dry_run, "setup_confirm_models", "setup_would_models"):
        cmd_models([])
    print()

    # 9. Final status refresh — reuses sai.cli.cmd_status (see this
    # module's docstring for why the import below is deferred rather
    # than at module load time) instead of re-fetching/re-rendering
    # provider statuses by hand. Explicitly skips all network/subprocess
    # activity under --dry-run rather than trying to fake a result.
    print(t("setup_step_finish"))
    if dry_run:
        print(t("setup_would_finish"))
    else:
        from sai.cli import cmd_status

        cmd_status([], force_refresh=True)
    print(t("setup_closing", cmd="./selectorai.py"))
