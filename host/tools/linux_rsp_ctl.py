#!/usr/bin/env python3
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "target" / "linux_port"))

from profile_paths import kernel_path
from rsp_ctl_common import RspController

PIDFILE = pathlib.Path("/tmp/little64-linux-rsp.pid")
LOGFILE = pathlib.Path("/tmp/little64-linux-rsp.log")
DEBUG_BIN = ROOT / "builddir" / "little-64-debug"
DEFAULT_PORT = 9000


def default_elf_path(defconfig_name: str | None = None) -> pathlib.Path:
    return kernel_path(defconfig_name, linux_port_root=ROOT / "target" / "linux_port")


def make_controller(port: int, elf_path: pathlib.Path) -> RspController:
    return RspController(
        name="little64 Linux RSP",
        root=ROOT,
        pidfile=PIDFILE,
        logfile=LOGFILE,
        debug_bin=DEBUG_BIN,
        command=[str(DEBUG_BIN), "--boot-mode=direct", str(port), str(elf_path)],
        kill_pattern=f"little-64-debug --boot-mode=direct {port}",
        startup_delay=0.15,
        ready_message=f"little64 Linux RSP running (pid {{pid}}) on 127.0.0.1:{port}",
        status_message=f"running pid {{pid}} on 127.0.0.1:{port}",
    )


def stop(port: int, defconfig_name: str | None = None) -> int:
    return make_controller(port, default_elf_path(defconfig_name)).stop()


def start(port: int, elf_path: pathlib.Path, trace_path: str | None = None) -> int:
    return make_controller(port, elf_path).start(
        required_paths={"kernel ELF": elf_path},
        trace_path=trace_path,
    )


def check(port: int, defconfig_name: str | None = None) -> int:
    return make_controller(port, default_elf_path(defconfig_name)).check()


def main() -> int:
    parser = argparse.ArgumentParser(description="Control Little64 Linux direct-boot RSP debug server")
    parser.add_argument("action", choices=["start", "check", "stop"])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--defconfig", default=None, help="Little64 Linux defconfig for profile-aware default ELF")
    parser.add_argument("--elf", default=None)
    parser.add_argument("--trace", default=None, help="Optional LITTLE64_RSP_TRACE_PATH output file")
    args = parser.parse_args()

    elf_path = pathlib.Path(args.elf) if args.elf else default_elf_path(args.defconfig)

    if args.action == "start":
        return start(args.port, elf_path, args.trace)
    if args.action == "check":
        return check(args.port, args.defconfig)
    return stop(args.port, args.defconfig)


if __name__ == "__main__":
    raise SystemExit(main())
