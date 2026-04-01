#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import re
import sys
import glob
import hashlib

# Paths
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
BIN_DIR = os.path.join(ROOT_DIR, "compilers/bin")
EMU_PATH = os.path.join(ROOT_DIR, "builddir/little-64")
DBG_PATH = os.path.join(ROOT_DIR, "builddir/little-64-debug")
TEST_DIR = os.path.join(ROOT_DIR, "tests/llvm")
TMP_DIR = os.path.join(ROOT_DIR, "tests/llvm/tmp")

# Toolchain
CLANG = os.path.join(BIN_DIR, "clang")
LLVM_MC = os.path.join(BIN_DIR, "llvm-mc")
LD_LLD = os.path.join(BIN_DIR, "ld.lld")

os.makedirs(TMP_DIR, exist_ok=True)

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

def colorize(text, color, use_color):
    return f"{color}{text}{RESET}" if use_color else text

class TestResult:
    def __init__(self, name, success, message=""):
        self.name = name
        self.success = success
        self.message = message


def write_json_report(path, results, passed, total):
    if not path:
        return

    report = {
        "summary": {
            "passed": passed,
            "failed": total - passed,
            "total": total,
        },
        "results": [
            {
                "name": r.name,
                "success": r.success,
                "message": r.message,
            }
            for r in results
        ],
    }

    report_dir = os.path.dirname(path)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

def run_cmd(args):
    try:
        res = subprocess.run(args, capture_output=True, text=True)
        return res
    except Exception as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))

def parse_metadata(file_path):
    metadata = {
        "should_fail": False,
        "expected_error": None,
        "expected_regs": {},
        "expected_stdout": [],
        "skip": False,
        "timeout": None,
    }
    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line.startswith(("//", ";", "#")):
                if not line: continue
                break # End of metadata block
            
            # Simple metadata parsing
            if "SHOULD_FAIL" in line:
                metadata["should_fail"] = True
                match = re.search(r"SHOULD_FAIL:\s*(.*)", line)
                if match: metadata["expected_error"] = match.group(1).strip()
            
            match = re.search(r"CHECK_REG:\s*(\w+)\s*=\s*(0x[0-9a-fA-F]+|\d+)", line)
            if match:
                reg = match.group(1).upper()
                val = int(match.group(2), 0)
                metadata["expected_regs"][reg] = val
                
            match = re.search(r"CHECK_STDOUT:\s*(.*)", line)
            if match:
                metadata["expected_stdout"].append(match.group(1).strip())

            match = re.search(r"TIMEOUT:\s*(\d+)", line)
            if match:
                metadata["timeout"] = int(match.group(1))
                
            if "SKIP" in line:
                metadata["skip"] = True
    return metadata

def make_tmp_paths(file_path):
    rel = os.path.relpath(file_path, TEST_DIR)
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]
    stem = os.path.splitext(os.path.basename(file_path))[0]
    base = f"{stem}_{digest}"
    return (os.path.join(TMP_DIR, f"{base}.o"),
            os.path.join(TMP_DIR, f"{base}.elf"))

def read_tail(text, max_lines=25):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-max_lines:])

def probe_timeout_state(elf_path):
    if not os.path.exists(DBG_PATH):
        return ""

    script = f"load {elf_path}\nrun 200000\npc\nregs\nquit\n"
    try:
        res = subprocess.run([DBG_PATH], input=script, capture_output=True, text=True, timeout=15)
    except Exception:
        return ""

    tail = read_tail(res.stdout, max_lines=20)
    if not tail:
        return ""
    return f"\nTimeout probe (little-64-debug):\n{tail}"

