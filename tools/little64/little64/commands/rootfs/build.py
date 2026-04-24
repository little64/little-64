"""``little64 rootfs build`` — build the minimal ext4 rootfs image for the LiteX SD boot path."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import List

from little64 import env, tools
from little64.build_support import run_checked
from little64.paths import compiler_bin, linux_port_dir, repo_root


def run(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="little64 rootfs build",
        description="Build a minimal ext4 rootfs image for the Little64 LiteX SD boot helpers.",
    )
    parser.add_argument("action", nargs="?", default="build", choices=["build", "clean"])
    parser.add_argument(
        "--size-mb",
        default=None,
        help=f"Rootfs image size in MB (default: {env.ROOTFS_SIZE_MB.name} or 8).",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    compiler_dir = compiler_bin(root)
    script_dir = linux_port_dir(root) / "rootfs"
    build_dir = script_dir / "build"
    staging = build_dir / "staging"
    init_obj = build_dir / "init.o"
    init_elf = build_dir / "init"
    rootfs_image = build_dir / "rootfs.ext4"
    rootfs_size_mb = args.size_mb or env.ROOTFS_SIZE_MB.get()

    if args.action == "clean":
        shutil.rmtree(build_dir, ignore_errors=True)
        return 0

    try:
        llvm_mc = tools.require_compiler_tool(compiler_dir, "llvm-mc")
        ld_lld = tools.require_compiler_tool(compiler_dir, "ld.lld")
    except tools.MissingToolError as exc:
        return tools.report_and_exit(exc)

    if not rootfs_size_mb or not rootfs_size_mb.isdigit() or rootfs_size_mb == "0":
        print(
            f"error: rootfs size must be a positive integer (got {rootfs_size_mb!r})",
            file=sys.stderr,
        )
        print(f"hint: pass --size-mb N or set {env.ROOTFS_SIZE_MB.name}=N", file=sys.stderr)
        return 1

    try:
        mkfs = tools.require_any_host_tool((
            tools.ToolRequest("mke2fs"),
            tools.ToolRequest("mkfs.ext4", hint="install e2fsprogs"),
        ))
    except tools.MissingToolError as exc:
        return tools.report_and_exit(exc)

    shutil.rmtree(build_dir, ignore_errors=True)
    for sub in ("dev", "etc", "proc", "sys", "tmp"):
        (staging / sub).mkdir(parents=True, exist_ok=True)

    run_checked(
        [str(llvm_mc), "-triple=little64", "-filetype=obj",
         str(script_dir / "init.S"), "-o", str(init_obj)],
    )
    run_checked(
        [str(ld_lld), "-z", "noexecstack", "-e", "_start",
         "-T", str(script_dir / "init.ld"), str(init_obj), "-o", str(init_elf)],
    )
    os.chmod(init_elf, 0o755)
    shutil.copy2(init_elf, staging / "init")

    (staging / "etc" / "issue").write_text("Little-64 Linux test rootfs\n")
    (staging / "README.little64").write_text(
        "This image is a minimal Little-64 test rootfs for the LiteX SD boot path.\n"
        "It exists to get VFS onto a real disk-backed root filesystem during kernel bring-up.\n"
    )

    run_checked(
        [str(mkfs), "-q", "-F", "-t", "ext4", "-L", "little64-rootfs", "-m", "0",
         "-d", str(staging), str(rootfs_image), f"{rootfs_size_mb}M"],
    )

    print(f"[little64-rootfs] built {rootfs_image}")
    return 0
