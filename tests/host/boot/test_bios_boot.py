#!/usr/bin/env python3
import argparse
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
BIN = ROOT / "compilers" / "bin"
CLANG = BIN / "clang"
LD = BIN / "ld.lld"
EMU = ROOT / "builddir" / "little-64"

VALID_OPT_LEVELS = ("0", "1", "2", "3", "s", "z")

MULDI3_STUB_SOURCE = """
__attribute__((used))
long long __muldi3(long long a, long long b) {
    unsigned long long ua = (unsigned long long)a;
    unsigned long long ub = (unsigned long long)b;
    unsigned long long res = 0;

    while (ub != 0ULL) {
        if ((ub & 1ULL) != 0ULL) {
            res += ua;
        }
        ua <<= 1;
        ub >>= 1;
    }

    return (long long)res;
}
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile BIOS boot C startup and run it in emulator")
    parser.add_argument(
        "--opt",
        default="0",
        choices=VALID_OPT_LEVELS,
        help="Optimization level suffix for -O (default: 0)",
    )
    return parser.parse_args()


def run_checked(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        details = []
        if exc.stdout:
            details.append(f"stdout:\n{exc.stdout}")
        if exc.stderr:
            details.append(f"stderr:\n{exc.stderr}")
        suffix = "\n\n" + "\n\n".join(details) if details else ""
        raise RuntimeError(f"Command failed: {' '.join(cmd)}{suffix}") from exc


def main() -> int:
    args = parse_args()
    builddir = ROOT / "builddir"
    builddir.mkdir(parents=True, exist_ok=True)

    obj = builddir / f"test_bios_boot_O{args.opt}.o"
    mul_stub_src = builddir / "test_muldi3_stub.c"
    mul_stub_obj = builddir / "test_muldi3_stub.o"
    elf = builddir / f"test_bios_boot_O{args.opt}.elf"

    mul_stub_src.write_text(MULDI3_STUB_SOURCE + "\n", encoding="utf-8")

    run_checked(
        [
            str(CLANG),
            "-target",
            "little64",
            f"-O{args.opt}",
            "-g",
            "-ffreestanding",
            f"-I{ROOT / 'host' / 'boot'}",
            "-c",
            str(ROOT / "target" / "c_boot" / "start.c"),
            "-o",
            str(obj),
        ],
    )

    run_checked(
        [
            str(CLANG),
            "-target",
            "little64",
            "-O0",
            "-ffreestanding",
            "-c",
            str(mul_stub_src),
            "-o",
            str(mul_stub_obj),
        ],
    )

    run_checked(
        [
            str(LD),
            str(obj),
            str(mul_stub_obj),
            "-o",
            str(elf),
            "-T",
            str(ROOT / "target" / "c_boot" / "linker_bios.ld"),
        ],
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
