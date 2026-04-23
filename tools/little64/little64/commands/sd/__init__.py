"""``little64 sd`` — Little64 SD boot artifact helpers."""

from __future__ import annotations

from typing import List

from little64.commands._group import SubcommandSpec, dispatch


_SUBCOMMANDS: tuple[SubcommandSpec, ...] = (
    ("build", "build", "Build the Little64 bootrom stage-0 image plus SD card image."),
    ("update", "update", "Update a correctly partitioned SD card without rewriting the full raw image."),
)


def run(argv: List[str]) -> int:
    return dispatch(
        argv,
        prog="little64 sd",
        description="Little64 SD boot artifact helpers.",
        package="little64.commands.sd",
        subcommands=_SUBCOMMANDS,
    )
