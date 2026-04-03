#!/usr/bin/env python3
import pathlib
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
BIN = ROOT / "compilers" / "bin"
CLANG = BIN / "clang"
LD = BIN / "ld.lld"
LLDB = BIN / "lldb"
DBG = ROOT / "builddir" / "little-64-debug"
START_C = ROOT / "target" / "c_boot" / "start.c"
LINKER = ROOT / "target" / "c_boot" / "linker_bios.ld"
PORT = "9018"


def build_bios_elf(tmpdir: pathlib.Path) -> pathlib.Path:
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
    return elf


def main() -> int:
    if not LLDB.exists():
        print("SKIP: compilers/bin/lldb not found")
        return 0

    with tempfile.TemporaryDirectory(prefix="little64-lldb-stepover-") as td:
        tmpdir = pathlib.Path(td)
        elf = build_bios_elf(tmpdir)

        cmds = tmpdir / "lldb_step_over.cmds"
        cmds.write_text(
            "target create " + str(elf) + "\n"
            "gdb-remote 127.0.0.1:" + PORT + "\n"
            "breakpoint set --file start.c --line 100\n"
            "continue\n"
            "thread step-over\n"
            "frame info\n"
            "breakpoint set --file start.c --line 103\n"
            "continue\n"
            "thread step-in\n"
            "frame info\n"
            "quit\n",
            encoding="utf-8",
        )

        server = subprocess.Popen(
            [str(DBG), PORT, str(elf)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            time.sleep(0.2)
            res = subprocess.run(
                [str(LLDB), "--batch", "-s", str(cmds)],
                capture_output=True,
                text=True,
                timeout=25,
            )

            out = res.stdout
            err = res.stderr
            if res.returncode != 0:
                raise RuntimeError(f"lldb returned {res.returncode}\nSTDOUT:\n{out}\nSTDERR:\n{err}")

            if "Breakpoint 1:" not in out:
                raise RuntimeError(f"missing breakpoint setup marker\n{out}")
            if "thread step-over" not in out:
                raise RuntimeError(f"missing step-over marker\n{out}")
            if "thread step-in" not in out:
                raise RuntimeError(f"missing step-in marker\n{out}")

            frame_lines = [line.strip() for line in out.splitlines() if line.strip().startswith("frame #0:")]
            if not frame_lines:
                raise RuntimeError(f"no frame info in LLDB output\n{out}")

            final_frame = frame_lines[-1]
            if "start.c:93" not in final_frame:
                raise RuntimeError(
                    "step-in did not resolve source line in mix_debug_value\n"
                    f"Final frame: {final_frame}\n"
                    f"LLDB output:\n{out}"
                )

            if "start.c:102" not in out:
                raise RuntimeError(
                    "single step-over did not advance to next source line\n"
                    f"LLDB output:\n{out}"
                )

            return 0
        finally:
            if server.poll() is None:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
