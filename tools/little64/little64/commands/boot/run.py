"""``little64 boot run`` \u2014 Little64 direct-boot helper for LiteX.

Produces a bootable SDRAM-backed LiteX SD image from a vmlinux, launches the
emulator (optionally with trace capture or the RSP debug server), and surfaces
the resulting exit status.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from little64.paths import (
    builddir,
    compiler_bin,
    effective_defconfig_name,
    existing_kernel_path,
    linux_port_dir,
    repo_root,
)


DEFAULT_MODE = "smoke"
DEFAULT_MACHINE = "litex"
DEFAULT_LITEX_DEFCONFIG_NAME = "little64_litex_sim_defconfig"

REQUIRED_LITEX_KERNEL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("CONFIG_MMC", "y"),
    ("CONFIG_MMC_BLOCK", "y"),
    ("CONFIG_MMC_LITEX", "y"),
    ("CONFIG_FAT_FS", "y"),
    ("CONFIG_MSDOS_FS", "y"),
    ("CONFIG_VFAT_FS", "y"),
    ("CONFIG_MSDOS_PARTITION", "y"),
    ("CONFIG_EXT4_FS", "y"),
    ("CONFIG_LITTLE64_KERNEL_PHYS_BASE", "0x40000000"),
)


def _python_bin(root: Path) -> str:
    override = os.environ.get("LITTLE64_PYTHON")
    if override:
        return override
    venv = root / ".venv" / "bin" / "python"
    if venv.is_file() and os.access(venv, os.X_OK):
        return str(venv)
    return shutil.which("python3") or sys.executable


def _ensure_litex_python_env(python_bin: str) -> None:
    if not python_bin or not shutil.which(python_bin) and not os.path.isfile(python_bin):
        print("error: Python interpreter not found for LiteX artifact generation", file=sys.stderr)
        print("hint: set LITTLE64_PYTHON or create <repo>/.venv", file=sys.stderr)
        sys.exit(1)
    rc = subprocess.run([python_bin, "-c", "import litex"], capture_output=True).returncode
    if rc != 0:
        print("error: selected Python environment does not provide the LiteX package", file=sys.stderr)
        print("hint: activate the repo virtualenv or set LITTLE64_PYTHON to an environment with LiteX installed", file=sys.stderr)
        sys.exit(1)


def _default_defconfig_for_machine(machine: str) -> str:
    if machine == "litex":
        return DEFAULT_LITEX_DEFCONFIG_NAME
    raise SystemExit(f"error: unknown machine: {machine}")


def _default_kernel_for_machine(machine: str) -> Path:
    defconfig = _default_defconfig_for_machine(machine)
    existing = existing_kernel_path(defconfig)
    if existing is not None:
        return existing
    from little64.paths import kernel_path as _kp

    path = _kp(defconfig)
    print(f"error: kernel ELF not found at {path}", file=sys.stderr)
    print(f"hint: build it first with: little64 kernel build --machine {machine} vmlinux -j1", file=sys.stderr)
    sys.exit(1)


def _recorded_defconfig_for_machine(machine: str) -> Optional[str]:
    from little64.paths import built_defconfig_name

    defconfig = _default_defconfig_for_machine(machine)
    try:
        return built_defconfig_name(defconfig)
    except Exception:
        return None


def _kernel_config_path(kernel_path: Path) -> Optional[Path]:
    candidate = kernel_path.resolve().parent / ".config"
    return candidate if candidate.is_file() else None


def _ensure_litex_kernel_support(kernel_path: Path) -> None:
    if os.environ.get("LITTLE64_SKIP_LITEX_KERNEL_CONFIG_CHECK") == "1":
        return
    config_path = _kernel_config_path(kernel_path)
    if config_path is None:
        print(f"error: unable to verify LiteX kernel support for {kernel_path}", file=sys.stderr)
        print("hint: provide a kernel built in a Little64 Linux build directory so the adjacent .config is available", file=sys.stderr)
        print("hint: or set LITTLE64_SKIP_LITEX_KERNEL_CONFIG_CHECK=1 to bypass this verification explicitly", file=sys.stderr)
        sys.exit(1)
    lines = config_path.read_text().splitlines()
    line_set = set(lines)
    for option, expected in REQUIRED_LITEX_KERNEL_OPTIONS:
        if f"{option}={expected}" not in line_set:
            print(f"error: kernel config {config_path} is missing {option}={expected}", file=sys.stderr)
            if option == "CONFIG_LITTLE64_KERNEL_PHYS_BASE":
                print("hint: rebuild the LiteX kernel so the early boot code matches the SDRAM-backed bootrom layout", file=sys.stderr)
                print("hint: run 'little64 kernel build --machine litex clean' then 'little64 kernel build --machine litex vmlinux -j1'", file=sys.stderr)
            sys.exit(1)


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
    root: Path,
) -> dict:
    dts_generator_args = ["hdl", "dts-linux"]
    sd_builder_args = ["sd", "build"]

    if shutil.which("dtc") is None:
        print("error: dtc is required for the LiteX machine profile", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    dts_path = output_dir / "little64-litex-sim.dts"
    dtb_path = output_dir / "little64-litex-sim.dtb"
    bootrom_path = output_dir / "little64-sd-stage0-bootrom.bin"
    sd_path = output_dir / "little64-linux-sdcard.img"

    little64_cli = [python_bin, "-m", "little64"]
    dts_cmd = [
        *little64_cli, *dts_generator_args,
        "--output", str(dts_path),
        "--with-spi-flash", "--with-sdcard", "--with-sdram",
        "--litex-target", litex_target,
        "--boot-source", "bootrom",
        "--cpu-variant", cpu_variant,
    ]
    if ram_size:
        dts_cmd += ["--ram-size", ram_size]
    subprocess.run(dts_cmd, check=True, stdout=subprocess.DEVNULL)

    if (not dtb_path.exists()) or (dtb_path.stat().st_mtime < dts_path.stat().st_mtime):
        subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-o", str(dtb_path), str(dts_path)], check=True)

    builder_cmd = [
        *little64_cli, *sd_builder_args,
        "--kernel-elf", str(kernel_elf),
        "--dtb", str(dtb_path),
        "--bootrom-output", str(bootrom_path),
        "--sd-output", str(sd_path),
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
    subprocess.run(builder_cmd, check=True)

    return {"dts": dts_path, "dtb": dtb_path, "bootrom": bootrom_path, "sd": sd_path}


def _append_common_runtime_args(args: list[str], *, max_cycles: Optional[int], attach_rootfs: bool, sd_image: Path) -> None:
    if max_cycles is not None:
        args.append(f"--max-cycles={max_cycles}")
    if attach_rootfs:
        args.append(f"--disk={sd_image}")
        args.append("--disk-readonly")


def run(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="little64 boot run",
        description="Direct-boot a Little64 kernel ELF (LiteX machine profile).",
    )
    parser.add_argument("--machine", default=DEFAULT_MACHINE, choices=["litex"])
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=["trace", "smoke", "rsp"])
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
        kernel_elf = _default_kernel_for_machine(args.machine)

    if args.machine == "litex":
        _ensure_litex_kernel_support(kernel_elf)

    if not user_specified_kernel:
        active_defconfig = _recorded_defconfig_for_machine(args.machine)
        expected = _default_defconfig_for_machine(args.machine)
        if active_defconfig and active_defconfig != expected:
            print(f"error: default kernel path {kernel_elf} currently points to a {active_defconfig} build", file=sys.stderr)
            print(f"hint: rebuild the LiteX kernel with: little64 kernel build --machine {args.machine} vmlinux -j1", file=sys.stderr)
            print("hint: LiteX kernels now live under target/linux_port/build-litex/ by default", file=sys.stderr)
            print("hint: or pass an explicit kernel path that matches the selected machine profile", file=sys.stderr)
            return 1

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

    python_bin = _python_bin(root)
    _ensure_litex_python_env(python_bin)

    output_dir = Path(os.environ.get("LITTLE64_LITEX_OUTPUT_DIR") or builddir(root) / "boot-direct-litex")
    cpu_variant = os.environ.get("LITTLE64_LITEX_CPU_VARIANT", "standard")
    litex_target = os.environ.get("LITTLE64_LITEX_TARGET", "arty-a7-35")
    ram_size = os.environ.get("LITTLE64_LITEX_RAM_SIZE") or None

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
        root=root,
    )

    print(f"[little64] machine    : {args.machine}")
    print(f"[little64] mode       : {args.mode}")
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

    if args.mode == "trace":
        emu_args = [
            str(emulator),
            "--trace-mmio", "--boot-events", "--trace-control-flow",
            f"--boot-events-file={boot_events_file}",
            f"--boot-events-max-mb={events_max_mb}",
            "--boot-mode=litex-bootrom",
        ]
        if os.environ.get("LITTLE64_TRACE_START_CYCLE"):
            emu_args.append(f"--trace-start-cycle={os.environ['LITTLE64_TRACE_START_CYCLE']}")
        if os.environ.get("LITTLE64_TRACE_END_CYCLE"):
            emu_args.append(f"--trace-end-cycle={os.environ['LITTLE64_TRACE_END_CYCLE']}")
        _append_common_runtime_args(emu_args, max_cycles=args.max_cycles, attach_rootfs=attach_rootfs, sd_image=artifacts["sd"])
        emu_args.append(str(artifacts["bootrom"]))
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
        emu_args = [str(emulator), "--boot-mode=litex-bootrom"]
        _append_common_runtime_args(emu_args, max_cycles=args.max_cycles, attach_rootfs=attach_rootfs, sd_image=artifacts["sd"])
        emu_args.append(str(artifacts["bootrom"]))
        os.execv(emu_args[0], emu_args)
        return 0  # unreachable

    if args.mode == "rsp":
        emu_args = [str(emulator_debug), "--boot-mode=litex-bootrom"]
        _append_common_runtime_args(emu_args, max_cycles=args.max_cycles, attach_rootfs=attach_rootfs, sd_image=artifacts["sd"])
        emu_args.append(str(args.port))
        emu_args.append(str(artifacts["bootrom"]))
        print(f"[little64] rsp        : 127.0.0.1:{args.port}")
        try:
            proc = subprocess.run(emu_args)
            rc = proc.returncode
        finally:
            print("", file=sys.stderr)
        return rc

    return 2
