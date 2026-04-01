#!/usr/bin/env python3
import os
import subprocess
import re
import sys
import glob

# Paths
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
BIN_DIR = os.path.join(ROOT_DIR, "compilers/bin")
EMU_PATH = os.path.join(ROOT_DIR, "builddir/little-64")
TEST_DIR = os.path.join(ROOT_DIR, "tests/llvm")
TMP_DIR = os.path.join(ROOT_DIR, "tests/llvm/tmp")

# Toolchain
CLANG = os.path.join(BIN_DIR, "clang")
LLVM_MC = os.path.join(BIN_DIR, "llvm-mc")
LD_LLD = os.path.join(BIN_DIR, "ld.lld")

os.makedirs(TMP_DIR, exist_ok=True)

class TestResult:
    def __init__(self, name, success, message=""):
        self.name = name
        self.success = success
        self.message = message

def run_cmd(cmd, check=False):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        return res
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))

def parse_metadata(file_path):
    metadata = {
        "should_fail": False,
        "expected_error": None,
        "expected_regs": {},
        "expected_stdout": [],
        "skip": False
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
                
            if "SKIP" in line:
                metadata["skip"] = True
    return metadata

def test_file(file_path):
    rel_path = os.path.relpath(file_path, TEST_DIR)
    meta = parse_metadata(file_path)
    if meta["skip"]:
        return TestResult(rel_path, True, "Skipped")

    base = os.path.basename(file_path).split('.')[0]
    obj = os.path.join(TMP_DIR, f"{base}.o")
    elf = os.path.join(TMP_DIR, f"{base}.elf")
    is_asm = file_path.endswith('.asm')

    # 1. Assemble / Compile
    if is_asm:
        res = run_cmd(f"{LLVM_MC} -triple=little64 -filetype=obj {file_path} -o {obj}")
    else:
        res = run_cmd(f"{CLANG} -target little64 -O1 -c {file_path} -o {obj}")

    if res.returncode != 0:
        if meta["should_fail"] and (not meta["expected_error"] or meta["expected_error"] in res.stderr + res.stdout):
            return TestResult(rel_path, True, "Failed as expected (compilation)")
        return TestResult(rel_path, False, f"Compilation failed:\n{res.stderr}\n{res.stdout}")

    # 2. Link
    res = run_cmd(f"{LD_LLD} {obj} -o {elf}")
    if res.returncode != 0:
        if meta["should_fail"] and (not meta["expected_error"] or meta["expected_error"] in res.stderr + res.stdout):
            return TestResult(rel_path, True, "Failed as expected (linking)")
        return TestResult(rel_path, False, f"Linking failed:\n{res.stderr}\n{res.stdout}")

    if meta["should_fail"]:
        return TestResult(rel_path, False, "Test was expected to fail but succeeded")

    # 3. Run
    try:
        res = subprocess.run(f"{EMU_PATH} {elf}", capture_output=True, text=True, shell=True, timeout=5)
    except subprocess.TimeoutExpired:
        return TestResult(rel_path, False, "Test execution timed out (5s)")

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

def main():
    test_files = (glob.glob(os.path.join(TEST_DIR, "**/*.asm"), recursive=True) + 
                  glob.glob(os.path.join(TEST_DIR, "**/*.c"), recursive=True))
    
    results = []
    for f in sorted(test_files):
        print(f"Running {os.path.relpath(f, TEST_DIR)}...", end="", flush=True)
        res = test_file(f)
        results.append(res)
        if res.success:
            print(" \033[92mPASS\033[0m" + (f" ({res.message})" if res.message else ""))
        else:
            print(" \033[91mFAIL\033[0m")
            print(f"  {res.message}")

    passed = sum(1 for r in results if r.success)
    total = len(results)
    print(f"\nSummary: {passed}/{total} tests passed")
    if passed < total:
        sys.exit(1)

if __name__ == "__main__":
    main()
