#!/usr/bin/env python3
"""Guard: no stray ``*.sh`` wrappers under ``target/`` or ``hdl/tools/``.

Shell wrappers are retired in favor of the unified ``little64`` Python CLI
(see ``tools/little64/``). The only shell scripts that may remain are:

* ``target/linux_port/clang_guard.sh`` — exec'd directly by ``make`` during
  kernel builds; shell form is intentional.
* ``target/build_sysroot.sh`` — top-level sysroot build entry point; not part
  of the migrated script set.
* anything under ``target/linux_port/linux/`` — vendored Linux kernel tree.
"""

from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

ALLOWED = {
    REPO_ROOT / "target" / "linux_port" / "clang_guard.sh",
    REPO_ROOT / "target" / "build_sysroot.sh",
}

SCAN_ROOTS = (
    REPO_ROOT / "target",
    REPO_ROOT / "hdl" / "tools",
)

EXCLUDED_DIRS = (
    REPO_ROOT / "target" / "linux_port" / "linux",
    REPO_ROOT / "target" / "mlibc",
)


def _is_excluded(path: pathlib.Path) -> bool:
    for excluded in EXCLUDED_DIRS:
        try:
            path.relative_to(excluded)
            return True
        except ValueError:
            continue
    return False


def main() -> int:
    offenders: list[pathlib.Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for sh in root.rglob("*.sh"):
            if _is_excluded(sh):
                continue
            if sh in ALLOWED:
                continue
            offenders.append(sh)
    if offenders:
        print("Forbidden shell wrappers detected:", file=sys.stderr)
        for path in offenders:
            print(f"  {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        print(
            "\nShell wrappers under target/ and hdl/tools/ are retired. "
            "Add the functionality to the little64 Python CLI instead.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
