"""Deterministic cycle-based HDL performance benchmark for Little-64 cores.

Usage
-----
  # Default: compare v2 vs v3 assembly micro-benchmarks
  ./.venv/bin/python hdl/tests/perf_bench.py

  # All supported variants
  ./.venv/bin/python hdl/tests/perf_bench.py --variants all

  # Single variant (no speedup table)
  ./.venv/bin/python hdl/tests/perf_bench.py --variants v3

  # Compare cache topology on v3
  ./.venv/bin/python hdl/tests/perf_bench.py --variants v3 --cache-topology split

  # Sweep all cache topologies in one command
  ./.venv/bin/python hdl/tests/perf_bench.py --variants v3 --cache-topology all

  # Quick regression check after perf-critical changes (no CoreMark)
  ./.venv/bin/python hdl/tests/perf_bench.py --variants v2,v3 --repeats 2 \\
      --cache-topology unified

  # Full regression suite with CoreMark (requires CoreMark source tree)
  ./.venv/bin/python hdl/tests/perf_bench.py \\
      --variants v2,v3 --coremark-src ~/coremark --coremark-total-data-size 128

Performance is measured as simulated cycle count, which is independent of
host wall-clock speed.  CoreMark/MHz = iterations * 1e6 / cycles.

Benchmarks included:
    - alu_loop: Basic arithmetic operations (~9k cycles)
    - branchy_loop: Forward-taken branch-heavy code (~26k cycles)
    - branchy_back_loop: Backward-branch-heavy code (predictor-friendly, ~18k cycles)
  - memory_unrolled: Memory load/store patterns (~800-1000 cycles)
    - mixed_loop: Combined ALU + memory (~7k-12k cycles)
  - nested_loop: Triple-nested loop, intermediate workload (~5000-15000 cycles)
  - coremark (optional): Full CoreMark benchmark (~100k+ cycles with reduced size)
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import geometric_mean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
HDL_ROOT = REPO_ROOT / "hdl"
TESTS_ROOT = HDL_ROOT / "tests"

sys.path.insert(0, str(HDL_ROOT))
sys.path.insert(0, str(TESTS_ROOT))

from little64_cores.config import CACHE_TOPOLOGIES, Little64CoreConfig, SUPPORTED_CORE_VARIANTS  # noqa: E402
from shared_program import run_program_source, run_elf_flat  # noqa: E402

CLANG = REPO_ROOT / "compilers" / "bin" / "clang"
LD = REPO_ROOT / "compilers" / "bin" / "ld.lld"
PORTME_DIR = REPO_ROOT / "target" / "coremark_hdl"


# ---------------------------------------------------------------------------
# Case types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AsmCase:
    """Assembly-source micro-benchmark case."""
    name: str
    source: str
    max_cycles: int


@dataclass(frozen=True, slots=True)
class ElfCase:
    """Pre-compiled ELF benchmark case."""
    name: str
    elf_path: Path
    iterations: int    # loop count baked into the ELF; used for CM/MHz
    max_cycles: int    # initial cycle budget (auto-expanded up to cycle_cap)
    cycle_cap: int     # hard upper bound on the cycle budget


# ---------------------------------------------------------------------------
# Assembly case builders
# ---------------------------------------------------------------------------

def _make_alu_loop_case(iterations: int) -> AsmCase:
    lines = [
        "LDI #1, R1",
        "LDI #2, R2",
        "LDI #0, R3",
    ]
    for _ in range(iterations):
        lines.extend([
            "ADD R1, R3",
            "SUB R2, R3",
            "ADD R2, R3",
        ])
    lines.append("STOP")
    return AsmCase(
        name=f"alu_loop_{iterations}",
        source="\n".join(lines),
        max_cycles=(iterations * 12) + 256,
    )


def _make_branchy_loop_case(iterations: int) -> AsmCase:
    lines = [
        "LDI #1, R1",
        "LDI #0, R3",
    ]
    for idx in range(iterations):
        lines.extend([
            "TEST R1, R1",
            f"JUMP.Z @nz_skip_{idx}",
            "ADD R1, R3",
            f"nz_skip_{idx}:",
            "TEST R0, R0",
            f"JUMP.Z @z_taken_{idx}",
            "ADD R2, R3",
            f"z_taken_{idx}:",
        ])
    lines.append("STOP")
    return AsmCase(
        name=f"branchy_loop_{iterations}",
        source="\n".join(lines),
        max_cycles=(iterations * 20) + 256,
    )


def _make_branchy_back_loop_case(iterations: int) -> AsmCase:
    """Branch-heavy loop that emphasizes taken backward branches.

    This case complements branchy_loop by stressing the predictor path where
    backward conditional branches are expected to be predicted taken.
    """
    lines = [
        "LDI #1, R1",
        f"LDI #{iterations}, R2",
        "LDI #0, R3",
        "loop:",
        "TEST R0, R1",
        "JUMP.Z @skip_add",
        "ADD R1, R3",
        "skip_add:",
        "SUB R1, R2",
        "TEST R0, R2",
        "JUMP.Z @done",
        "TEST R1, R1",
        "JUMP.Z @loop",
        "done:",
        "STOP",
    ]
    return AsmCase(
        name=f"branchy_back_loop_{iterations}",
        source="\n".join(lines),
        max_cycles=(iterations * 20) + 512,
    )


def _make_memory_unrolled_case(ops: int) -> AsmCase:
    lines = [
        "LDI #0x20, R2",
        "LDI.S1 #0x10, R2",
        "LDI #1, R1",
        "LDI #0, R3",
    ]
    for _ in range(ops):
        lines.extend(["STORE [R2], R1", "LOAD [R2], R4", "ADD R4, R3"])
    lines.append("STOP")
    return AsmCase(
        name=f"memory_unrolled_{ops}",
        source="\n".join(lines),
        max_cycles=(ops * 20) + 256,
    )


def _make_mixed_loop_case(iterations: int) -> AsmCase:
    lines = [
        "LDI #0x40, R2",
        "LDI.S1 #0x20, R2",
        "LDI #1, R1",
        "LDI #0, R3",
    ]
    for _ in range(iterations):
        lines.extend([
            "STORE [R2], R1",
            "LOAD [R2], R4",
            "ADD R4, R3",
            "ADD R1, R3",
        ])
    lines.append("STOP")
    return AsmCase(
        name=f"mixed_loop_{iterations}",
        source="\n".join(lines),
        max_cycles=(iterations * 24) + 512,
    )


def _make_nested_loop_case(ops: int) -> AsmCase:
    """Extended memory access loop for intermediate-complexity benchmark.

    Extends memory_unrolled pattern with more operations.
    Intermediate complexity between quick micro-benchmarks and full CoreMark.
    Typical runtime: 4,000-15,000 cycles depending on cache topology and core variant.
    """
    lines = [
        "LDI #0x40, R2",
        "LDI.S1 #0x20, R2",
        "LDI #1, R1",
        "LDI #0, R3",
    ]
    # Unrolled memory operations
    for _ in range(ops):
        lines.extend([
            "STORE [R2], R1",
            "LOAD [R2], R4",
            "ADD R4, R3",
            "STORE [R2], R3",
            "LOAD [R2], R5",
            "ADD R5, R3",
        ])
    lines.append("STOP")
    return AsmCase(
        name=f"nested_loop_{ops}",
        source="\n".join(lines),
        max_cycles=(ops * 30) + 512,
    )


def _default_asm_cases() -> list[AsmCase]:
    return [
        # Keep quick-regression runtime short while making short cases less
        # dominated by pipeline warm-up/fill overhead.
        _make_alu_loop_case(2000),
        _make_branchy_loop_case(2000),
        _make_branchy_back_loop_case(2000),
        _make_memory_unrolled_case(96),
        _make_mixed_loop_case(1024),
        _make_nested_loop_case(256),  # intermediate complexity: ~8k cycles
    ]


# ---------------------------------------------------------------------------
# CoreMark compilation
# ---------------------------------------------------------------------------

_COREMARK_SOURCES = [
    "core_main.c",
    "core_list_join.c",
    "core_matrix.c",
    "core_state.c",
    "core_util.c",
]


def compile_coremark(
    coremark_src: Path,
    *,
    iterations: int = 1,
    total_data_size: int = 2000,
    opt: str = "2",
    build_dir: Path,
) -> Path:
    """Compile CoreMark for the Little-64 HDL harness.

    *coremark_src* must be the directory containing ``core_main.c`` and the
    other standard CoreMark C sources.  Returns the path to the linked ELF.
    """
    if not CLANG.exists():
        raise RuntimeError(f"Little-64 clang not found: {CLANG}")
    if not LD.exists():
        raise RuntimeError(f"Little-64 lld not found: {LD}")

    builtins_candidates = sorted(
        (REPO_ROOT / "compilers" / "lib" / "clang").glob("*/lib/baremetal/libclang_rt.builtins-little64.a")
    )
    if not builtins_candidates:
        builtins_candidates = sorted(
            (REPO_ROOT / "compilers" / "lib" / "clang").glob("*/lib/libclang_rt.builtins-little64.a")
        )
    if not builtins_candidates:
        raise RuntimeError("Could not locate libclang_rt.builtins-little64.a under compilers/lib/clang")
    builtins_lib = builtins_candidates[-1]

    portme_files = [
        PORTME_DIR / "core_portme.h",
        PORTME_DIR / "core_portme.c",
        PORTME_DIR / "crt0_hdl.c",
        PORTME_DIR / "linker_hdl.ld",
    ]
    for f in portme_files:
        if not f.exists():
            raise RuntimeError(f"CoreMark portme file missing: {f}")

    for name in _COREMARK_SOURCES:
        if not (coremark_src / name).exists():
            raise FileNotFoundError(
                f"CoreMark source not found: {coremark_src / name}"
            )

    build_dir.mkdir(parents=True, exist_ok=True)

    common_cflags = [
        str(CLANG),
        "-target", "little64",
        f"-O{opt}",
        "-ffreestanding",
        "-fno-builtin",
        f"-I{coremark_src}",
        f"-I{PORTME_DIR}",
        f"-DITERATIONS={iterations}",
        f"-DTOTAL_DATA_SIZE={total_data_size}",
    ]

    compiled_objs: list[Path] = []

    for src_name in _COREMARK_SOURCES:
        obj = build_dir / src_name.replace(".c", ".o")
        subprocess.run(
            [*common_cflags, "-c", str(coremark_src / src_name), "-o", str(obj)],
            check=True,
            capture_output=True,
        )
        compiled_objs.append(obj)

    for src in [PORTME_DIR / "core_portme.c", PORTME_DIR / "crt0_hdl.c"]:
        obj = build_dir / (src.stem + ".o")
        subprocess.run(
            [*common_cflags, "-c", str(src), "-o", str(obj)],
            check=True,
            capture_output=True,
        )
        compiled_objs.append(obj)

    elf = build_dir / "coremark.elf"
    subprocess.run(
        [
            str(LD),
            *[str(obj) for obj in compiled_objs],
            str(builtins_lib),
            "-o", str(elf),
            "-T", str(PORTME_DIR / "linker_hdl.ld"),
        ],
        check=True,
        capture_output=True,
    )
    return elf


# ---------------------------------------------------------------------------
# Case runners
# ---------------------------------------------------------------------------

def _run_asm_case(
    variant: str,
    case: AsmCase,
    *,
    cache_topology: str,
    max_cycle_cap: int,
) -> dict:
    config = Little64CoreConfig(core_variant=variant, cache_topology=cache_topology, reset_vector=0)
    budget = case.max_cycles

    while True:
        observed = run_program_source(case.source, config=config, max_cycles=budget)
        if observed["locked_up"]:
            raise RuntimeError(f"{variant}:{case.name} locked up")
        if observed["halted"]:
            break
        if budget >= max_cycle_cap:
            raise RuntimeError(
                f"{variant}:{case.name} did not halt within max_cycles={budget}"
            )
        budget = min(max_cycle_cap, budget * 2)

    cycles = int(observed["executed_cycles"])
    commits = int(observed["commit_count"])
    return {
        "variant": variant,
        "case": case.name,
        "cycles": cycles,
        "commits": commits,
        "ipc": (commits / cycles) if cycles else 0.0,
        "extra": {},
    }


def _run_elf_case(
    variant: str,
    case: ElfCase,
    *,
    cache_topology: str,
) -> dict:
    elf_bytes = case.elf_path.read_bytes()
    config = Little64CoreConfig(core_variant=variant, cache_topology=cache_topology, reset_vector=0)
    budget = case.max_cycles

    while True:
        observed = run_elf_flat(elf_bytes, config=config, max_cycles=budget)
        if observed["locked_up"]:
            raise RuntimeError(f"{variant}:{case.name} locked up")
        if observed["halted"]:
            break
        if budget >= case.cycle_cap:
            raise RuntimeError(
                f"{variant}:{case.name} did not halt within max_cycles={budget}"
            )
        budget = min(case.cycle_cap, budget * 2)

    cycles = int(observed["executed_cycles"])
    commits = int(observed["commit_count"])
    cm_per_mhz = (case.iterations * 1_000_000 / cycles) if cycles else 0.0
    return {
        "variant": variant,
        "case": case.name,
        "cycles": cycles,
        "commits": commits,
        "ipc": (commits / cycles) if cycles else 0.0,
        "extra": {"cm_per_mhz": cm_per_mhz},
    }


# ---------------------------------------------------------------------------
# Suite runner
# ---------------------------------------------------------------------------

def run_suite(
    variants: list[str],
    asm_cases: list[AsmCase],
    elf_cases: list[ElfCase],
    repeats: int,
    *,
    cache_topology: str,
    max_cycle_cap: int,
) -> dict:
    all_cases: list[AsmCase | ElfCase] = [*asm_cases, *elf_cases]

    raw: dict[str, dict[str, list[dict]]] = {
        v: {c.name: [] for c in all_cases} for v in variants
    }

    for variant in variants:
        for case in all_cases:
            for _ in range(repeats):
                if isinstance(case, AsmCase):
                    result = _run_asm_case(
                        variant,
                        case,
                        cache_topology=cache_topology,
                        max_cycle_cap=max_cycle_cap,
                    )
                else:
                    result = _run_elf_case(variant, case, cache_topology=cache_topology)
                raw[variant][case.name].append(result)

    summary: dict[str, dict[str, dict]] = {v: {} for v in variants}
    for variant in variants:
        for case in all_cases:
            samples = raw[variant][case.name]
            cycles_s = sorted(int(s["cycles"]) for s in samples)
            commits_s = sorted(int(s["commits"]) for s in samples)
            ipcs_s = sorted(float(s["ipc"]) for s in samples)
            n = len(samples)
            entry: dict = {
                "cycles_median": float(cycles_s[n // 2]),
                "commits_median": float(commits_s[n // 2]),
                "ipc_median": float(ipcs_s[n // 2]),
            }
            if "cm_per_mhz" in (samples[0].get("extra") or {}):
                cm_s = sorted(float(s["extra"]["cm_per_mhz"]) for s in samples)
                entry["cm_per_mhz_median"] = cm_s[n // 2]
            summary[variant][case.name] = entry

    speedups: dict[str, dict[str, float]] = {}
    geomean_speedup: dict[str, float] = {}
    if len(variants) >= 2:
        baseline = variants[0]
        for variant in variants[1:]:
            per_case: dict[str, float] = {}
            for case in all_cases:
                base_c = summary[baseline][case.name]["cycles_median"]
                tgt_c = summary[variant][case.name]["cycles_median"]
                per_case[case.name] = (base_c / tgt_c) if tgt_c else math.inf
            speedups[variant] = per_case
            geomean_speedup[variant] = geometric_mean(list(per_case.values()))

    return {
        "variants": variants,
        "cache_topology": cache_topology,
        "cases": [c.name for c in all_cases],
        "repeats": repeats,
        "max_cycle_cap": max_cycle_cap,
        "summary": summary,
        "speedups_vs_first_variant": speedups,
        "aggregate_geomean_speedup": geomean_speedup,
    }


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

_COL_CASE = 26
_COL_VAR = 12


def _row(label: str, values: list[str]) -> str:
    return f"  {label:{_COL_CASE}}" + "".join(f"{v:{_COL_VAR}}" for v in values)


def print_report(report: dict) -> None:
    variants = report["variants"]
    baseline = variants[0]
    cases = report["cases"]
    summary = report["summary"]
    speedups = report["speedups_vs_first_variant"]
    geomean = report["aggregate_geomean_speedup"]
    non_baseline = variants[1:]

    sep = "─" * (_COL_CASE + 2 + _COL_VAR * len(variants))

    print("Little-64 HDL Performance Benchmark")
    print(f"  variants : {', '.join(variants)}")
    print(f"  cache    : {report['cache_topology']}")
    print(f"  repeats  : {report['repeats']}")
    print()

    # Cycles
    print("Cycles (lower is better):")
    print(_row("case", variants))
    print(_row("─" * _COL_CASE, ["─" * (_COL_VAR - 1)] * len(variants)))
    for case in cases:
        vals = [f"{summary[v][case]['cycles_median']:.0f}" for v in variants]
        print(_row(case, vals))
    print()

    # IPC
    print("IPC — commits/cycle (higher is better):")
    print(_row("case", variants))
    print(_row("─" * _COL_CASE, ["─" * (_COL_VAR - 1)] * len(variants)))
    for case in cases:
        vals = [f"{summary[v][case]['ipc_median']:.3f}" for v in variants]
        print(_row(case, vals))
    print()

    # CoreMark/MHz (only for ELF cases)
    cm_cases = [
        c for c in cases
        if any("cm_per_mhz_median" in summary[v].get(c, {}) for v in variants)
    ]
    if cm_cases:
        print("CoreMark/MHz (higher is better):")
        print(_row("case", variants))
        print(_row("─" * _COL_CASE, ["─" * (_COL_VAR - 1)] * len(variants)))
        for case in cm_cases:
            vals = [
                f"{summary[v][case].get('cm_per_mhz_median', 0.0):.3f}"
                for v in variants
            ]
            print(_row(case, vals))
        print()

    # Speedup vs baseline
    if non_baseline:
        print(f"Speedup vs {baseline} (first variant, higher is better):")
        print(_row("case", non_baseline))
        print(_row("─" * _COL_CASE, ["─" * (_COL_VAR - 1)] * len(non_baseline)))
        for case in cases:
            vals = [
                f"{speedups.get(v, {}).get(case, 1.0):.3f}x"
                for v in non_baseline
            ]
            print(_row(case, vals))
        print()
        print("  geomean speedup vs baseline:")
        for v in non_baseline:
            print(f"    {v}: {geomean.get(v, 1.0):.3f}x")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic HDL performance benchmark for Little-64 core variants.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""\
Examples:
  %(prog)s
  %(prog)s --variants all
    %(prog)s --variants v3 --cache-topology split
  %(prog)s --variants v3
  %(prog)s --variants v2,v3 --coremark-src ~/coremark --repeats 3

Supported variants: {', '.join(SUPPORTED_CORE_VARIANTS)}
""",
    )
    parser.add_argument(
        "--variants",
        default="v2,v3",
        metavar="LIST",
        help=(
            f"Comma-separated variant list, or \"all\" for "
            f"{{{', '.join(SUPPORTED_CORE_VARIANTS)}}}. "
            "First entry is the baseline for speedup comparisons. (default: v2,v3)"
        ),
    )
    parser.add_argument(
        "--cache-topology",
        default="none",
        metavar="TOPOLOGY|all",
        help=(
            "Core cache topology to benchmark (none|unified|split), or 'all'. "
            "Applies to all selected variants. (default: none)."
        ),
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        metavar="N",
        help="Repetitions per case per variant (default: 5).",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write the full report as JSON to this path.",
    )
    parser.add_argument(
        "--max-cycle-cap",
        type=int,
        default=65536,
        metavar="N",
        help="Maximum cycle budget for assembly cases when auto-expanding (default: 65536).",
    )
    parser.add_argument(
        "--coremark-src",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Path to the CoreMark source directory (must contain core_main.c etc.). "
            "When provided, a CoreMark ELF case is compiled and added to the suite."
        ),
    )
    parser.add_argument(
        "--coremark-iterations",
        type=int,
        default=1,
        metavar="N",
        help="CoreMark iteration count baked into the compiled ELF (default: 1).",
    )
    parser.add_argument(
        "--coremark-cycle-cap",
        type=int,
        default=5_000_000,
        metavar="N",
        help=(
            "Hard cycle-budget cap for each CoreMark run (default: 5000000). "
            "Increase if the benchmark does not halt within this budget."
        ),
    )
    parser.add_argument(
        "--coremark-total-data-size",
        type=int,
        default=128,
        metavar="N",
        help=(
            "Compile-time TOTAL_DATA_SIZE for CoreMark (default: 128). "
            "Lower values run faster in HDL simulation."
        ),
    )

    args = parser.parse_args()

    # Resolve variant list
    if args.variants.strip().lower() == "all":
        variants = list(SUPPORTED_CORE_VARIANTS)
    else:
        variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    if not variants:
        raise SystemExit("--variants must not be empty")
    for v in variants:
        if v not in SUPPORTED_CORE_VARIANTS:
            raise SystemExit(
                f"Unknown variant {v!r}; supported: {', '.join(SUPPORTED_CORE_VARIANTS)}"
            )
    cache_arg = args.cache_topology.strip().lower()
    if cache_arg == "all":
        cache_topologies = list(CACHE_TOPOLOGIES)
    elif cache_arg in CACHE_TOPOLOGIES:
        cache_topologies = [cache_arg]
    else:
        raise SystemExit(
            f"Unknown --cache-topology {args.cache_topology!r}; supported: {', '.join(CACHE_TOPOLOGIES)} or all"
        )

    if any(v == "basic" for v in variants) and any(t != "none" for t in cache_topologies):
        raise SystemExit(
            "basic core only supports --cache-topology none; choose --cache-topology none or exclude basic"
        )
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")
    if args.max_cycle_cap < 1:
        raise SystemExit("--max-cycle-cap must be >= 1")

    asm_cases = _default_asm_cases()
    elf_cases: list[ElfCase] = []

    if args.coremark_src is not None:
        coremark_src = args.coremark_src.resolve()
        if not coremark_src.is_dir():
            raise SystemExit(f"CoreMark source directory not found: {coremark_src}")

        build_dir = REPO_ROOT / "builddir" / "coremark_hdl"
        print(
            f"Compiling CoreMark ({args.coremark_iterations} iteration(s), -O2) ...",
            flush=True,
        )
        try:
            elf_path = compile_coremark(
                coremark_src,
                iterations=args.coremark_iterations,
                total_data_size=args.coremark_total_data_size,
                opt="2",
                build_dir=build_dir,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace")
            raise SystemExit(f"CoreMark compilation failed:\n{stderr}") from exc

        print(f"CoreMark ELF: {elf_path}", flush=True)
        elf_cases.append(
            ElfCase(
                name=f"coremark_{args.coremark_iterations}iter",
                elf_path=elf_path,
                iterations=args.coremark_iterations,
                max_cycles=100_000,
                cycle_cap=args.coremark_cycle_cap,
            )
        )

    reports_by_cache: dict[str, dict[str, Any]] = {}
    for idx, cache_topology in enumerate(cache_topologies):
        if len(cache_topologies) > 1:
            if idx:
                print()
            print(f"=== cache-topology: {cache_topology} ===")

        report = run_suite(
            variants=variants,
            asm_cases=asm_cases,
            elf_cases=elf_cases,
            repeats=args.repeats,
            cache_topology=cache_topology,
            max_cycle_cap=args.max_cycle_cap,
        )
        print_report(report)
        reports_by_cache[cache_topology] = report

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        if len(cache_topologies) == 1:
            json_payload: dict[str, Any] = reports_by_cache[cache_topologies[0]]
        else:
            json_payload = {
                "cache_topology_mode": "all",
                "cache_topologies": cache_topologies,
                "reports_by_cache_topology": reports_by_cache,
            }
        args.json_out.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")
        print(f"Wrote JSON report: {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
