#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = ROOT / "tools" / "little64"


def _load_module():
    if str(PKG_DIR) not in sys.path:
        sys.path.insert(0, str(PKG_DIR))
    import importlib
    return importlib.import_module("little64.commands.kernel.build")


def main() -> int:
    helper = _load_module()

    assert helper.default_defconfig_for_machine("litex") == "little64_litex_sim_defconfig"

    args, extra = helper.parse_args(["--machine", "litex", "-j1"])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.machine == "litex"
    assert request.target == "vmlinux"
    assert request.defconfig_name == "little64_litex_sim_defconfig"
    assert str(request.build_dir).endswith("target/linux_port/build-litex")
    assert request.make_args == ("-j1",)

    args, extra = helper.parse_args([])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.defconfig_name == "little64_litex_sim_defconfig"
    assert str(request.build_dir).endswith("target/linux_port/build-litex")

    args, extra = helper.parse_args(["--machine", "litex", "--defconfig", "custom_defconfig", "vmlinux"])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.defconfig_name == "custom_defconfig"
    assert str(request.build_dir).endswith("target/linux_port/build-custom_defconfig")

    args, extra = helper.parse_args([])
    request = helper.resolve_build_request(args, extra, env={"LITTLE64_LINUX_DEFCONFIG": "env_defconfig"})
    assert request.defconfig_name == "env_defconfig"
    assert request.target == "vmlinux"
    assert request.make_args[0].startswith("-j")

    args, extra = helper.parse_args(["clean"])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.target == "clean"

    args, extra = helper.parse_args(["vmlinux", "KCFLAGS=-O0", "CONFIG_DEBUG_INFO=n"])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.debug_cflag_args == ()
    assert request.debug_kconfig_args == ()
    assert helper.build_targets_for_request(request) == ("vmlinux", "vmlinuz")

    args, extra = helper.parse_args(["clean"])
    request = helper.resolve_build_request(args, extra, env={})
    assert helper.build_targets_for_request(request) == ("clean",)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
