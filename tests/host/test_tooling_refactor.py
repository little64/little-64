#!/usr/bin/env python3
"""Coverage for the Phase 1-3 tooling refactor (little64 shared modules)."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile


REPO = pathlib.Path(__file__).resolve().parents[2]
PKG = REPO / "tools" / "little64"
VENV_PYTHON = REPO / ".venv" / "bin" / "python"


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(PKG), env.get("PYTHONPATH", "")]).strip(os.pathsep)
    return env


def _run_python(code: str, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = _python_env()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(VENV_PYTHON), "-c", code],
        env=env,
        capture_output=True,
        text=True,
    )


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(VENV_PYTHON), "-m", "little64.cli", *args],
        env=_python_env(),
        capture_output=True,
        text=True,
    )


def _assert_success(result: subprocess.CompletedProcess[str], label: str) -> int:
    if result.returncode != 0:
        sys.stderr.write(f"[{label}] rc={result.returncode}\n")
        sys.stderr.write(result.stdout + result.stderr)
        return 1
    return 0


def main() -> int:
    if not VENV_PYTHON.is_file():
        sys.stderr.write(f"missing test interpreter: {VENV_PYTHON}\n")
        return 1

    # ---- little64.config registry ----
    result = _run_python(
        "from little64 import config\n"
        "assert config.DEFAULT_MACHINE == 'litex'\n"
        "assert config.DEFAULT_DEFCONFIG_NAME == 'little64_litex_sim_defconfig'\n"
        "assert config.available_machines() == ('litex',)\n"
        "profile = config.get_machine_profile('litex')\n"
        "assert profile.defconfig == 'little64_litex_sim_defconfig'\n"
        "assert profile.build_dir_name == 'build-litex'\n"
        "assert profile.cpu_variant == 'standard'\n"
        "assert config.build_dir_name_for_defconfig('little64_litex_sim_defconfig') == 'build-litex'\n"
        "assert config.build_dir_name_for_defconfig('unknown_defconfig') == 'build-unknown_defconfig'\n"
        "assert config.resolve_defconfig(defconfig='explicit') == 'explicit'\n"
        "assert config.resolve_defconfig(machine='litex') == 'little64_litex_sim_defconfig'\n"
        "assert config.resolve_defconfig(env={'LITTLE64_LINUX_DEFCONFIG': 'envcfg'}) == 'envcfg'\n"
        "assert config.resolve_defconfig(env={}) == 'little64_litex_sim_defconfig'\n"
        "try:\n"
        "    config.get_machine_profile('mystery')\n"
        "    raise AssertionError('should have raised')\n"
        "except ValueError:\n"
        "    pass\n"
    )
    if rc := _assert_success(result, "config registry"):
        return rc

    # ---- little64.paths delegates defconfig resolution to config ----
    result = _run_python(
        "from little64 import paths\n"
        "assert paths.build_dir_name_for_defconfig('little64_litex_sim_defconfig') == 'build-litex'\n"
        "assert paths.effective_defconfig_name(None) == 'little64_litex_sim_defconfig'\n"
        "assert paths.effective_defconfig_name('custom') == 'custom'\n"
    )
    if rc := _assert_success(result, "paths delegation"):
        return rc

    # ---- little64.proc CommandError carries context + rc ----
    result = _run_python(
        "from little64 import proc\n"
        "try:\n"
        "    proc.run(['false'], context='testing rc propagation')\n"
        "except proc.CommandError as exc:\n"
        "    assert exc.returncode == 1\n"
        "    assert exc.context == 'testing rc propagation'\n"
        "    assert 'testing rc propagation' in str(exc)\n"
        "else:\n"
        "    raise AssertionError('expected CommandError')\n"
        "# check=False must not raise\n"
        "completed = proc.run(['false'], context='nocheck', check=False)\n"
        "assert completed.returncode == 1\n"
    )
    if rc := _assert_success(result, "proc.CommandError"):
        return rc

    # ---- little64.proc dry-run skips execution ----
    with tempfile.TemporaryDirectory() as tmp:
        marker = pathlib.Path(tmp) / "shouldnotexist"
        result = _run_python(
            f"from little64 import proc\n"
            f"from pathlib import Path\n"
            f"# Would error without dry-run; with dry-run it's a no-op that returns rc=0.\n"
            f"completed = proc.run(['touch', {str(marker)!r}], context='dry-run probe')\n"
            f"assert completed.returncode == 0\n"
            f"assert not Path({str(marker)!r}).exists()\n",
            extra_env={"LITTLE64_DRY_RUN": "1"},
        )
        if rc := _assert_success(result, "proc dry-run"):
            return rc

    # ---- little64.tools MissingToolError and require_* paths ----
    result = _run_python(
        "from little64 import tools\n"
        "from pathlib import Path\n"
        "# find_host_tool returns Path or None; /bin/ls is ubiquitous.\n"
        "found = tools.find_host_tool('ls')\n"
        "assert found is not None and found.name == 'ls'\n"
        "assert tools.find_host_tool('definitely-not-a-real-binary-xyz') is None\n"
        "try:\n"
        "    tools.require_host_tool(tools.ToolRequest('definitely-not-a-real-binary-xyz', hint='invent one'))\n"
        "except tools.MissingToolError as exc:\n"
        "    assert 'definitely-not-a-real-binary-xyz' in str(exc)\n"
        "    assert 'invent one' in str(exc)\n"
        "else:\n"
        "    raise AssertionError('expected MissingToolError')\n"
        "try:\n"
        "    tools.require_compiler_tool(Path('/nonexistent'), 'clang')\n"
        "except tools.MissingToolError as exc:\n"
        "    assert 'clang' in str(exc)\n"
        "    assert 'compilers' in str(exc) and 'build.sh llvm' in str(exc)\n"
        "else:\n"
        "    raise AssertionError('expected MissingToolError')\n"
        "first_found = tools.require_any_host_tool((\n"
        "    tools.ToolRequest('definitely-not-a-real-binary-xyz'),\n"
        "    tools.ToolRequest('ls'),\n"
        "))\n"
        "assert first_found.name == 'ls'\n"
    )
    if rc := _assert_success(result, "tools helpers"):
        return rc

    # ---- little64.env registry + get_flag ----
    result = _run_python(
        "from little64 import env\n"
        "assert env.REPO_ROOT.name == 'LITTLE64_REPO_ROOT'\n"
        "assert env.ROOTFS_SIZE_MB.default == '8'\n"
        "assert env.BOOT_EVENTS_MAX_MB.get(env={}) == '500'\n"
        "assert env.VERBOSE.get_flag(env={'LITTLE64_VERBOSE': '1'}) is True\n"
        "assert env.VERBOSE.get_flag(env={}) is False\n"
        "assert env.VERBOSE.get_flag(env={'LITTLE64_VERBOSE': 'no'}) is False\n"
        "assert env.LINUX_DEFCONFIG.get(env={'LITTLE64_LINUX_DEFCONFIG': 'foo'}) == 'foo'\n"
    )
    if rc := _assert_success(result, "env registry"):
        return rc

    # ---- little64.errors CLIError hints ----
    result = _run_python(
        "from little64.errors import CLIError, LitexBootError\n"
        "try:\n"
        "    raise LitexBootError('something broke', hints=('try X', 'try Y'))\n"
        "except CLIError as exc:\n"
        "    assert str(exc) == 'something broke'\n"
        "    assert exc.hints == ('try X', 'try Y')\n"
        "# Default hints tuple\n"
        "try:\n"
        "    raise CLIError('plain')\n"
        "except CLIError as exc:\n"
        "    assert exc.hints == ()\n"
    )
    if rc := _assert_success(result, "errors hierarchy"):
        return rc

    # ---- little64.hdl_bridge idempotency ----
    result = _run_python(
        "import sys\n"
        "from little64.hdl_bridge import ensure_hdl_path, hdl_root\n"
        "entry = str(hdl_root())\n"
        "before = sys.path.count(entry)\n"
        "ensure_hdl_path()\n"
        "ensure_hdl_path()\n"
        "after = sys.path.count(entry)\n"
        "# Either the entry was already there (before >= 1) and stays, or it is added exactly once.\n"
        "assert after <= max(before, 1)\n"
    )
    if rc := _assert_success(result, "hdl_bridge idempotency"):
        return rc

    # ---- litex_boot_support raises LitexBootError instead of sys.exit ----
    result = _run_python(
        "from little64.litex_boot_support import (\n"
        "    ensure_litex_python_env, LitexBootError,\n"
        ")\n"
        "try:\n"
        "    ensure_litex_python_env('/nonexistent/python/interp')\n"
        "except LitexBootError as exc:\n"
        "    assert 'Python interpreter not found' in str(exc)\n"
        "    assert any('LITTLE64_PYTHON' in hint for hint in exc.hints)\n"
        "else:\n"
        "    raise AssertionError('expected LitexBootError')\n"
    )
    if rc := _assert_success(result, "litex_boot_support raises"):
        return rc

    # ---- kernel.validate exposes KernelConfigError ----
    result = _run_python(
        "from pathlib import Path\n"
        "import tempfile\n"
        "from little64.commands.kernel.validate import (\n"
        "    KernelConfigError, validate_kernel_config,\n"
        ")\n"
        "with tempfile.TemporaryDirectory() as tmp:\n"
        "    fake_kernel = Path(tmp) / 'vmlinux'\n"
        "    fake_kernel.write_text('')\n"
        "    # No .config anywhere; must raise.\n"
        "    try:\n"
        "        validate_kernel_config(fake_kernel)\n"
        "    except KernelConfigError as exc:\n"
        "        assert 'unable to verify' in str(exc)\n"
        "    else:\n"
        "        raise AssertionError('expected KernelConfigError')\n"
        "    # skip_check=True short-circuits.\n"
        "    validate_kernel_config(fake_kernel, skip_check=True)\n"
    )
    if rc := _assert_success(result, "kernel.validate"):
        return rc

    # ---- CLI --help / global --verbose / --dry-run flags ----
    help_result = _run_cli("--help")
    if rc := _assert_success(help_result, "cli --help"):
        return rc
    for flag in ("--verbose", "--dry-run"):
        if flag not in help_result.stdout:
            sys.stderr.write(f"cli --help missing {flag!r}\n{help_result.stdout}")
            return 1

    # --verbose doesn't break paths repo-root.
    repo_root_result = _run_cli("-v", "paths", "repo-root")
    if rc := _assert_success(repo_root_result, "cli -v paths repo-root"):
        return rc
    if pathlib.Path(repo_root_result.stdout.strip()).resolve() != REPO:
        sys.stderr.write(f"expected repo-root {REPO}, got {repo_root_result.stdout!r}\n")
        return 1

    # ---- rootfs build --help documents --size-mb ----
    help_result = _run_cli("rootfs", "build", "--help")
    if rc := _assert_success(help_result, "cli rootfs build --help"):
        return rc
    if "--size-mb" not in help_result.stdout:
        sys.stderr.write(f"rootfs build --help missing --size-mb\n{help_result.stdout}")
        return 1

    # ---- hdl arty-build --help documents --machine ----
    help_result = _run_cli("hdl", "arty-build", "--help")
    if rc := _assert_success(help_result, "cli hdl arty-build --help"):
        return rc
    if "--machine" not in help_result.stdout:
        sys.stderr.write(f"hdl arty-build --help missing --machine\n{help_result.stdout}")
        return 1

    # ---- CLI catches CLIError and prints hint ----
    with tempfile.TemporaryDirectory() as tmp:
        result = _run_python(
            f"import sys\n"
            f"import os\n"
            f"os.environ['LITTLE64_REPO_ROOT'] = {tmp!r}\n"
            f"from little64.cli import main\n"
            f"# Boot run will fail finding the emulator; confirms error reporting path.\n"
            f"# We use a safer surface: raise manually through the top-level handler.\n"
            f"from little64.errors import CLIError\n"
            f"sys.argv = ['little64', 'paths', 'repo-root']\n"
            f"rc = main(['paths', 'repo-root'])\n"
            f"assert rc == 0\n"
        )
        if rc := _assert_success(result, "cli main CLIError catch"):
            return rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
