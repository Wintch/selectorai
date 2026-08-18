#!/usr/bin/env python3
"""Discover and run test_*.py files in this directory, in name order.
Plain scripts with asserts (no pytest) — each test_*.py is run as its own
subprocess with the *same* interpreter this runner was launched with, so
`python3 tests/run_tests.py` exercises the stdlib-only path and
`.../venv/bin/python3 tests/run_tests.py` additionally exercises the
Textual picker test. A test may print its own "SKIP" line and exit 0 when
a precondition isn't met (see test_picker_headless.py under plain
python3) — that still counts as a pass, not a failure.
"""
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def main():
    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    if not test_files:
        print("No tests found.")
        return 1

    results = []
    for f in test_files:
        print(f"--- {f.name} ({sys.executable}) ---")
        sys.stdout.flush()  # keep this header ahead of the child's own (unbuffered-ish) prints
        r = subprocess.run([sys.executable, str(f)], cwd=str(TESTS_DIR))
        ok = r.returncode == 0
        results.append((f.name, ok))
        print()

    print("=" * 60)
    print("Summary:")
    failed = 0
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{status}] {name}")
    print("=" * 60)
    if failed:
        print(f"{failed}/{len(results)} test file(s) failed.")
        return 1
    print(f"All {len(results)} test file(s) passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
