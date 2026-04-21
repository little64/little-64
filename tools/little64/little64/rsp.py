"""Lifecycle controller for Little64 RSP debug servers.

Concrete BIOS/Linux controllers live in :mod:`little64.commands.rsp`.
"""

from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import sys
import time
from typing import Optional


class RspController:
    def __init__(
        self,
        *,
        name: str,
        root: pathlib.Path,
        pidfile: pathlib.Path,
        logfile: pathlib.Path,
        debug_bin: pathlib.Path,
        command: list[str],
        kill_pattern: str,
        startup_delay: float = 0.2,
        default_trace_path: Optional[str] = None,
        ready_message: Optional[str] = None,
        status_message: Optional[str] = None,
        failure_tail_lines: int = 0,
    ) -> None:
        self.name = name
        self.root = root
        self.pidfile = pidfile
        self.logfile = logfile
        self.debug_bin = debug_bin
        self.command = command
        self.kill_pattern = kill_pattern
        self.startup_delay = startup_delay
        self.default_trace_path = default_trace_path
        self.ready_message = ready_message
        self.status_message = status_message
        self.failure_tail_lines = failure_tail_lines

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _read_pid(self) -> Optional[int]:
        if not self.pidfile.exists():
            return None
        try:
            return int(self.pidfile.read_text(encoding="utf-8").strip())
        except Exception:
            return None

    def cleanup_stale_pidfile(self) -> None:
        pid = self._read_pid()
        if pid is None:
            self.pidfile.unlink(missing_ok=True)
            return
        if not self._pid_alive(pid):
            self.pidfile.unlink(missing_ok=True)

    def _print_missing_path(self, label: str, path: pathlib.Path) -> int:
        print(f"missing {label}: {path}", file=sys.stderr)
        return 1

    def stop(self) -> int:
        pid = self._read_pid()
        if pid is not None and self._pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            time.sleep(0.1)
            if self._pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

        self.pidfile.unlink(missing_ok=True)
        subprocess.run(
            ["pkill", "-f", self.kill_pattern],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        print("stopped")
        return 0

    def start(self, *, required_paths: dict[str, pathlib.Path], trace_path: Optional[str] = None) -> int:
        if not self.debug_bin.exists():
            return self._print_missing_path("debug server binary", self.debug_bin)

        for label, path in required_paths.items():
            if not path.exists():
                return self._print_missing_path(label, path)

        self.stop()

        self.logfile.parent.mkdir(parents=True, exist_ok=True)
        with self.logfile.open("ab") as log:
            env = os.environ.copy()
            effective_trace_path = trace_path or self.default_trace_path
            if effective_trace_path:
                env["LITTLE64_RSP_TRACE_PATH"] = effective_trace_path

            proc = subprocess.Popen(
                self.command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(self.root),
                start_new_session=True,
                env=env,
            )

        self.pidfile.write_text(f"{proc.pid}\n", encoding="utf-8")
        time.sleep(self.startup_delay)

        if proc.poll() is not None:
            print(f"{self.name} failed to stay running; see {self.logfile}", file=sys.stderr)
            if self.failure_tail_lines > 0:
                try:
                    tail = self.logfile.read_text(encoding="utf-8", errors="ignore").splitlines()[
                        -self.failure_tail_lines :
                    ]
                    if tail:
                        print("\n".join(tail), file=sys.stderr)
                except Exception:
                    pass
            self.pidfile.unlink(missing_ok=True)
            return 1

        message = self.ready_message or f"{self.name} running (pid {proc.pid})"
        print(message.format(pid=proc.pid))
        return 0

    def check(self) -> int:
        self.cleanup_stale_pidfile()
        pid = self._read_pid()
        if pid is None or not self._pid_alive(pid):
            print("not running", file=sys.stderr)
            return 1

        message = self.status_message or "running pid {pid}"
        print(message.format(pid=pid))
        return 0
