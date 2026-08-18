"""Background-session persistence via tmux: keep a launched CLI running
inside a detached tmux session so it survives an SSH drop, and offer to
reattach to it on the next run instead of starting fresh.

live-unverified: tmux is NOT installed on this development machine (no
sudo, no way to install it here) — every tmux-facing function in this
module is built from tmux(1)'s documented conventions plus the prior-art
repos surveyed in docs/PRIOR_ART.md's "Session-persistence / tmux
managers" section (claude-squad/ccmanager's "one TUI, one tmux session,
one keypress to attach" shape; the plain `tmux attach || tmux new` idiom;
tmux-resurrect's `capture-pane -p` preview trick) rather than exercised
against a real tmux binary. tests/test_session.py stubs shutil.which and
subprocess.run entirely — it proves this module's own branching logic,
not that the tmux commands it shells out to actually behave as documented.

Deliberately NOT a multi-session manager (out of scope per
docs/PRIOR_ART.md's "ideas deliberately not adopted" — no daemon, no
per-account session sprawl): one fixed session name, one window per
provider launched into it, `has-session` for liveness. KEEP IT SIMPLE.
"""
import os
import shutil
import subprocess

from sai import paths
from sai.i18n import t

SESSION_NAME = "selectorai"

_BACKGROUND_FILENAME = "background"


def _background_file():
    # `paths.STATE_DIR` read at call time, not bound to a module-level
    # constant — same reason as sai/providers/codex.py's status(): tests
    # monkeypatch sai.paths.STATE_DIR to a tempdir, and a name imported at
    # module load time would freeze the old path before that happens.
    return paths.STATE_DIR / _BACKGROUND_FILENAME


def available():
    """Whether the tmux binary exists on PATH at all.
    live-unverified: shutil.which itself is plain stdlib, the caveat is
    only that this has never observed a real tmux install returning True."""
    return shutil.which("tmux") is not None


def enabled():
    """Persisted toggle, ABSENT file = ON. Inverted from
    check-antigravity's opt-in-by-default (see sai.cli.cmd_check_antigravity):
    surviving an SSH drop is this feature's entire reason to exist, so once
    tmux is available it should just work without an extra opt-in step. A
    file containing '0' is the explicit opt-out; any other content (or the
    file simply not existing) means on."""
    f = _background_file()
    if not f.exists():
        return True
    return f.read_text().strip() != "0"


def should_wrap():
    """The actual gate wrap_launch() uses, pulled out into its own
    function so sai.cli can ask "is a launch about to be tmux-wrapped?"
    (for the launch-log's mode string, see sai.cli.cmd_menu) without
    duplicating this condition or calling wrap_launch() itself just to
    inspect it. Not wrapping inside an existing tmux session (`TMUX` env
    var set) is load-bearing, not cosmetic: tmux does not support nesting
    a session inside a client that's already attached to one — see
    tmux(1)'s own $TMUX discussion."""
    return available() and enabled() and "TMUX" not in os.environ


def live_windows():
    """[(window_name, activity_epoch), ...] for the persistent session, or
    [] if it doesn't exist (including "tmux isn't installed" — has-session
    just fails the same way). live-unverified: the two tmux invocations
    below follow `tmux has-session`/`tmux list-windows -F` as documented in
    tmux(1), not confirmed against a real session."""
    try:
        has = subprocess.run(
            ["tmux", "has-session", "-t", SESSION_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    if has.returncode != 0:
        return []
    try:
        out = subprocess.run(
            ["tmux", "list-windows", "-t", SESSION_NAME, "-F", "#{window_name}\t#{window_activity}"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except Exception:
        return []
    windows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        name, epoch_str = parts
        try:
            windows.append((name, int(epoch_str)))
        except ValueError:
            continue
    return windows


def peek(window_name):
    """Best-effort "what was the agent doing" preview: last 5 non-empty
    lines of the window's pane, via tmux-resurrect's `capture-pane -p`
    trick (see docs/PRIOR_ART.md — reused rather than reimplemented, no
    per-CLI output parsing needed). [] on any failure (dead window, no
    tmux, anything else) — this is a nice-to-have for the reattach offer's
    detail panel, never something a caller should treat as authoritative.
    live-unverified."""
    try:
        out = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", f"{SESSION_NAME}:{window_name}", "-S", "-10"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except Exception:
        return []
    lines = [line for line in out.splitlines() if line.strip()]
    return lines[-5:]


def wrap_launch(provider_name, argv_list):
    """Returns the argv the caller should actually exec. Three cases:

    - tmux missing/disabled, or already inside a tmux client (`$TMUX` set,
      see should_wrap() above): argv_list unchanged — no nesting, no
      surprise wrapping of a launch the user already runs inside tmux.
    - no live `selectorai` session yet: create one, naming its first
      window after the provider being launched
      (`tmux new-session -s selectorai -n <provider> <argv...>`).
    - a live session already exists: add a new window running the
      provider into it (`tmux new-window`, run as a side effect here,
      not returned — see below) then hand back `tmux attach-session`, so
      the caller's exec lands the *current* terminal inside the shared
      session instead of launching the CLI a second time.

    live-unverified: both tmux invocations below follow tmux(1)'s
    documented `new-session`/`new-window`/`attach-session` flag shapes,
    not confirmed against a real session."""
    if not should_wrap():
        return argv_list
    if not live_windows():
        return ["tmux", "new-session", "-s", SESSION_NAME, "-n", provider_name] + argv_list
    # Side-effecting subprocess.run here, not exec: the new window is
    # created in the background while this process is still the one about
    # to exec attach-session next — there's nothing to hand argv_list's
    # exec responsibility to otherwise, unlike the session-absent branch
    # where `tmux new-session ... <argv>` does both jobs (create + run) at
    # once.
    subprocess.run(["tmux", "new-window", "-t", SESSION_NAME, "-n", provider_name] + argv_list)
    return ["tmux", "attach-session", "-t", SESSION_NAME]


def cmd_background(argv):
    """`background on|off|status` — same on/off/status shape as
    sai.cli.cmd_check_antigravity, persisted via _background_file()
    instead of a bare CHECK_ANTIGRAVITY_FILE-style constant (see
    _background_file()'s docstring for why: STATE_DIR must be read at
    call time here, for testability)."""
    f = _background_file()
    if argv and argv[0] == "on":
        f.unlink(missing_ok=True)  # absent == on, see enabled()
        print(t("session_background_on_msg"))
    elif argv and argv[0] == "off":
        f.write_text("0")
        print(t("session_background_off_msg"))
    else:
        state_key = "session_state_on" if enabled() else "session_state_off"
        print(t("session_background_status", state=t(state_key)))
        print(t("session_background_hint_on", cmd="selectorai.py"))
        print(t("session_background_hint_off", cmd="selectorai.py"))
    if not available():
        print(t("session_no_tmux"))
