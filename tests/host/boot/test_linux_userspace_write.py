#!/usr/bin/env python3
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
BIN = ROOT / "compilers" / "bin"
LLVM_MC = BIN / "llvm-mc"
LD = BIN / "ld.lld"
BOOT_HELPER = ROOT / "target" / "linux_port" / "boot_direct.sh"
KERNEL_ELF = ROOT / "target" / "linux_port" / "build" / "vmlinux"

INIT_SOURCE = pathlib.Path(__file__).with_name("linux_userspace_write_init.S")
INIT_LINKER = pathlib.Path(__file__).with_name("linux_userspace_write_init.ld")
EXPECTED_STDOUT = "hello from little64 test init via single write\n"
EXPECTED_MAX_CYCLES_ERROR = "Error: execution reached max cycle limit"


def find_host_tool(name: str) -> str | None:
    resolved = shutil.which(name)
    if resolved:
        return resolved

    for prefix in ("/usr/sbin", "/sbin"):
        candidate = pathlib.Path(prefix) / name
        if candidate.exists() and candidate.stat().st_mode & 0o111:
            return str(candidate)

    return None


def run_checked(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        details: list[str] = []
        if exc.stdout:
            details.append(f"stdout:\n{exc.stdout}")
        if exc.stderr:
            details.append(f"stderr:\n{exc.stderr}")
        suffix = "\n\n" + "\n\n".join(details) if details else ""
        raise RuntimeError(f"Command failed: {' '.join(cmd)}{suffix}") from exc


def build_rootfs(builddir: pathlib.Path) -> pathlib.Path:
    mkfs_ext2 = find_host_tool("mke2fs") or find_host_tool("mkfs.ext2")
    if not mkfs_ext2:
        raise SystemExit(77)

    for tool in (LLVM_MC, LD):
        if not tool.exists():
            raise SystemExit(77)

    out_dir = builddir / "test_linux_userspace_write_rootfs"
    staging_dir = out_dir / "staging"
    init_obj = out_dir / "init.o"
    init_elf = out_dir / "init"
    rootfs_image = out_dir / "rootfs.ext2"

    if out_dir.exists():
        shutil.rmtree(out_dir)

    for rel in ("dev", "etc", "proc", "sys", "tmp"):
        (staging_dir / rel).mkdir(parents=True, exist_ok=True)

    run_checked([
        str(LLVM_MC),
        "-triple=little64",
        "-filetype=obj",
        str(INIT_SOURCE),
        "-o",
        str(init_obj),
    ])

    run_checked([
        str(LD),
        "-z",
        "noexecstack",
        "-e",
        "_start",
        "-T",
        str(INIT_LINKER),
        str(init_obj),
        "-o",
        str(init_elf),
    ])

    init_elf.chmod(0o755)
    shutil.copy2(init_elf, staging_dir / "init")
    (staging_dir / "etc" / "issue").write_text(
        "Little-64 Linux userspace write smoke rootfs\n",
        encoding="utf-8",
    )

    run_checked([
        mkfs_ext2,
        "-q",
        "-F",
        "-t",
        "ext2",
        "-L",
        "little64-test-rootfs",
        "-m",
        "0",
        "-d",
        str(staging_dir),
        str(rootfs_image),
        "8M",
    ])

    return rootfs_image


def main() -> int:
    if not KERNEL_ELF.exists() or not BOOT_HELPER.exists():
        raise SystemExit(77)

    builddir = ROOT / "builddir"
    builddir.mkdir(parents=True, exist_ok=True)

    rootfs_image = build_rootfs(builddir)

    res = subprocess.run(
        [
            str(BOOT_HELPER),
            "--mode=smoke",
            "--rootfs",
            str(rootfs_image),
            "--max-cycles",
            "200000000",
            str(KERNEL_ELF),
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )

    if EXPECTED_STDOUT not in res.stdout:
        raise RuntimeError(
            "Missing full userspace write output in boot stdout:\n"
            f"{res.stdout}"
        )

    if res.returncode not in (0, 1):
        raise RuntimeError(
            "Unexpected boot helper exit status "
            f"{res.returncode}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )

    if res.returncode == 1 and EXPECTED_MAX_CYCLES_ERROR not in res.stderr:
        raise RuntimeError(
            "Boot helper stopped with an unexpected error.\n"
            f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())