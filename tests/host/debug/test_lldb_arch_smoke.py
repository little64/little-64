#!/usr/bin/env python3
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
BIN = ROOT / "compilers" / "bin"
MC = BIN / "llvm-mc"
LD = BIN / "ld.lld"
LLDB = BIN / "lldb"


def build_test_elf(tmpdir: pathlib.Path) -> pathlib.Path:
    asm = tmpdir / "lldb_arch_smoke.asm"
    obj = tmpdir / "lldb_arch_smoke.o"
    elf = tmpdir / "lldb_arch_smoke.elf"

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

    with tempfile.TemporaryDirectory(prefix="little64-lldb-arch-") as td:
        tmpdir = pathlib.Path(td)
        elf = build_test_elf(tmpdir)

        res = subprocess.run(
            [
                str(LLDB),
                "--batch",
                "-o",
                f"target create --arch little64 {elf}",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        out = res.stdout
        err = res.stderr
        if res.returncode != 0:
            raise RuntimeError(f"lldb returned {res.returncode}\nSTDOUT:\n{out}\nSTDERR:\n{err}")

        if "(little64)" not in out:
            raise RuntimeError(f"LLDB did not load little64 target as expected\n{out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
