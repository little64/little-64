"""``little64`` unified CLI dispatcher.

This module wires the top-level argparse tree and lazily imports subcommand
modules from :mod:`little64.commands`. Adding a new subcommand group is a
matter of dropping a module under ``little64.commands`` and registering it in
:data:`COMMAND_GROUPS` below.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Callable, Iterable

from little64.errors import CLIError


# (subcommand name, module under little64.commands, one-line help)
COMMAND_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("paths", "paths", "Resolve Little64 repository paths and Linux build profiles."),
    ("trace", "trace", "Decode and analyze Little-64 binary trace files (.l64t)."),
    ("rsp", "rsp", "Control Little64 RSP debug servers (BIOS and Linux)."),
    ("lldb", "lldb", "LLDB helpers against a Little64 RSP server (tui)."),
    ("kernel", "kernel", "Linux kernel build, analysis, and debug helpers."),
    ("boot", "boot", "Little64 direct-boot helpers (run, sample)."),
    ("sd", "sd", "Little64 SD boot artifact builders."),
    ("rootfs", "rootfs", "Minimal Linux rootfs image builders."),
    ("bios", "bios", "Build and run the Little64 C-BIOS ELF."),
    ("dev", "dev", "Developer scaffolding helpers (new device)."),
    ("hdl", "hdl", "HDL/LiteX bitstream, simulation, and export helpers."),
)


def _register(subparsers: argparse._SubParsersAction, name: str, module: str, help_text: str) -> None:
    # ``add_help=False`` so ``little64 <cmd> --help`` is forwarded to the real
    # subcommand parser (loaded lazily from ``little64.commands.<module>``)
    # instead of being consumed by this stub. The top-level ``--help`` still
    # works via the parent parser.
    parser = subparsers.add_parser(name, help=help_text, add_help=False)
    parser.set_defaults(_lazy_module=f"little64.commands.{module}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="little64",
        description="Unified CLI for the Little64 project.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Override the detected repository root (sets LITTLE64_REPO_ROOT).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Echo every tool shell-out before running it (sets LITTLE64_VERBOSE=1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Echo every tool shell-out but skip execution (sets LITTLE64_DRY_RUN=1).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    for name, module, help_text in COMMAND_GROUPS:
        _register(subparsers, name, module, help_text)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)

    parser = _build_parser()

    # Two-phase parse: first, pull off the global ``--repo-root`` and the
    # subcommand name, then hand the rest of the argv to the subcommand's own
    # parser. This avoids every subcommand having to re-declare ``--repo-root``.
    args, remaining = parser.parse_known_args(argv_list)

    import os

    if args.repo_root is not None:
        os.environ["LITTLE64_REPO_ROOT"] = args.repo_root
    if args.verbose:
        os.environ["LITTLE64_VERBOSE"] = "1"
    if args.dry_run:
        os.environ["LITTLE64_DRY_RUN"] = "1"

    module_name: str = getattr(args, "_lazy_module")
    module = importlib.import_module(module_name)
    run: Callable[[list[str]], int] = getattr(module, "run")
    try:
        return int(run(remaining) or 0)
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        for hint in exc.hints:
            print(f"hint: {hint}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
