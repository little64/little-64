from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from little64 import proc
from little64.paths import compiler_bin


@dataclass(frozen=True)
class Stage0CompileUnit:
    source: Path
    object_name: str
    extra_cflags: tuple[str, ...] = ()


def run_checked(command: Sequence[str | Path], *, cwd: Path | None = None) -> None:
    """Back-compat shim; prefer :func:`little64.proc.run` in new code."""
    proc.run(command, cwd=cwd, check=True)


def build_stage0_binary(
    *,
    compile_units: Sequence[Stage0CompileUnit],
    linker_script: Path,
    work_dir: Path,
    output_stem: str,
    optimization: str,
    generated_header_dir: Path | None = None,
    extra_include_dirs: Sequence[Path] = (),
    force_include_headers: Sequence[Path] = (),
    extra_cflags: Sequence[str] = (),
) -> bytes:
    work_dir.mkdir(parents=True, exist_ok=True)

    common_cflags: list[str | Path] = [
        '-target', 'little64',
        optimization,
        '-ffreestanding',
        '-fno-builtin',
        '-fomit-frame-pointer',
        '-fno-stack-protector',
        '-fno-unwind-tables',
        '-fno-asynchronous-unwind-tables',
    ]
    if generated_header_dir is not None:
        common_cflags += ['-I', generated_header_dir]
    for include_dir in extra_include_dirs:
        common_cflags += ['-I', include_dir]
    for header_path in force_include_headers:
        common_cflags += ['-include', header_path]
    common_cflags += list(extra_cflags)

    tools = compiler_bin()
    object_paths: list[Path] = []
    for unit in compile_units:
        object_path = work_dir / unit.object_name
        run_checked([
            tools / 'clang',
            *common_cflags,
            *unit.extra_cflags,
            '-c', unit.source,
            '-o', object_path,
        ])
        object_paths.append(object_path)

    elf_path = work_dir / f'{output_stem}.elf'
    bin_path = work_dir / f'{output_stem}.bin'
    run_checked([
        tools / 'ld.lld',
        *object_paths,
        '-o', elf_path,
        '-T', linker_script,
    ])
    run_checked([
        tools / 'llvm-objcopy',
        '-O', 'binary',
        elf_path,
        bin_path,
    ])
    return bin_path.read_bytes()