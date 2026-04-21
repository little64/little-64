"""``little64 dev`` — developer scaffolding helpers."""

from __future__ import annotations

from typing import List

from little64.commands._group import SubcommandSpec, dispatch


_SUBCOMMANDS: tuple[SubcommandSpec, ...] = (
    ("new-device", "new_device", "Create a new Little-64 MMIO device skeleton."),
)


def run(argv: List[str]) -> int:
    return dispatch(
        argv,
        prog="little64 dev",
        description="Developer scaffolding helpers.",
        package="little64.commands.dev",
        subcommands=_SUBCOMMANDS,
    )
