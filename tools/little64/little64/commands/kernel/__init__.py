"""``little64 kernel`` — Linux kernel build and debug helpers."""

from __future__ import annotations

from typing import List

from little64.commands._group import SubcommandSpec, dispatch


_SUBCOMMANDS: tuple[SubcommandSpec, ...] = (
    ("build", "build", "Build the Little64 Linux kernel (defconfig-aware)."),
    ("pc2line", "pc2line", "Resolve a PC to function/file/line in a vmlinux image."),
    ("analyze-lockup", "analyze_lockup", "Analyze Little64 boot lockup trace logs."),
)


def run(argv: List[str]) -> int:
    return dispatch(
        argv,
        prog="little64 kernel",
        description="Linux kernel build and debug helpers.",
        package="little64.commands.kernel",
        subcommands=_SUBCOMMANDS,
    )
