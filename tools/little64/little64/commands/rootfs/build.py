"""``little64 rootfs build`` \u2014 build the minimal ext4 rootfs image for the LiteX SD boot path."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from little64.paths import compiler_bin, linux_port_dir, repo_root


def _find_host_tool(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    for candidate in (f"/usr/sbin/{name}", f"/sbin/{name}"):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def run(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="little64 rootfs build",
        description="Build a minimal ext4 rootfs image for the Little64 LiteX SD boot helpers.",
    )
    parser.add_argument("action", nargs="?", default="build", choices=["build", "clean"])
    args = parser.parse_args(argv)

    root = repo_root()
    tools = compiler_bin(root)
    script_dir = linux_port_dir(root) / "rootfs"
    build_dir = script_dir / "build"
    staging = build_dir / "staging"
    init_obj = build_dir / "init.o"
    init_elf = build_dir / "init"
    rootfs_image = build_dir / "rootfs.ext4"
    rootfs_size_mb = os.environ.get("LITTLE64_ROOTFS_SIZE_MB", "8")

    if args.action == "clean":
        shutil.rmtree(build_dir, ignore_errors=True)
        return 0

    if not (tools / "llvm-mc").is_file():
        print(f"error: llvm-mc not found at {tools}/llvm-mc", file=sys.stderr)
        print(f"hint: build the LLVM toolchain first with: (cd {root}/compilers && ./build.sh llvm)", file=sys.stderr)
        return 1
    if not (tools / "ld.lld").is_file():
        print(f"error: ld.lld not found at {tools}/ld.lld", file=sys.stderr)
        print(f"hint: build the LLVM toolchain first with: (cd {root}/compilers && ./build.sh llvm)", file=sys.stderr)
        return 1

    if not rootfs_size_mb.isdigit() or rootfs_size_mb == "0":
        print("error: LITTLE64_ROOTFS_SIZE_MB must be a positive integer", file=sys.stderr)
        return 1

    mkfs = _find_host_tool("mke2fs") or _find_host_tool("mkfs.ext4")
    if not mkfs:
        print("error: neither mke2fs nor mkfs.ext4 is available", file=sys.stderr)
        return 1

    shutil.rmtree(build_dir, ignore_errors=True)
    for sub in ("dev", "etc", "proc", "sys", "tmp"):
        (staging / sub).mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [str(tools / "llvm-mc"), "-triple=little64", "-filetype=obj",
         str(script_dir / "init.S"), "-o", str(init_obj)],
        check=True,
    )
    subprocess.run(
        [str(tools / "ld.lld"), "-z", "noexecstack", "-e", "_start",
         "-T", str(script_dir / "init.ld"), str(init_obj), "-o", str(init_elf)],
        check=True,
    )
    os.chmod(init_elf, 0o755)
    shutil.copy2(init_elf, staging / "init")

    (staging / "etc" / "issue").write_text("Little-64 Linux test rootfs\n")
    (staging / "README.little64").write_text(
        "This image is a minimal Little-64 test rootfs for the LiteX SD boot path.\n"
        "It exists to get VFS onto a real disk-backed root filesystem during kernel bring-up.\n"
    )

    subprocess.run(
        [mkfs, "-q", "-F", "-t", "ext4", "-L", "little64-rootfs", "-m", "0",
         "-d", str(staging), str(rootfs_image), f"{rootfs_size_mb}M"],
        check=True,
    )

    print(f"[little64-rootfs] built {rootfs_image}")
    return 0
