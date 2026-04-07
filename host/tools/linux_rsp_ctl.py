#!/usr/bin/env python3
import argparse
import os
import pathlib
import signal
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
PIDFILE = pathlib.Path("/tmp/little64-linux-rsp.pid")
LOGFILE = pathlib.Path("/tmp/little64-linux-rsp.log")
DEBUG_BIN = ROOT / "builddir" / "little-64-debug"
DEFAULT_ELF = ROOT / "target" / "linux_port" / "build" / "vmlinux"
DEFAULT_PORT = 9000


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
        PIDFILE.unlink(missing_ok=True)
        return
    if not _pid_alive(pid):
        PIDFILE.unlink(missing_ok=True)


def stop(port: int) -> int:
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

    # Safety cleanup in case a stale server escaped the pidfile tracking.
    subprocess.run(
        ["pkill", "-f", f"little-64-debug --boot-mode=direct {port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    print("stopped")
    return 0


def start(port: int, elf_path: pathlib.Path, trace_path: str | None = None) -> int:
    if not DEBUG_BIN.exists():
        print(f"missing debug server binary: {DEBUG_BIN}", file=sys.stderr)
        return 1
    if not elf_path.exists():
        print(f"missing kernel ELF: {elf_path}", file=sys.stderr)
        return 1

    stop(port)

    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    with LOGFILE.open("ab") as log:
        env = os.environ.copy()
        if trace_path:
            env["LITTLE64_RSP_TRACE_PATH"] = trace_path
        proc = subprocess.Popen(
            [str(DEBUG_BIN), "--boot-mode=direct", str(port), str(elf_path)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            start_new_session=True,
            env=env,
        )

    PIDFILE.write_text(f"{proc.pid}\n", encoding="utf-8")

    if proc.poll() is not None:
        print("little64 Linux RSP failed to stay running; see /tmp/little64-linux-rsp.log", file=sys.stderr)
        PIDFILE.unlink(missing_ok=True)
        return 1

    # Give the process a moment to initialize before liveness checks.
    time.sleep(0.15)

    if proc.poll() is not None:
        print("little64 Linux RSP exited during startup; see /tmp/little64-linux-rsp.log", file=sys.stderr)
        stop(port)
        return 1

    print(f"little64 Linux RSP running (pid {proc.pid}) on 127.0.0.1:{port}")
    return 0


def check(port: int) -> int:
    _cleanup_stale_pidfile()
    pid = _read_pid()
    if pid is None or not _pid_alive(pid):
        print("not running", file=sys.stderr)
        return 1

    print(f"running pid {pid} on 127.0.0.1:{port}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Control Little64 Linux direct-boot RSP debug server")
    parser.add_argument("action", choices=["start", "check", "stop"])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--elf", default=str(DEFAULT_ELF))
    parser.add_argument("--trace", default=None, help="Optional LITTLE64_RSP_TRACE_PATH output file")
    args = parser.parse_args()

    elf_path = pathlib.Path(args.elf)

    if args.action == "start":
        return start(args.port, elf_path, args.trace)
    if args.action == "check":
        return check(args.port)
    return stop(args.port)


if __name__ == "__main__":
    raise SystemExit(main())
