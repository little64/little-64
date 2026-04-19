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

from little64.config import CORE_VARIANTS, Little64CoreConfig, SUPPORTED_CORE_VARIANTS


def _parse_shared_core_variants(raw_value: str) -> list[str]:
	normalized = raw_value.strip().lower()
	if normalized in ('', 'default', 'current'):
		return ['v2', 'v3']
	if normalized == 'v2':
		return ['v2']
	if normalized == 'all':
		return list(CORE_VARIANTS)

	variants = [value.strip().lower() for value in raw_value.split(',') if value.strip()]
	if not variants:
		raise pytest.UsageError('`--core-variants` requires at least one variant name')

	unknown = [variant for variant in variants if variant not in SUPPORTED_CORE_VARIANTS]
	if unknown:
		raise pytest.UsageError(
			f'Unsupported core variants in `--core-variants`: {", ".join(unknown)}; expected one of {", ".join(SUPPORTED_CORE_VARIANTS)} or `all`'
		)
	return list(dict.fromkeys(variants))


def pytest_addoption(parser: pytest.Parser) -> None:
	parser.addoption(
		'--core-variants',
		action='store',
		default='default',
		help='Shared HDL test core variants to run: `default` (`v2,v3`), `v2`, `basic`, experimental `v3`, comma-separated variants, or `all`.',
	)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
	if 'shared_core_variant' not in metafunc.fixturenames:
		return
	variants = _parse_shared_core_variants(str(metafunc.config.getoption('core_variants')))
	metafunc.parametrize('shared_core_variant', variants, ids=variants)


@pytest.fixture
def shared_core_config(shared_core_variant: str) -> Little64CoreConfig:
	return Little64CoreConfig(core_variant=shared_core_variant, reset_vector=0)
