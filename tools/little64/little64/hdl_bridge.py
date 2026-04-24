"""Single entry point for importing Little64 HDL modules from the CLI.

The ``hdl/`` subtree is not an installable Python package — it lives beside
the CLI and is imported by appending ``<repo>/hdl`` to :data:`sys.path`.
Before this helper existed, ten different command modules each pasted the
same ``sys.path.insert(0, ...)`` line inline. Every one of them was a site
that could silently break if the repo layout changed. Now the rule is:
**if you need to import ``little64_cores``, call :func:`ensure_hdl_path`**.
"""

from __future__ import annotations

import sys
from pathlib import Path

from little64.paths import repo_root


def hdl_root(root: Path | None = None) -> Path:
    """Return the ``<repo>/hdl`` directory that holds ``little64_cores``."""
    return (root or repo_root()) / "hdl"


def ensure_hdl_path(root: Path | None = None) -> Path:
    """Add ``<repo>/hdl`` to :data:`sys.path` (idempotent) and return the path."""
    directory = hdl_root(root)
    entry = str(directory)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    return directory
