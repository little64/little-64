#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = ROOT / 'target' / 'linux_port' / 'linux_build.py'


def _load_module():
    sys.path.insert(0, str(HELPER_PATH.parent))
    spec = importlib.util.spec_from_file_location('little64_linux_build', HELPER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    helper = _load_module()

    assert helper.default_defconfig_for_machine('virt') == 'little64_defconfig'
    assert helper.default_defconfig_for_machine('litex') == 'little64_litex_sim_defconfig'

    args, extra = helper.parse_args(['--machine', 'litex', '-j1'])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.machine == 'litex'
    assert request.target == 'vmlinux'
    assert request.defconfig_name == 'little64_litex_sim_defconfig'
    assert str(request.build_dir).endswith('target/linux_port/build-litex')
    assert request.make_args == ('-j1',)

    args, extra = helper.parse_args([])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.defconfig_name == 'little64_litex_sim_defconfig'
    assert str(request.build_dir).endswith('target/linux_port/build-litex')

    args, extra = helper.parse_args(['--machine', 'virt'])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.defconfig_name == 'little64_defconfig'
    assert str(request.build_dir).endswith('target/linux_port/build-virt')

    args, extra = helper.parse_args(['--machine', 'litex', '--defconfig', 'custom_defconfig', 'vmlinux'])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.defconfig_name == 'custom_defconfig'
    assert str(request.build_dir).endswith('target/linux_port/build-custom_defconfig')

    args, extra = helper.parse_args([])
    request = helper.resolve_build_request(args, extra, env={'LITTLE64_LINUX_DEFCONFIG': 'env_defconfig'})
    assert request.defconfig_name == 'env_defconfig'
    assert request.target == 'vmlinux'
    assert request.make_args[0].startswith('-j')

    args, extra = helper.parse_args(['clean'])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.target == 'clean'

    args, extra = helper.parse_args(['vmlinux', 'KCFLAGS=-O0', 'CONFIG_DEBUG_INFO=n'])
    request = helper.resolve_build_request(args, extra, env={})
    assert request.debug_cflag_args == ()
    assert request.debug_kconfig_args == ()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())