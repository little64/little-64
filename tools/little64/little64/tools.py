"""Tool availability helpers.

Consolidates the "find a binary or fail with a useful hint" pattern that was
previously copy-pasted into rootfs/build.py, commands/lldb.py, and
commands/bios.py. Each call site used to return slightly different error
strings; centralizing lets us keep messages consistent.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


class MissingToolError(RuntimeError):
    """Raised when a required binary cannot be located on the host."""


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """A tool whose absence should produce a helpful diagnostic."""

    name: str
    hint: str = ""
    extra_search_dirs: tuple[str, ...] = ()


def find_host_tool(name: str, *, extra_search_dirs: tuple[str, ...] = ()) -> Path | None:
    """Return ``Path`` to an executable ``name`` or ``None`` if not found.

    ``shutil.which`` is consulted first, then any ``extra_search_dirs`` are
    probed. Common fallbacks like ``/usr/sbin`` and ``/sbin`` are checked
    automatically for root-only admin tools (``mke2fs`` etc.).
    """
    resolved = shutil.which(name)
    if resolved:
        return Path(resolved)
    candidates = list(extra_search_dirs) + [f"/usr/sbin/{name}", f"/sbin/{name}"]
    for candidate in candidates:
        if candidate.endswith(name):
            path = Path(candidate)
        else:
            path = Path(candidate) / name
        if os.access(path, os.X_OK):
            return path
    return None


def require_host_tool(request: ToolRequest) -> Path:
    """Locate a tool or raise :class:`MissingToolError` with its hint."""
    found = find_host_tool(request.name, extra_search_dirs=request.extra_search_dirs)
    if found is not None:
        return found
    message = f"{request.name} not found on PATH"
    if request.hint:
        message = f"{message}\nhint: {request.hint}"
    raise MissingToolError(message)


def require_any_host_tool(requests: tuple[ToolRequest, ...]) -> Path:
    """Return the first available tool from ``requests`` or raise."""
    tried: list[str] = []
    hint = ""
    for request in requests:
        found = find_host_tool(request.name, extra_search_dirs=request.extra_search_dirs)
        if found is not None:
            return found
        tried.append(request.name)
        if not hint and request.hint:
            hint = request.hint
    message = f"none of the following tools are available: {', '.join(tried)}"
    if hint:
        message = f"{message}\nhint: {hint}"
    raise MissingToolError(message)


def require_compiler_tool(compiler_bin_dir: Path, name: str, *, hint: str = "") -> Path:
    """Require a tool from the Little64 compiler-bin directory.

    The compiler tree is produced by ``compilers/build.sh llvm``; if callers
    invoke this before that has been run, they get a consistent hint.
    """
    candidate = compiler_bin_dir / name
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    message = f"{name} not found at {candidate}"
    default_hint = "build the LLVM toolchain first with: (cd compilers && ./build.sh llvm)"
    message = f"{message}\nhint: {hint or default_hint}"
    raise MissingToolError(message)


def report_and_exit(exc: MissingToolError, stream=None) -> int:
    """Convert a :class:`MissingToolError` into a friendly CLI exit code."""
    print(f"error: {exc}", file=stream or sys.stderr)
    return 1
