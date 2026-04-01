#!/usr/bin/env python3
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
BIN = ROOT / "compilers" / "bin"
CLANG = BIN / "clang"
LD = BIN / "ld.lld"
EMU = ROOT / "builddir" / "little-64"


def main() -> int:
    builddir = ROOT / "builddir"
    builddir.mkdir(parents=True, exist_ok=True)

    obj = builddir / "test_bios_boot.o"
    elf = builddir / "test_bios_boot.elf"

    subprocess.run(
        [
            str(CLANG),
            "-target",
            "little64",
            "-O0",
            "-g",
            "-ffreestanding",
            f"-I{ROOT / 'host' / 'boot'}",
            "-c",
            str(ROOT / "target" / "c_boot" / "start.c"),
            "-o",
            str(obj),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            str(LD),
            str(obj),
            "-o",
            str(elf),
            "-T",
            str(ROOT / "target" / "c_boot" / "linker_bios.ld"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    res = subprocess.run(
        [str(EMU), str(elf)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )

    out = res.stdout
    if "BIOS READY" not in out:
        raise RuntimeError(f"Missing BIOS banner in emulator output:\n{out}")
    if "BOOT MODE: PHYS" not in out:
        raise RuntimeError(f"Missing boot mode marker in emulator output:\n{out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
