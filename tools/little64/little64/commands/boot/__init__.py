"""``little64 boot`` — Little64 direct-boot helpers."""

from __future__ import annotations

from typing import List

from little64.commands._group import SubcommandSpec, dispatch


_SUBCOMMANDS: tuple[SubcommandSpec, ...] = (
    ("run", "run", "Direct-boot a Little64 kernel ELF (LiteX machine profile)."),
    ("sample", "sample", "Sample repeated fast-boot outcomes and cluster them."),
)


def run(argv: List[str]) -> int:
    return dispatch(
        argv,
        prog="little64 boot",
        description="Little64 direct-boot helpers.",
        package="little64.commands.boot",
        subcommands=_SUBCOMMANDS,
    )
