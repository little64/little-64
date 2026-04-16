#!/usr/bin/env python3
import argparse
import pathlib

from rsp_ctl_common import RspController

ROOT = pathlib.Path(__file__).resolve().parents[2]
PIDFILE = pathlib.Path("/tmp/little64-bios-rsp.pid")
LOGFILE = pathlib.Path("/tmp/little64-bios-rsp.log")
DEBUG_BIN = ROOT / "builddir" / "little-64-debug"
BIOS_ELF = ROOT / "builddir" / "c_boot_bios.elf"
DEFAULT_TRACE_PATH = "/tmp/little64-rsp-trace.log"


def make_controller() -> RspController:
    return RspController(
        name="little64 BIOS RSP",
        root=ROOT,
        pidfile=PIDFILE,
        logfile=LOGFILE,
        debug_bin=DEBUG_BIN,
        command=[str(DEBUG_BIN), "9000", str(BIOS_ELF)],
        kill_pattern="little-64-debug 9000",
        startup_delay=0.2,
        default_trace_path=DEFAULT_TRACE_PATH,
        ready_message="little64 BIOS RSP running (pid {pid})",
        status_message="running pid {pid}",
        failure_tail_lines=50,
    )


def stop() -> int:
    return make_controller().stop()


def start() -> int:
    return make_controller().start(required_paths={"BIOS ELF": BIOS_ELF})


def check() -> int:
    return make_controller().check()


def main() -> int:
    parser = argparse.ArgumentParser(description="Control Little64 BIOS RSP debug server")
    parser.add_argument("action", choices=["start", "check", "stop"])
    args = parser.parse_args()

    if args.action == "start":
        return start()
    if args.action == "check":
        return check()
    return stop()


if __name__ == "__main__":
    raise SystemExit(main())
