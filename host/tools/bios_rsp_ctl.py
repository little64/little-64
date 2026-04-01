#!/usr/bin/env python3
import argparse
import os
import pathlib
import signal
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
PIDFILE = pathlib.Path("/tmp/little64-bios-rsp.pid")
LOGFILE = pathlib.Path("/tmp/little64-bios-rsp.log")
DEBUG_BIN = ROOT / "builddir" / "little-64-debug"
BIOS_ELF = ROOT / "builddir" / "c_boot_bios.elf"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pid() -> int | None:
    if not PIDFILE.exists():
        return None
    try:
        return int(PIDFILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _cleanup_stale_pidfile() -> None:
    pid = _read_pid()
    if pid is None:
        if PIDFILE.exists():
            PIDFILE.unlink(missing_ok=True)
        return
    if not _pid_alive(pid):
        PIDFILE.unlink(missing_ok=True)


def stop() -> int:
    pid = _read_pid()
    if pid is not None and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        time.sleep(0.1)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    PIDFILE.unlink(missing_ok=True)
    subprocess.run(["pkill", "-f", "little-64-debug 9000"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("stopped")
    return 0


def start() -> int:
    if not DEBUG_BIN.exists():
        print(f"missing debug server binary: {DEBUG_BIN}", file=sys.stderr)
        return 1
    if not BIOS_ELF.exists():
        print(f"missing BIOS ELF: {BIOS_ELF}", file=sys.stderr)
        return 1

    stop()

    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    with LOGFILE.open("ab") as log:
        env = os.environ.copy()
        env["LITTLE64_RSP_TRACE_PATH"] = "/tmp/little64-rsp-trace.log"
        proc = subprocess.Popen(
            [str(DEBUG_BIN), "9000", str(BIOS_ELF)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            start_new_session=True,
            env=env,
        )

    PIDFILE.write_text(f"{proc.pid}\n", encoding="utf-8")
    time.sleep(0.2)

    if proc.poll() is not None:
        print("little64 BIOS RSP failed to stay running; see /tmp/little64-bios-rsp.log", file=sys.stderr)
        try:
            tail = LOGFILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-50:]
            if tail:
                print("\n".join(tail), file=sys.stderr)
        except Exception:
            pass
        PIDFILE.unlink(missing_ok=True)
        return 1

    print(f"little64 BIOS RSP running (pid {proc.pid})")
    return 0


def check() -> int:
    _cleanup_stale_pidfile()
    pid = _read_pid()
    if pid is not None and _pid_alive(pid):
        print(f"running pid {pid}")
        return 0
    print("not running", file=sys.stderr)
    return 1


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
