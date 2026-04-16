#!/usr/bin/env python3
import argparse
import errno
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, TextIO


WARNING_PATTERNS = (
    "WARNING:",
    "BUG:",
    "refcount_t:",
    "kernfs:",
    "sysfs",
    "scheduling while atomic",
    "max cycle limit",
    "Error: execution reached max cycle limit",
    "panic",
    "Oops",
    "---[ end trace",
)

HEX_WORD_RE = re.compile(r"0x[0-9a-fA-F]+")
BARE_HEX_RE = re.compile(r"(?<![0-9A-Za-z])([0-9a-fA-F]{12,})(?![0-9A-Za-z])")
DECIMAL_RE = re.compile(r"(?<![0-9A-Za-z])\d{4,}(?![0-9A-Za-z])")
BUILD_NUM_RE = re.compile(r"#\d+")
SPACES_RE = re.compile(r"\s+")


@dataclass
class RunResult:
    index: int
    cpu_id: int
    returncode: int
    stdout_path: Path
    stderr_path: Path
    stdout_signature: str
    outcome_signature: str
    markers: list[str]


@dataclass
class ActiveRun:
    index: int
    cpu_id: int
    stdout_path: Path
    stderr_path: Path
    meta_path: Path
    stdout_handle: TextIO
    stderr_handle: TextIO
    process: subprocess.Popen[str]


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Run Little64 fast direct-boot multiple times and cluster recurring outcomes."
    )
    parser.add_argument("--runs", type=int, default=20, help="Number of boot attempts to run (default: 20)")
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=300_000_000,
        help="Cycle limit passed to the boot script (default: 300000000)",
    )
    parser.add_argument(
        "--boot-script",
        default=str(script_dir / "boot_direct.sh"),
        help="Boot helper to invoke (default: target/linux_port/boot_direct.sh)",
    )
    parser.add_argument(
        "--boot-mode",
        default="smoke",
        choices=("trace", "smoke", "rsp"),
        help="Mode passed to the boot helper when it supports --mode (default: smoke)",
    )
    parser.add_argument(
        "--kernel",
        default=None,
        help="Optional kernel ELF path passed as the final positional argument",
    )
    parser.add_argument(
        "--rootfs",
        default=None,
        help="Optional rootfs image path passed via --rootfs",
    )
    parser.add_argument(
        "--no-rootfs",
        action="store_true",
        help="Pass --no-rootfs to the boot script",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to store per-run logs and summaries (default: /tmp/little64-fastboot-samples/<timestamp>)",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue sampling even if a run exits non-zero",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="Concurrent emulator workers. 0 uses one worker per available CPU in the current affinity set.",
    )
    parser.add_argument(
        "--cpu-list",
        default=None,
        help="Comma-separated CPU list/ranges to pin workers to, for example 0,2,4-7",
    )
    return parser.parse_args()


def parse_cpu_list(spec: str) -> list[int]:
    cpus: set[int] = set()
    for part in spec.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start = int(start_text, 10)
            end = int(end_text, 10)
            if end < start:
                raise ValueError(f"invalid CPU range: {item}")
            cpus.update(range(start, end + 1))
        else:
            cpus.add(int(item, 10))
    if not cpus:
        raise ValueError("CPU list is empty")
    return sorted(cpus)


def get_available_cpus() -> list[int]:
    if hasattr(os, "sched_getaffinity"):
        return sorted(os.sched_getaffinity(0))
    cpu_count = os.cpu_count() or 1
    return list(range(cpu_count))


def resolve_worker_cpus(args: argparse.Namespace) -> tuple[list[int], list[int]]:
    available_cpus = get_available_cpus()
    if args.cpu_list:
        requested_cpus = parse_cpu_list(args.cpu_list)
        unavailable = [cpu for cpu in requested_cpus if cpu not in available_cpus]
        if unavailable:
            raise ValueError(
                f"requested CPUs are outside the current affinity set: {','.join(str(cpu) for cpu in unavailable)}"
            )
    else:
        requested_cpus = available_cpus

    jobs = args.jobs if args.jobs > 0 else len(requested_cpus)
    if jobs <= 0:
        raise ValueError("resolved worker count is zero")
    if jobs > len(requested_cpus):
        raise ValueError(
            f"--jobs={jobs} requires at least {jobs} CPUs, but only {len(requested_cpus)} are available"
        )

    return available_cpus, requested_cpus[:jobs]


