from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def _load_smoke_wrapper_module():
    module_path = Path(__file__).resolve().parents[1] / 'tools' / 'run_litex_linux_boot_smoke.py'
    spec = importlib.util.spec_from_file_location('little64_run_litex_linux_boot_smoke', module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_required_markers_use_linux_version_banner() -> None:
    smoke_wrapper = _load_smoke_wrapper_module()

    assert smoke_wrapper.DEFAULT_REQUIRED_MARKERS == [smoke_wrapper.LINUX_VERSION_MARKER]
    assert smoke_wrapper.DEFAULT_SD_REQUIRED_MARKERS == [smoke_wrapper.LINUX_VERSION_MARKER]


def test_resolved_output_dir_uses_sdcard_specific_build_dir() -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    args = argparse.Namespace(with_sdcard=True, output_dir=smoke_wrapper.DEFAULT_OUTPUT_DIR)

    assert smoke_wrapper._resolved_output_dir(args) == smoke_wrapper.DEFAULT_SD_OUTPUT_DIR


def test_resolve_required_markers_uses_linux_banner_by_default() -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    args = argparse.Namespace(with_sdcard=True, require=[], extra_require=[])

    assert smoke_wrapper._resolve_required_markers(args) == [smoke_wrapper.LINUX_VERSION_MARKER]


def test_resolve_required_markers_appends_extra_requirements_without_duplicates() -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    args = argparse.Namespace(
        with_sdcard=False,
        require=[],
        extra_require=[smoke_wrapper.LINUX_VERSION_MARKER, 'little64-timer: clocksource + clockevent @ 1 GHz'],
    )

    assert smoke_wrapper._resolve_required_markers(args) == [
        smoke_wrapper.LINUX_VERSION_MARKER,
        'little64-timer: clocksource + clockevent @ 1 GHz',
    ]


def test_resolve_required_markers_allows_exact_override() -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    args = argparse.Namespace(with_sdcard=False, require=['stage0: handing off to kernel'], extra_require=[])

    assert smoke_wrapper._resolve_required_markers(args) == ['stage0: handing off to kernel']