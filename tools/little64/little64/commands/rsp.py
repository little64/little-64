"""``little64 rsp`` — control BIOS and Linux RSP debug servers.

Subcommand tree backed by :class:`little64.rsp.RspController`.
"""

from __future__ import annotations

import argparse
import pathlib
from typing import List, Optional

from little64 import paths
from little64.rsp import RspController


BIOS_PIDFILE = pathlib.Path("/tmp/little64-bios-rsp.pid")
BIOS_LOGFILE = pathlib.Path("/tmp/little64-bios-rsp.log")
BIOS_DEFAULT_TRACE_PATH = "/tmp/little64-rsp-trace.log"

LINUX_PIDFILE = pathlib.Path("/tmp/little64-linux-rsp.pid")
LINUX_LOGFILE = pathlib.Path("/tmp/little64-linux-rsp.log")
LINUX_DEFAULT_PORT = 9000


def _debug_bin() -> pathlib.Path:
    return paths.builddir() / "little-64-debug"


def _bios_elf() -> pathlib.Path:
    return paths.builddir() / "c_boot_bios.elf"


def _make_bios_controller() -> RspController:
    debug_bin = _debug_bin()
    return RspController(
        name="little64 BIOS RSP",
        root=paths.repo_root(),
        pidfile=BIOS_PIDFILE,
        logfile=BIOS_LOGFILE,
        debug_bin=debug_bin,
        command=[str(debug_bin), "9000", str(_bios_elf())],
        kill_pattern="little-64-debug 9000",
        startup_delay=0.2,
        default_trace_path=BIOS_DEFAULT_TRACE_PATH,
        ready_message="little64 BIOS RSP running (pid {pid})",
        status_message="running pid {pid}",
        failure_tail_lines=50,
    )


def _make_linux_controller(port: int, elf_path: pathlib.Path) -> RspController:
    debug_bin = _debug_bin()
    return RspController(
        name="little64 Linux RSP",
        root=paths.repo_root(),
        pidfile=LINUX_PIDFILE,
        logfile=LINUX_LOGFILE,
        debug_bin=debug_bin,
        command=[str(debug_bin), "--boot-mode=direct", str(port), str(elf_path)],
        kill_pattern=f"little-64-debug --boot-mode=direct {port}",
        startup_delay=0.15,
        ready_message=f"little64 Linux RSP running (pid {{pid}}) on 127.0.0.1:{port}",
        status_message=f"running pid {{pid}} on 127.0.0.1:{port}",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="little64 rsp",
        description="Control Little64 RSP debug servers (BIOS and Linux direct-boot).",
    )
    sub = parser.add_subparsers(dest="target", required=True, metavar="<target>")

    bios = sub.add_parser("bios", help="BIOS RSP debug server (builddir/c_boot_bios.elf, port 9000)")
    bios.add_argument("action", choices=["start", "check", "stop"])

    linux = sub.add_parser("linux", help="Linux direct-boot RSP debug server")
    linux.add_argument("action", choices=["start", "check", "stop"])
    linux.add_argument("--port", type=int, default=LINUX_DEFAULT_PORT)
    linux.add_argument(
        "--defconfig",
        default=None,
        help="Little64 Linux defconfig for profile-aware default kernel ELF",
    )
    linux.add_argument("--elf", default=None, help="Override kernel ELF path")
    linux.add_argument(
        "--trace",
        default=None,
        help="Optional LITTLE64_RSP_TRACE_PATH output file",
    )

    return parser


def _run_bios(action: str) -> int:
    ctrl = _make_bios_controller()
    if action == "start":
        return ctrl.start(required_paths={"BIOS ELF": _bios_elf()})
    if action == "check":
        return ctrl.check()
    return ctrl.stop()


def _run_linux(action: str, port: int, defconfig: Optional[str], elf: Optional[str], trace: Optional[str]) -> int:
    elf_path = pathlib.Path(elf) if elf else paths.kernel_path(defconfig)
    ctrl = _make_linux_controller(port, elf_path)
    if action == "start":
        return ctrl.start(required_paths={"kernel ELF": elf_path}, trace_path=trace)
    if action == "check":
        return ctrl.check()
    return ctrl.stop()


def run(argv: List[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.target == "bios":
        return _run_bios(args.action)
    return _run_linux(args.action, args.port, args.defconfig, args.elf, args.trace)
