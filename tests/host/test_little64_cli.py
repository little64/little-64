#!/usr/bin/env python3
"""Smoke test: the ``little64`` CLI dispatcher imports and answers help."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys


REPO = pathlib.Path(__file__).resolve().parents[2]
PKG = REPO / "tools" / "little64"


def main() -> int:
    # Import the package directly via PYTHONPATH so we exercise the source
    # tree without requiring a prior ``pip install -e``. This mirrors what a
    # fresh checkout looks like before the bootstrap step.
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PKG), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)

    # ``little64 --help`` must exit 0.
    result = subprocess.run(
        [sys.executable, "-m", "little64.cli", "--help"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    # ``little64 paths repo-root`` must resolve to the detected repo root.
    result = subprocess.run(
        [sys.executable, "-m", "little64.cli", "paths", "repo-root"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    reported = pathlib.Path(result.stdout.strip()).resolve()
    if reported != REPO:
        sys.stderr.write(
            f"expected repo-root {REPO}, got {reported}\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