def normalize_text(text: str) -> str:
    normalized_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = BUILD_NUM_RE.sub("#<num>", line)
        line = HEX_WORD_RE.sub("0x<hex>", line)
        line = BARE_HEX_RE.sub("<hex>", line)
        line = DECIMAL_RE.sub("<num>", line)
        line = SPACES_RE.sub(" ", line)
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


def extract_markers(stdout_text: str, stderr_text: str) -> list[str]:
    markers: list[str] = []
    for source_name, text in (("stdout", stdout_text), ("stderr", stderr_text)):
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if any(pattern in stripped for pattern in WARNING_PATTERNS):
                markers.append(f"{source_name}: {stripped}")
    return markers


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_command(args: argparse.Namespace) -> list[str]:
    command = [args.boot_script, f"--mode={args.boot_mode}", "--max-cycles", str(args.max_cycles)]
    if args.no_rootfs:
        command.append("--no-rootfs")
    elif args.rootfs:
        command.extend(["--rootfs", args.rootfs])
    if args.kernel:
        command.append(args.kernel)
    return command


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def make_output_dir(base: str | None) -> Path:
    if base:
        output_dir = Path(base).expanduser().resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = Path("/tmp/little64-fastboot-samples") / timestamp
    ensure_dir(output_dir)
    return output_dir


def make_run_paths(index: int, output_dir: Path) -> tuple[Path, Path, Path]:
    run_dir = output_dir / f"run_{index:03d}"
    ensure_dir(run_dir)
    return run_dir / "stdout.log", run_dir / "stderr.log", run_dir / "meta.json"


def pin_to_cpu(cpu_id: int) -> None:
    if not hasattr(os, "sched_setaffinity"):
        return
    try:
        os.sched_setaffinity(0, {cpu_id})
    except OSError as exc:
        if exc.errno == errno.EINVAL:
            raise RuntimeError(f"failed to pin child process to CPU {cpu_id}") from exc
        raise


def start_run(index: int, cpu_id: int, command: list[str], output_dir: Path, repo_root: Path) -> ActiveRun:
    stdout_path, stderr_path, meta_path = make_run_paths(index, output_dir)
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=repo_root,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
        errors="replace",
        preexec_fn=lambda: pin_to_cpu(cpu_id),
    )
    return ActiveRun(
        index=index,
        cpu_id=cpu_id,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        meta_path=meta_path,
        stdout_handle=stdout_handle,
        stderr_handle=stderr_handle,
        process=process,
    )


def finalize_run(active_run: ActiveRun, command: list[str]) -> RunResult:
    active_run.stdout_handle.close()
    active_run.stderr_handle.close()

    stdout_text = active_run.stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr_text = active_run.stderr_path.read_text(encoding="utf-8", errors="replace")
    stdout_normalized = normalize_text(stdout_text)
    markers = extract_markers(stdout_text, stderr_text)
    marker_text = normalize_text("\n".join(markers))
    outcome_material = "\n---stdout---\n" + stdout_normalized + "\n---markers---\n" + marker_text

    meta = {
        "index": active_run.index,
        "cpu_id": active_run.cpu_id,
        "returncode": active_run.process.returncode,
        "command": command,
        "stdout_signature": hash_text(stdout_normalized),
        "outcome_signature": hash_text(outcome_material),
        "marker_count": len(markers),
    }
    write_text(active_run.meta_path, json.dumps(meta, indent=2, sort_keys=True) + "\n")

    return RunResult(
        index=active_run.index,
        cpu_id=active_run.cpu_id,
        returncode=active_run.process.returncode,
        stdout_path=active_run.stdout_path,
        stderr_path=active_run.stderr_path,
        stdout_signature=meta["stdout_signature"],
        outcome_signature=meta["outcome_signature"],
        markers=markers,
    )


