#!/usr/bin/env python3
"""Plain-python3 test: every .py file in the repo compiles, and `sai` plus
every submodule imports cleanly — including sai.ui.picker/sai.ui.plain,
which must stay importable without textual installed (textual is imported
lazily, inside functions, not at module scope — see sai/ui/picker.py's
docstring). This file itself must never import textual at module scope.
"""
import py_compile
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def check(label, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        raise AssertionError(label)


def main():
    print("test_imports:")

    # 1. Every .py file in the repo compiles (syntax-only, doesn't run
    # anything — safe even for files that assume a real tty/CLI).
    py_files = sorted(REPO_ROOT.rglob("*.py"))
    py_files = [f for f in py_files if ".git" not in f.parts]
    check(f"found .py files to compile ({len(py_files)})", len(py_files) > 10)
    for f in py_files:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            check(f"py_compile {f.relative_to(REPO_ROOT)}", False)
            raise
    check(f"py_compile: all {len(py_files)} files OK", True)

    # 2. `import sai` and every non-UI submodule.
    import sai  # noqa: F401
    import sai.paths  # noqa: F401
    import sai.i18n  # noqa: F401
    import sai.bigfont  # noqa: F401
    import sai.themes  # noqa: F401
    import sai.timeutil  # noqa: F401
    import sai.sysinfo  # noqa: F401
    import sai.cache  # noqa: F401
    import sai.auth  # noqa: F401
    import sai.cli  # noqa: F401
    import sai.providers  # noqa: F401
    import sai.providers.base  # noqa: F401
    import sai.providers.claude  # noqa: F401
    import sai.providers.codex  # noqa: F401
    import sai.providers.antigravity  # noqa: F401
    import sai.providers.grok  # noqa: F401

    check("import sai + non-ui submodules", True)

    # 3. sai.ui itself, and both picker/plain submodules, must ALSO import
    # fine under plain python3 (no textual on this interpreter) — proving
    # the lazy-import discipline actually holds, not just that it's
    # documented.
    assert "textual" not in sys.modules, "textual got imported as a side effect before this point"
    import sai.ui  # noqa: F401
    import sai.ui.plain  # noqa: F401
    import sai.ui.picker  # noqa: F401

    check("import sai.ui + picker/plain under plain python3", True)
    check("textual still not imported (lazy import held)", "textual" not in sys.modules)

    # textual_available() itself must not raise even when textual truly
    # isn't installed on this interpreter — it should report False, not
    # blow up.
    available = sai.ui.picker.textual_available()
    check(f"textual_available() returned a bool ({available})", isinstance(available, bool))

    print("test_imports: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