def test_file(file_path, default_timeout):
    rel_path = os.path.relpath(file_path, TEST_DIR)
    meta = parse_metadata(file_path)
    if meta["skip"]:
        return TestResult(rel_path, True, "Skipped")

    obj, elf = make_tmp_paths(file_path)
    is_asm = file_path.endswith('.asm')
    timeout = meta["timeout"] if meta["timeout"] is not None else default_timeout

    # 1. Assemble / Compile
    if is_asm:
        res = run_cmd([LLVM_MC, "-triple=little64", "-filetype=obj", file_path, "-o", obj])
    else:
        res = run_cmd([CLANG, "-target", "little64", "-O1", "-c", file_path, "-o", obj])

    if res.returncode != 0:
        if meta["should_fail"] and (not meta["expected_error"] or meta["expected_error"] in res.stderr + res.stdout):
            return TestResult(rel_path, True, "Failed as expected (compilation)")
        return TestResult(rel_path, False, f"Compilation failed:\n{res.stderr}\n{res.stdout}")

    # 2. Link
    res = run_cmd([LD_LLD, obj, "-o", elf])
    if res.returncode != 0:
        if meta["should_fail"] and (not meta["expected_error"] or meta["expected_error"] in res.stderr + res.stdout):
            return TestResult(rel_path, True, "Failed as expected (linking)")
        return TestResult(rel_path, False, f"Linking failed:\n{res.stderr}\n{res.stdout}")

    if meta["should_fail"]:
        return TestResult(rel_path, False, "Test was expected to fail but succeeded")

    # 3. Run
    try:
        res = subprocess.run([EMU_PATH, elf], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        probe = probe_timeout_state(elf)
        return TestResult(rel_path, False, f"Test execution timed out ({timeout}s){probe}")

    # Check Regs
    actual_regs = {}
    for line in res.stderr.splitlines():
        match = re.search(r"\s*(R\d+):\s*(0x[0-9a-fA-F]+)", line)
        if match:
            actual_regs[match.group(1).upper()] = int(match.group(2), 0)
            
    for reg, expected_val in meta["expected_regs"].items():
        if reg not in actual_regs:
            return TestResult(rel_path, False, f"Register {reg} not found in output")
        if actual_regs[reg] != expected_val:
            return TestResult(rel_path, False, f"Register {reg} mismatch: expected {hex(expected_val)}, got {hex(actual_regs[reg])}")

    # Check Stdout
    for expected in meta["expected_stdout"]:
        if expected not in res.stdout:
            return TestResult(rel_path, False, f"Stdout mismatch: expected '{expected}' not found in '{res.stdout}'")

    return TestResult(rel_path, True)

def collect_test_files():
    asm_files = glob.glob(os.path.join(TEST_DIR, "asm", "**", "*.asm"), recursive=True)
    c_files = glob.glob(os.path.join(TEST_DIR, "c", "**", "*.c"), recursive=True)
    return sorted(asm_files + c_files)

def parse_args():
    parser = argparse.ArgumentParser(description="Run Little-64 LLVM integration tests")
    parser.add_argument("--timeout", type=int, default=5,
                        help="Default per-test execution timeout in seconds (default: 5)")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI color output")
    parser.add_argument("--verbose", action="store_true",
                        help="Print PASS details even on success")
    parser.add_argument("--report-json", type=str,
                        help="Write machine-readable JSON report to this path")
    return parser.parse_args()

def main():
    args = parse_args()
    use_color = (not args.no_color) and sys.stdout.isatty()
    test_files = collect_test_files()
    
    results = []
    for f in sorted(test_files):
        print(f"Running {os.path.relpath(f, TEST_DIR)}...", end="", flush=True)
        res = test_file(f, default_timeout=args.timeout)
        results.append(res)
        if res.success:
            suffix = f" ({res.message})" if (res.message and args.verbose) else ""
            print(" " + colorize("PASS", GREEN, use_color) + suffix)
        else:
            print(" " + colorize("FAIL", RED, use_color))
            print(f"  {res.message}")

    passed = sum(1 for r in results if r.success)
    total = len(results)
    write_json_report(args.report_json, results, passed, total)
    print(f"\nSummary: {passed}/{total} tests passed")
    if passed < total:
        sys.exit(1)

if __name__ == "__main__":
    main()
