"""``little64 rootfs mlibc-hello`` \u2014 build an ext2 rootfs with a mlibc dynamically-linked /init."""

from __future__ import annotations

import argparse
import os
import shutil
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
        prog="little64 rootfs mlibc-hello",
        description="Build a rootfs ext2 image with a dynamically-linked mlibc hello-world /init.",
    )
    parser.add_argument("action", nargs="?", default="build", choices=["build", "clean"])
    args = parser.parse_args(argv)

    root = repo_root()
    tools = compiler_bin(root)
    sysroot = root / "target" / "sysroot"
    script_dir = linux_port_dir(root) / "rootfs"
    build_dir = script_dir / "build-mlibc-hello"
    staging = build_dir / "staging"
    rootfs_image = build_dir / "rootfs.ext2"
    rootfs_size_mb = os.environ.get("LITTLE64_ROOTFS_SIZE_MB", "16")
    hello_src = script_dir / "hello_init.c"

    if args.action == "clean":
        shutil.rmtree(build_dir, ignore_errors=True)
        return 0

    def die(msg: str) -> int:
        print(f"error: {msg}", file=sys.stderr)
        return 1

    if not (tools / "clang").is_file():
        return die("clang not found \u2014 build the toolchain first")
    if not (tools / "ld.lld").is_file():
        return die("ld.lld not found \u2014 build the toolchain first")
    if not (sysroot / "usr" / "lib").is_dir():
        return die(f"sysroot not found at {sysroot} \u2014 run target/build_sysroot.sh first")
    if not (sysroot / "usr" / "lib" / "libc.so").is_file():
        return die("libc.so not found in sysroot \u2014 run target/build_sysroot.sh first")
    if not hello_src.is_file():
        return die(f"hello_init.c not found at {hello_src}")

    mkfs = _find_host_tool("mke2fs") or _find_host_tool("mkfs.ext2")
    if not mkfs:
        return die("mke2fs / mkfs.ext2 not available")

    shutil.rmtree(build_dir, ignore_errors=True)
    for sub in ("dev", "etc", "proc", "sys", "tmp", "usr/lib"):
        (staging / sub).mkdir(parents=True, exist_ok=True)

    print("[mlibc-hello] Compiling hello_init.c \u2026")
    subprocess.run(
        [str(tools / "clang"), "-target", "little64",
         f"--sysroot={sysroot}",
         "-isystem", str(sysroot / "usr" / "include"),
         "-c", "-o", str(build_dir / "hello_init.o"), str(hello_src)],
        check=True,
    )

    print("[mlibc-hello] Linking init (dynamic) \u2026")
    subprocess.run(
        [str(tools / "ld.lld"),
         "-o", str(build_dir / "init"),
         str(sysroot / "usr" / "lib" / "Scrt1.o"),
         str(sysroot / "usr" / "lib" / "crti.o"),
         str(build_dir / "hello_init.o"),
         "-L", str(sysroot / "usr" / "lib"), "-lc",
         "-dynamic-linker", "/usr/lib/ld.so",
         "-rpath", "/usr/lib",
         str(sysroot / "usr" / "lib" / "crtn.o")],
        check=True,
    )
    os.chmod(build_dir / "init", 0o755)
    shutil.copy2(build_dir / "init", staging / "init")

    for lib in (
        "ld.so", "libc.so", "libdl.so", "libm.so", "libpthread.so", "libresolv.so",
        "librt.so", "libssp.so", "libssp_nonshared.so", "libutil.so",
    ):
        src = sysroot / "usr" / "lib" / lib
        if src.is_file():
            shutil.copy2(src, staging / "usr" / "lib" / lib)

    (staging / "etc" / "issue").write_text("Little-64 mlibc test rootfs\n")
    (staging / "README.little64").write_text(
        "Minimal Little-64 rootfs with mlibc-based dynamically-linked /init.\n"
    )

    print(f"[mlibc-hello] Creating rootfs.ext2 ({rootfs_size_mb} MiB) \u2026")
    subprocess.run(
        [mkfs, "-q", "-F", "-t", "ext2", "-L", "little64-mlibc", "-m", "0",
         "-d", str(staging), str(rootfs_image), f"{rootfs_size_mb}M"],
        check=True,
    )

    print(f"[mlibc-hello] Built {rootfs_image}")
    print(f"[mlibc-hello] init payload: {build_dir / 'init'}")
    return 0
