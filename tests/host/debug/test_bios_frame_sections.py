#!/usr/bin/env python3
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
BIN = ROOT / "compilers" / "bin"
CLANG = BIN / "clang"
LD = BIN / "ld.lld"
READELF = BIN / "llvm-readelf"
START_C = ROOT / "target" / "c_boot" / "start.c"
LINKER = ROOT / "target" / "c_boot" / "linker_bios.ld"


def section_table(path: pathlib.Path) -> str:
    result = subprocess.run(
        [str(READELF), "-S", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="little64-bios-frame-") as td:
        tmpdir = pathlib.Path(td)
        obj = tmpdir / "c_boot_bios.o"
        elf = tmpdir / "c_boot_bios.elf"

        subprocess.run(
            [
                str(CLANG),
                "-target",
                "little64",
                "-O0",
                "-gdwarf-4",
                "-fno-omit-frame-pointer",
                "-funwind-tables",
                "-fasynchronous-unwind-tables",
                "-fforce-dwarf-frame",
                "-ffreestanding",
                "-I",
                str(ROOT / "host" / "boot"),
                "-c",
                str(START_C),
                "-o",
                str(obj),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        subprocess.run(
            [str(LD), str(obj), "-o", str(elf), "-T", str(LINKER)],
            check=True,
            capture_output=True,
            text=True,
        )

        obj_sections = section_table(obj)
        elf_sections = section_table(elf)

        for name in (".eh_frame", ".debug_frame"):
            if name not in obj_sections:
                raise RuntimeError(f"missing {name} in object file\n{obj_sections}")
            if name not in elf_sections:
                raise RuntimeError(f"missing {name} in linked ELF\n{elf_sections}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
