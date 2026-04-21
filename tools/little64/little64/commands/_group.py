"""Shared helper for command-group dispatch.

Most ``little64 <group>`` subcommand groups follow the same pattern: a tuple
of ``(name, module_suffix, help)`` entries, a top-level parser that lists
them, and a dispatcher that lazily imports the selected module's ``run``
function. This module centralises that pattern so each group's
``__init__.py`` is a short declaration.
"""

from __future__ import annotations

import argparse
import importlib
from typing import Iterable, List, Sequence, Tuple


SubcommandSpec = Tuple[str, str, str]
"""``(name, module_suffix, help)``."""


def build_parser(prog: str, description: str, subcommands: Sequence[SubcommandSpec]) -> argparse.ArgumentParser:
    """Return a parser that lists all subcommands without loading them."""
    parser = argparse.ArgumentParser(prog=prog, description=description)
    sub = parser.add_subparsers(dest="op", required=True, metavar="<op>")
    for name, _module, help_text in subcommands:
        # Stub parser; the real parser is owned by the backing module.
        sub.add_parser(name, help=help_text, add_help=False)
    return parser


def dispatch(
    argv: Iterable[str],
    *,
    prog: str,
    description: str,
    package: str,
    subcommands: Sequence[SubcommandSpec],
) -> int:
    """Dispatch ``argv`` to the matching subcommand's ``run`` function.

    ``package`` is the fully qualified package name under which the backing
    modules live (e.g. ``"little64.commands.kernel"``).
    """
    argv_list = list(argv)
    if not argv_list or argv_list[0] in ("-h", "--help"):
        build_parser(prog, description, subcommands).parse_args(argv_list)
        return 0

    op = argv_list[0]
    for name, module_suffix, _help in subcommands:
        if name == op:
            module = importlib.import_module(f"{package}.{module_suffix}")
            return int(module.run(argv_list[1:]) or 0)

    # Fall through to argparse error for an unknown subcommand.
    build_parser(prog, description, subcommands).parse_args(argv_list)
    return 2
