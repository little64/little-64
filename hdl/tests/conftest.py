from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

HDL_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(HDL_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from little64_cores.config import DEFAULT_CORE_VARIANT, Little64CoreConfig, SUPPORTED_CORE_VARIANTS

from core_test_contract import adapter_for_variant, variants_with_capabilities


def _default_shared_core_variants() -> list[str]:
	# Keep the current default core first, then include pipelined cores for comparison.
	ordered = [DEFAULT_CORE_VARIANT]
	for candidate in ('v2', 'v3', 'v4'):
		if candidate != DEFAULT_CORE_VARIANT and candidate in SUPPORTED_CORE_VARIANTS:
			ordered.append(candidate)
	return ordered


def _parse_shared_core_variants(raw_value: str) -> list[str]:
	normalized = raw_value.strip().lower()
	if normalized in ('', 'default', 'current'):
		return _default_shared_core_variants()
	if normalized == 'all':
		return list(SUPPORTED_CORE_VARIANTS)
	if normalized in SUPPORTED_CORE_VARIANTS:
		return [normalized]

	variants = [value.strip().lower() for value in raw_value.split(',') if value.strip()]
	if not variants:
		raise pytest.UsageError('`--core-variants` requires at least one variant name')

	unknown = [variant for variant in variants if variant not in SUPPORTED_CORE_VARIANTS]
	if unknown:
		raise pytest.UsageError(
			f'Unsupported core variants in `--core-variants`: {", ".join(unknown)}; expected one of {", ".join(SUPPORTED_CORE_VARIANTS)} or `all`'
		)
	return list(dict.fromkeys(variants))


def _parse_pipelined_core_variants(raw_value: str) -> list[str]:
	"""Parse core variants, excluding 'basic' (for pipelined-core-only tests like MMIO)."""
	variants = _parse_shared_core_variants(raw_value)
	return variants_with_capabilities(variants, {'pipelined'})


def _required_core_capabilities(metafunc: pytest.Metafunc) -> set[str]:
	required: set[str] = set()
	for marker in metafunc.definition.iter_markers('core_capabilities'):
		required.update(str(capability) for capability in marker.args)
	return required


def pytest_addoption(parser: pytest.Parser) -> None:
	default_variants = ','.join(_default_shared_core_variants())
	parser.addoption(
		'--core-variants',
		action='store',
		default='default',
		help=(
			f'Shared HDL test core variants to run: `default` (`{default_variants}`), '
			'`v3`, `v2`, `basic`, comma-separated variants, or `all`.'
		),
	)


def pytest_configure(config: pytest.Config) -> None:
	config.addinivalue_line(
		'markers',
		'core_capabilities(*names): restrict a matrixed HDL test to variants that advertise the named capabilities.',
	)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
	required_capabilities = _required_core_capabilities(metafunc)
	if 'shared_core_variant' in metafunc.fixturenames:
		variants = _parse_shared_core_variants(str(metafunc.config.getoption('core_variants')))
		variants = variants_with_capabilities(variants, required_capabilities)
		metafunc.parametrize('shared_core_variant', variants, ids=variants)
	elif 'pipelined_core_variant' in metafunc.fixturenames:
		variants = _parse_pipelined_core_variants(str(metafunc.config.getoption('core_variants')))
		variants = variants_with_capabilities(variants, required_capabilities)
		metafunc.parametrize('pipelined_core_variant', variants, ids=variants)


@pytest.fixture
def shared_core_config(shared_core_variant: str) -> Little64CoreConfig:
	return Little64CoreConfig(core_variant=shared_core_variant, reset_vector=0)


@pytest.fixture
def shared_core_adapter(shared_core_variant: str):
	return adapter_for_variant(shared_core_variant)


@pytest.fixture
def shared_special_register_file_factory(shared_core_adapter):
	return shared_core_adapter.create_special_register_file


@pytest.fixture
def shared_tlb_factory(shared_core_adapter):
	return shared_core_adapter.create_tlb


@pytest.fixture
def pipelined_core_config(pipelined_core_variant: str) -> Little64CoreConfig:
	return Little64CoreConfig(core_variant=pipelined_core_variant, reset_vector=0)


@pytest.fixture
def pipelined_core_adapter(pipelined_core_variant: str):
	return adapter_for_variant(pipelined_core_variant)
