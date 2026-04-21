"""``little64 rootfs`` — minimal Linux rootfs image builders."""

from __future__ import annotations

from typing import List

from little64.commands._group import SubcommandSpec, dispatch


_SUBCOMMANDS: tuple[SubcommandSpec, ...] = (
    ("build", "build", "Build the minimal ext4 rootfs image from rootfs/init.S."),
    ("mlibc-hello", "mlibc_hello", "Build the mlibc-based hello-world rootfs image."),
)


def run(argv: List[str]) -> int:
    return dispatch(
        argv,
        prog="little64 rootfs",
        description="Minimal Linux rootfs image builders.",
        package="little64.commands.rootfs",
        subcommands=_SUBCOMMANDS,
    )
