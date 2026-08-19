#!/usr/bin/env python3
"""Plain-python3 test: sai.auth's URL-extraction regex only (_URL_BLOCK_RE
plus the whitespace-strip idiom run_login_capture applies to its match).

Doesn't exercise run_login_capture itself — that spawns a real subprocess
via a shell pipe (`cmd | tee logfile`), which is exactly the class of
thing this repo's safety rules forbid an automated test from doing (see
tests/test_status_shapes.py's module docstring). The regex is the part
that actually had a bug (see sai/auth.py's _URL_BLOCK_RE comment for the
live incident this reproduces), so it's what's worth covering directly.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sai.auth import _URL_BLOCK_RE  # noqa: E402


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


def _clean_url(text):
    m = _URL_BLOCK_RE.search(text)
    return re.sub(r"\s+", "", m.group(0)) if m else None


def test_wrapped_url_across_newlines_rejoins_clean():
    # A CLI wrapping its own printed URL at an assumed column width, no
    # real space inserted at the break — the original problem this
    # regex/strip pair was built to fix.
    text = (
        "Visit:\n\n"
        "https://auth.x.ai/oauth2/dev\nice/code?user_code=ABCD-EFGH\n\n"
        "Then enter the code above."
    )
    check(
        "wrapped URL rejoins without swallowing the trailing prose",
        _clean_url(text) == "https://auth.x.ai/oauth2/device/code?user_code=ABCD-EFGH",
    )


def test_url_followed_by_trailing_error_text_on_same_line_not_swallowed():
    # Live-reproduced incident (grok device-auth on a DNS failure): the
    # URL and unrelated error prose share one line with no blank line
    # between them, so the old ".split(\"\\n\\n\")[0]" heuristic never
    # found a stop point and mashed the whole line into the "clean URL".
    text = (
        'Error: error sending request for url (https://auth.x.ai/oauth2/device/code): '
        "client error (Connect): dns error: failed to lookup address information: Try again"
    )
    check(
        "URL extracted without the trailing error text glued on",
        _clean_url(text) == "https://auth.x.ai/oauth2/device/code",
    )


def test_no_url_present_no_match():
    check("no https?:// in the text -> no match", _clean_url("just some ordinary output\nnothing to see here") is None)


def main():
    print("test_auth:")
    test_wrapped_url_across_newlines_rejoins_clean()
    test_url_followed_by_trailing_error_text_on_same_line_not_swallowed()
    test_no_url_present_no_match()
    print("test_auth: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