def run_once(index: int, cpu_id: int, command: list[str], output_dir: Path, repo_root: Path) -> RunResult:
    active_run = start_run(index, cpu_id, command, output_dir, repo_root)
    active_run.process.wait()
    return finalize_run(active_run, command)


def run_parallel(
    args: argparse.Namespace,
    command: list[str],
    output_dir: Path,
    worker_cpus: list[int],
    repo_root: Path,
) -> tuple[list[RunResult], bool]:
    results_by_index: dict[int, RunResult] = {}
    active_runs: dict[int, ActiveRun] = {}
    available_worker_cpus = list(worker_cpus)
    next_index = 1
    stop_queueing = False
    terminate_deadline: float | None = None

    while next_index <= args.runs and available_worker_cpus and not stop_queueing:
        cpu_id = available_worker_cpus.pop(0)
        print(f"[{next_index}/{args.runs}] running {' '.join(command)} on cpu {cpu_id}", flush=True)
        active_runs[next_index] = start_run(next_index, cpu_id, command, output_dir, repo_root)
        next_index += 1

    while active_runs:
        completed_indexes: list[int] = []
        for index, active_run in sorted(active_runs.items()):
            if active_run.process.poll() is None:
                continue

            result = finalize_run(active_run, command)
            results_by_index[index] = result
            available_worker_cpus.append(active_run.cpu_id)
            completed_indexes.append(index)
            print(
                f"[{index}/{args.runs}] rc={result.returncode} cpu={result.cpu_id} stdout_sig={result.stdout_signature} outcome_sig={result.outcome_signature} markers={len(result.markers)}",
                flush=True,
            )

            if result.returncode != 0 and not args.keep_going and not stop_queueing:
                stop_queueing = True
                terminate_deadline = time.monotonic() + 2.0
                for other_index, other_run in active_runs.items():
                    if other_index != index and other_run.process.poll() is None:
                        other_run.process.terminate()

        for index in completed_indexes:
            del active_runs[index]

        available_worker_cpus.sort()
        while next_index <= args.runs and available_worker_cpus and not stop_queueing:
            cpu_id = available_worker_cpus.pop(0)
            print(f"[{next_index}/{args.runs}] running {' '.join(command)} on cpu {cpu_id}", flush=True)
            active_runs[next_index] = start_run(next_index, cpu_id, command, output_dir, repo_root)
            next_index += 1

        if active_runs:
            if stop_queueing and terminate_deadline is not None and time.monotonic() >= terminate_deadline:
                for active_run in active_runs.values():
                    if active_run.process.poll() is None:
                        active_run.process.kill()
                terminate_deadline = None
            time.sleep(0.05)

    results = [results_by_index[index] for index in sorted(results_by_index)]
    return results, stop_queueing


def summarize_clusters(results: Iterable[RunResult], key: str) -> list[tuple[str, list[RunResult]]]:
    groups: dict[str, list[RunResult]] = defaultdict(list)
    for result in results:
        groups[getattr(result, key)].append(result)
    return sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))


def write_summary(output_dir: Path, command: list[str], results: list[RunResult]) -> None:
    summary_path = output_dir / "summary.txt"
    stdout_clusters = summarize_clusters(results, "stdout_signature")
    outcome_clusters = summarize_clusters(results, "outcome_signature")
    returncodes = Counter(result.returncode for result in results)

    lines: list[str] = []
    lines.append("Little64 Fast-Boot Sampling Summary")
    lines.append("")
    lines.append(f"Output directory: {output_dir}")
    lines.append(f"Command: {' '.join(command)}")
    lines.append(f"Runs: {len(results)}")
    lines.append("")
    lines.append("Return codes:")
    for returncode, count in sorted(returncodes.items()):
        lines.append(f"  {returncode}: {count}")
    lines.append("")
    lines.append("Outcome clusters (stdout + warning/BUG markers):")
    for signature, cluster_results in outcome_clusters:
        lines.append(f"  {len(cluster_results):2d}x  {signature}  runs={','.join(f'{r.index:03d}' for r in cluster_results)}")
        first = cluster_results[0]
        if first.markers:
            for marker in first.markers[:6]:
                lines.append(f"      {marker}")
            if len(first.markers) > 6:
                lines.append(f"      ... {len(first.markers) - 6} more marker lines")
        else:
            lines.append("      no warning/BUG markers captured")
    lines.append("")
    lines.append("Stdout-only clusters:")
    for signature, cluster_results in stdout_clusters:
        lines.append(f"  {len(cluster_results):2d}x  {signature}  runs={','.join(f'{r.index:03d}' for r in cluster_results)}")
    lines.append("")
    lines.append("Per-run logs:")
    for result in results:
        lines.append(
            f"  run_{result.index:03d}: cpu={result.cpu_id} rc={result.returncode} stdout={result.stdout_path} stderr={result.stderr_path}"
        )

    write_text(summary_path, "\n".join(lines) + "\n")


