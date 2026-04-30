"""``little64 boot run`` \u2014 Little64 direct-boot helper for LiteX.

Produces a bootable SDRAM-backed LiteX SD image from a vmlinux, launches the
emulator (optionally with trace capture or the RSP debug server), and surfaces
the resulting exit status.
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from little64.build_support import run_checked
from little64.litex_boot_support import (
    default_kernel_for_machine,
    ensure_default_machine_kernel_matches_defconfig,
    ensure_litex_kernel_support,
    ensure_litex_python_env,
    resolve_litex_machine_profile,
)
from little64.paths import (
    builddir,
    repo_root,
)
from little64.tooling_support import little64_command, resolve_python_bin


DEFAULT_MODE = "smoke"
DEFAULT_MACHINE = "litex"
DEFAULT_LAUNCH = "direct"
DEFAULT_STAGE0_STACK_RESERVE_BYTES = 512
DEFAULT_DIRECT_KERNEL_PHYSICAL_BASE = 0x40000000
DEFAULT_DIRECT_RAM_SIZE = 0x10000000


def _ensure_litex_kernel_support(kernel_path: Path) -> None:
    ensure_litex_kernel_support(kernel_path)


def _prepare_litex_artifacts(
    *,
    kernel_elf: Path,
    output_dir: Path,
    cpu_variant: str,
    litex_target: str,
    ram_size: Optional[str],
    attach_rootfs: bool,
    rootfs_image: Optional[Path],
    python_bin: str,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    dts_path = output_dir / "little64-litex-sim.dts"
    dtb_path = output_dir / "little64-litex-sim.dtb"
    bootrom_path = output_dir / "little64-sd-stage0-bootrom.bin"
    sd_path = output_dir / "little64-linux-sdcard.img"

    builder_cmd = [
        *little64_command('sd', 'build', python_bin=python_bin),
        "--machine", "litex",
        "--output-dir", str(output_dir),
        "--kernel-elf", str(kernel_elf),
        "--cpu-variant", cpu_variant,
        "--litex-target", litex_target,
        "--boot-source", "bootrom",
        "--with-sdram",
    ]
    if ram_size:
        builder_cmd += ["--ram-size", ram_size]
    if not attach_rootfs:
        builder_cmd.append("--no-rootfs")
    elif rootfs_image is not None:
        builder_cmd += ["--rootfs-image", str(rootfs_image)]
    run_checked(builder_cmd)

    return {"dts": dts_path, "dtb": dtb_path, "bootrom": bootrom_path, "sd": sd_path}


def _append_common_runtime_args(args: list[str], *, max_cycles: Optional[int], attach_rootfs: bool, sd_image: Path) -> None:
    if max_cycles is not None:
        args.append(f"--max-cycles={max_cycles}")
    if attach_rootfs:
        args.append(f"--disk={sd_image}")
        args.append("--disk-readonly")


def _infer_direct_kernel_physical_base(kernel_elf: Path) -> Optional[int]:
    """Infer direct-load physical base using stage-0-equivalent rules.

    Stage-0 loads into ``L64_KERNEL_PHYSICAL_BASE`` unless the PT_LOAD virtual
    window itself already fits in RAM, in which case it preserves that virtual
    base as the physical load address. Mirror that behavior here so direct mode
    and bootrom stage-0 launch the kernel from equivalent physical placement.
    """
    try:
        elf_bytes = kernel_elf.read_bytes()
    except OSError:
        return None

    # ELF64 header.
    if len(elf_bytes) < 64:
        return None
    if elf_bytes[0:4] != b"\x7fELF":
        return None
    if elf_bytes[4] != 2 or elf_bytes[5] != 1:  # ELFCLASS64 + ELFDATA2LSB
        return None

    try:
        ehdr = struct.unpack_from("<16sHHIQQQIHHHHHH", elf_bytes, 0)
    except struct.error:
        return None

    phoff = ehdr[5]
    phentsize = ehdr[9]
    phnum = ehdr[10]
    if phentsize < 56:
        return None

    min_vaddr: Optional[int] = None
    max_vaddr = 0
    for i in range(phnum):
        phdr_off = phoff + (i * phentsize)
        if phdr_off + 56 > len(elf_bytes):
            return None
        try:
            p_type, _p_flags, _p_offset, p_vaddr, _p_paddr, _p_filesz, p_memsz, _p_align = struct.unpack_from(
                "<IIQQQQQQ", elf_bytes, phdr_off
            )
        except struct.error:
            return None
        if p_type != 1:  # PT_LOAD
            continue
        if min_vaddr is None or p_vaddr < min_vaddr:
            min_vaddr = p_vaddr
        if p_vaddr + p_memsz > max_vaddr:
            max_vaddr = p_vaddr + p_memsz

    if min_vaddr is None or max_vaddr <= min_vaddr:
        return None

    page = 4096
    virt_base = min_vaddr & ~(page - 1)
    image_span = ((max_vaddr - virt_base + page - 1) // page) * page
    virt_end = virt_base + image_span
    ram_end = DEFAULT_DIRECT_KERNEL_PHYSICAL_BASE + DEFAULT_DIRECT_RAM_SIZE

    # Keep virtual base only when it already denotes a valid physical RAM
    # window (stage-0 image_window_fits_ram equivalent).
    if virt_base >= DEFAULT_DIRECT_KERNEL_PHYSICAL_BASE and virt_end <= ram_end:
        return virt_base

    return DEFAULT_DIRECT_KERNEL_PHYSICAL_BASE


def run(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="little64 boot run",
        description="Direct-boot a Little64 kernel ELF (LiteX machine profile).",
    )
    parser.add_argument("--machine", default=DEFAULT_MACHINE, choices=["litex"])
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=["trace", "smoke", "rsp"])
    parser.add_argument(
        "--launch",
        default=DEFAULT_LAUNCH,
        choices=["direct", "bootrom"],
        help="Launch flow: direct preloads state equivalent to post-stage-0 handoff (default); bootrom runs through the full stage-0 SD path.",
    )
    rootfs_group = parser.add_mutually_exclusive_group()
    rootfs_group.add_argument("--rootfs", default=None, help="Rootfs image path to mount as read-only SD partition 2.")
    rootfs_group.add_argument("--no-rootfs", action="store_true", help="Leave the LiteX SD rootfs partition empty.")
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("LITTLE64_RSP_PORT", "9000")),
        help="RSP port when --mode=rsp (default: 9000 or $LITTLE64_RSP_PORT).",
    )
    parser.add_argument("kernel_elf", nargs="?", default=None)
    parser.add_argument(
        "extra_max_cycles",
        nargs="?",
        default=None,
        help="Optional second positional interpreted as --max-cycles for shell-compat.",
    )
    args = parser.parse_args(argv)

    # Shell-compat: bare integer positional (e.g. ``little64 boot run 123``) means --max-cycles.
    if args.kernel_elf is not None and args.extra_max_cycles is None and args.max_cycles is None:
        if args.kernel_elf.isdigit():
            args.max_cycles = int(args.kernel_elf)
            args.kernel_elf = None
    if args.extra_max_cycles is not None:
        if args.max_cycles is not None:
            print("error: too many positional arguments", file=sys.stderr)
            return 1
        if not args.extra_max_cycles.isdigit():
            print("error: max cycles must be a positive integer", file=sys.stderr)
            return 1
        args.max_cycles = int(args.extra_max_cycles)

    if not (1 <= args.port <= 65535):
        print("error: port must be an integer in range 1..65535", file=sys.stderr)
        return 1

    root = repo_root()
    emulator = builddir(root) / "little-64"
    emulator_debug = builddir(root) / "little-64-debug"
    runner_bin = emulator_debug if args.mode == "rsp" else emulator
    if not runner_bin.is_file() or not os.access(runner_bin, os.X_OK):
        print(f"error: emulator binary not found at {runner_bin}", file=sys.stderr)
        print(f"hint: build it first with: meson compile -C {builddir(root)}", file=sys.stderr)
        return 1

    user_specified_kernel = args.kernel_elf is not None
    if user_specified_kernel:
        kernel_elf = Path(args.kernel_elf).expanduser()
        if not kernel_elf.is_file():
            print(f"error: kernel ELF not found at {kernel_elf}", file=sys.stderr)
            print(f"hint: build it first with: little64 kernel build --machine {args.machine} vmlinux -j1", file=sys.stderr)
            return 1
    else:
        kernel_elf = default_kernel_for_machine(args.machine)

    if args.machine == "litex":
        _ensure_litex_kernel_support(kernel_elf)

    if not user_specified_kernel:
        ensure_default_machine_kernel_matches_defconfig(args.machine, kernel_elf)

    # Rootfs selection.
    attach_rootfs = True
    rootfs_image: Optional[Path] = None
    if args.no_rootfs:
        attach_rootfs = False
    elif args.rootfs:
        rootfs_image = Path(args.rootfs).expanduser()
    else:
        env_rootfs = os.environ.get("LITTLE64_ROOTFS_IMAGE")
        if env_rootfs:
            rootfs_image = Path(env_rootfs)
        else:
            # Default: let the SD builder regenerate the ext4 image itself.
            rootfs_image = None

    if attach_rootfs and rootfs_image is not None and not rootfs_image.is_file():
        print(f"error: rootfs image not found at {rootfs_image}", file=sys.stderr)
        print("hint: build it first with: little64 rootfs build", file=sys.stderr)
        print("hint: or boot without a root disk via: little64 boot run --no-rootfs", file=sys.stderr)
        return 1

    python_bin = resolve_python_bin(root)
    ensure_litex_python_env(python_bin)

    profile = resolve_litex_machine_profile(root=root, machine=args.machine)
    output_dir = profile.output_dir
    cpu_variant = profile.cpu_variant
    litex_target = profile.litex_target
    ram_size = profile.ram_size

    # Optional targeted LR / memory write-watch instrumentation (opt-in via env).
    if os.environ.get("LITTLE64_TRACE_LR") == "1":
        os.environ.setdefault("LITTLE64_TRACE_LR_START", "0xffffffc0000ad000")
        os.environ.setdefault("LITTLE64_TRACE_LR_END", "0xffffffc0000b4700")
        print(
            f"[little64] lr trace enabled: pc in [{os.environ['LITTLE64_TRACE_LR_START']}, {os.environ['LITTLE64_TRACE_LR_END']}]",
            file=sys.stderr,
        )
    if os.environ.get("LITTLE64_TRACE_WATCH") == "1":
        os.environ.setdefault("LITTLE64_TRACE_WATCH_START", "0xffffffc0006a3f40")
        os.environ.setdefault("LITTLE64_TRACE_WATCH_END", "0xffffffc0006a3f70")
        print(
            f"[little64] watch trace enabled: addr in [{os.environ['LITTLE64_TRACE_WATCH_START']}, {os.environ['LITTLE64_TRACE_WATCH_END']}]",
            file=sys.stderr,
        )

    artifacts = _prepare_litex_artifacts(
        kernel_elf=kernel_elf,
        output_dir=output_dir,
        cpu_variant=cpu_variant,
        litex_target=litex_target,
        ram_size=ram_size,
        attach_rootfs=attach_rootfs,
        rootfs_image=rootfs_image,
        python_bin=python_bin,
    )

    print(f"[little64] machine    : {args.machine}")
    print(f"[little64] mode       : {args.mode}")
    print(f"[little64] launch     : {args.launch}{'  (post-stage0 state)' if args.launch == 'direct' else '  (full stage-0 SD boot)'}")
    print(f"[little64] kernel ELF : {kernel_elf}")
    print(f"[little64] DT source  : {artifacts['dts']}")
    print(f"[little64] stage0     : {artifacts['bootrom']}")
    print(f"[little64] sd image   : {artifacts['sd']}")
    if attach_rootfs:
        if rootfs_image is not None:
            print(f"[little64] rootfs     : {rootfs_image}")
        else:
            print("[little64] rootfs     : auto-generated ext4 from target/linux_port/rootfs/init.S")
    else:
        print("[little64] rootfs     : disabled (--no-rootfs)")
    if args.max_cycles is not None:
        print(f"[little64] max cycles : {args.max_cycles}")

    boot_events_file = os.environ.get("LITTLE64_BOOT_EVENTS_FILE", "/tmp/little64_boot_events.l64t")
    boot_log = os.environ.get("LITTLE64_BOOT_LOG", "/tmp/little64_boot.log")
    events_max_mb = os.environ.get("LITTLE64_BOOT_EVENTS_MAX_MB", "500")

    extra_direct_args: list[str] = []
    if args.launch == "direct":
        direct_kernel_physical_base = os.environ.get("LITTLE64_DIRECT_KERNEL_PHYSICAL_BASE")
        if direct_kernel_physical_base is None:
            inferred_base = _infer_direct_kernel_physical_base(kernel_elf)
            if inferred_base is None:
                inferred_base = DEFAULT_DIRECT_KERNEL_PHYSICAL_BASE
            direct_kernel_physical_base = f"0x{inferred_base:x}"

        emu_boot_mode = "direct"
        emu_image = kernel_elf
        extra_direct_args = [
            f"--direct-dtb={artifacts['dtb']}",
            f"--direct-stack-reserve-bytes={os.environ.get('LITTLE64_DIRECT_STACK_RESERVE_BYTES', str(DEFAULT_STAGE0_STACK_RESERVE_BYTES))}",
            f"--direct-kernel-physical-base={direct_kernel_physical_base}",
        ]
        print(f"[little64] direct phys: {direct_kernel_physical_base}")
    else:
        emu_boot_mode = "litex-bootrom"
        emu_image = artifacts["bootrom"]

    if args.mode == "trace":
        emu_args = [
            str(emulator),
            "--trace-mmio", "--boot-events", "--trace-control-flow",
            f"--boot-events-file={boot_events_file}",
            f"--boot-events-max-mb={events_max_mb}",
            f"--boot-mode={emu_boot_mode}",
        ]
        emu_args.extend(extra_direct_args)
        if os.environ.get("LITTLE64_TRACE_START_CYCLE"):
            emu_args.append(f"--trace-start-cycle={os.environ['LITTLE64_TRACE_START_CYCLE']}")
        if os.environ.get("LITTLE64_TRACE_END_CYCLE"):
            emu_args.append(f"--trace-end-cycle={os.environ['LITTLE64_TRACE_END_CYCLE']}")
        _append_common_runtime_args(emu_args, max_cycles=args.max_cycles, attach_rootfs=attach_rootfs, sd_image=artifacts["sd"])
        emu_args.append(str(emu_image))
        try:
            with open(boot_log, "w") as log:
                proc = subprocess.run(emu_args, stderr=log)
            rc = proc.returncode
        finally:
            print("", file=sys.stderr)
            print(f"(boot event log saved to {boot_events_file})", file=sys.stderr)
            print(f"(stderr log saved to {boot_log})", file=sys.stderr)
        return rc

    if args.mode == "smoke":
        emu_args = [str(emulator), f"--boot-mode={emu_boot_mode}"]
        emu_args.extend(extra_direct_args)
        _append_common_runtime_args(emu_args, max_cycles=args.max_cycles, attach_rootfs=attach_rootfs, sd_image=artifacts["sd"])
        emu_args.append(str(emu_image))
        os.execv(emu_args[0], emu_args)
        return 0  # unreachable

    if args.mode == "rsp":
        emu_args = [str(emulator_debug), f"--boot-mode={emu_boot_mode}"]
        emu_args.extend(extra_direct_args)
        _append_common_runtime_args(emu_args, max_cycles=args.max_cycles, attach_rootfs=attach_rootfs, sd_image=artifacts["sd"])
        emu_args.append(str(args.port))
        emu_args.append(str(emu_image))
        print(f"[little64] rsp        : 127.0.0.1:{args.port}")
        try:
            proc = subprocess.run(emu_args)
            rc = proc.returncode
        finally:
            print("", file=sys.stderr)
        return rc

    return 2
