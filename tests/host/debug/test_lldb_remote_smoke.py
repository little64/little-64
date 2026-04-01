#!/usr/bin/env python3
import pathlib
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
BIN = ROOT / "compilers" / "bin"
MC = BIN / "llvm-mc"
LD = BIN / "ld.lld"
LLDB = BIN / "lldb"
DBG = ROOT / "builddir" / "little-64-debug"
PORT = "9017"


def build_test_elf(tmpdir: pathlib.Path) -> pathlib.Path:
    asm = tmpdir / "lldb_smoke.asm"
    obj = tmpdir / "lldb_smoke.o"
    elf = tmpdir / "lldb_smoke.elf"

    asm.write_text(
        ".global _start\n"
        "_start:\n"
        "  STOP\n",
        encoding="utf-8",
    )

    subprocess.run(
        [str(MC), "-triple=little64", "-filetype=obj", str(asm), "-o", str(obj)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [str(LD), str(obj), "-o", str(elf)],
        check=True,
        capture_output=True,
        text=True,
    )
    return elf


def main() -> int:
    if not LLDB.exists():
        print("SKIP: compilers/bin/lldb not found")
        return 0

    with tempfile.TemporaryDirectory(prefix="little64-lldb-") as td:
        tmpdir = pathlib.Path(td)
        elf = build_test_elf(tmpdir)

        server = subprocess.Popen(
            [str(DBG), PORT, str(elf)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            time.sleep(0.2)
            res = subprocess.run(
                [
                    str(LLDB),
                    "--batch",
                    "-o",
                    f"gdb-remote 127.0.0.1:{PORT}",
                    "-o",
                    "process continue",
                ],
                capture_output=True,
                text=True,
                timeout=25,
            )

            out = res.stdout
            err = res.stderr
            if res.returncode != 0:
                raise RuntimeError(f"lldb returned {res.returncode}\nSTDOUT:\n{out}\nSTDERR:\n{err}")

            if "Process 1 stopped" not in out:
                raise RuntimeError(f"missing attach stop marker in LLDB output\n{out}")
            if "Process 1 exited with status = 0" not in out:
                raise RuntimeError(f"missing clean exit marker in LLDB output\n{out}")

            return 0
        finally:
            if server.poll() is None:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