def print_console_summary(output_dir: Path, results: list[RunResult]) -> None:
    stdout_clusters = summarize_clusters(results, "stdout_signature")
    outcome_clusters = summarize_clusters(results, "outcome_signature")
    print(f"saved run artifacts under {output_dir}")
    print("outcome clusters:")
    for signature, cluster_results in outcome_clusters:
        marker_preview = cluster_results[0].markers[0] if cluster_results[0].markers else "no markers"
        print(
            f"  {len(cluster_results):2d}x {signature} runs={','.join(f'{r.index:03d}' for r in cluster_results)} | {marker_preview}"
        )
    print("stdout-only clusters:")
    for signature, cluster_results in stdout_clusters:
        print(f"  {len(cluster_results):2d}x {signature} runs={','.join(f'{r.index:03d}' for r in cluster_results)}")
    print(f"full summary: {output_dir / 'summary.txt'}")


def main() -> int:
    args = parse_args()
    if args.runs <= 0:
        print("error: --runs must be positive", file=sys.stderr)
        return 2
    if args.jobs < 0:
        print("error: --jobs must be zero or positive", file=sys.stderr)
        return 2

    boot_script = Path(args.boot_script).expanduser().resolve()
    if not boot_script.is_file():
        print(f"error: boot script not found: {boot_script}", file=sys.stderr)
        return 2
    if not os.access(boot_script, os.X_OK):
        print(f"error: boot script is not executable: {boot_script}", file=sys.stderr)
        return 2

    args.boot_script = str(boot_script)
    output_dir = make_output_dir(args.output_dir)
    command = build_command(args)
    repo_root = Path(__file__).resolve().parents[2]

    try:
        available_cpus, worker_cpus = resolve_worker_cpus(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    metadata = {
        "created_at": datetime.now().isoformat(),
        "command": command,
        "runs": args.runs,
        "max_cycles": args.max_cycles,
        "available_cpus": available_cpus,
        "worker_cpus": worker_cpus,
        "jobs": len(worker_cpus),
    }
    write_text(output_dir / "session.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")

    print(
        f"using {len(worker_cpus)} worker(s) pinned to CPUs: {','.join(str(cpu) for cpu in worker_cpus)}",
        flush=True,
    )

    if len(worker_cpus) == 1:
        results: list[RunResult] = []
        for index in range(1, args.runs + 1):
            print(f"[{index}/{args.runs}] running {' '.join(command)} on cpu {worker_cpus[0]}", flush=True)
            result = run_once(index, worker_cpus[0], command, output_dir, repo_root)
            results.append(result)
            print(
                f"[{index}/{args.runs}] rc={result.returncode} cpu={result.cpu_id} stdout_sig={result.stdout_signature} outcome_sig={result.outcome_signature} markers={len(result.markers)}",
                flush=True,
            )
            if result.returncode != 0 and not args.keep_going:
                print("stopping after non-zero exit; rerun with --keep-going to continue", file=sys.stderr)
                break
    else:
        results, stopped_early = run_parallel(args, command, output_dir, worker_cpus, repo_root)
        if stopped_early:
            print(
                "stopping after non-zero exit; in-flight runs were terminated because --keep-going was not set",
                file=sys.stderr,
            )

    write_summary(output_dir, command, results)
    print_console_summary(output_dir, results)
    return 0


if __name__ == "__main__":
    sys.exit(main())