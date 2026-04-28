from __future__ import annotations

import pytest

from little64_cores.config import DEFAULT_CORE_VARIANT, Little64CoreConfig


def test_default_config_matches_reference_choices() -> None:
    config = Little64CoreConfig()

    assert config.instruction_bus_width == 64
    assert config.data_bus_width == 64
    assert config.core_variant == DEFAULT_CORE_VARIANT
    assert config.cache_topology == 'none'
    assert config.enable_tlb is True
    assert config.tlb_entries == 64
    assert config.optional_platform_registers is False
    assert config.first_irq_vector == 65
    assert config.last_irq_vector == 127


def test_optional_platform_registers_are_toggleable() -> None:
    config = Little64CoreConfig(optional_platform_registers=True)
    assert config.optional_platform_registers is True


def test_non_64_bit_buses_are_rejected() -> None:
    with pytest.raises(ValueError):
        Little64CoreConfig(instruction_bus_width=32)

    with pytest.raises(ValueError):
        Little64CoreConfig(data_bus_width=32)


def test_basic_core_rejects_cache_topologies() -> None:
    with pytest.raises(ValueError):
        Little64CoreConfig(core_variant='basic', cache_topology='split')


def test_v2_core_accepts_future_cache_topologies() -> None:
    assert Little64CoreConfig(core_variant='v2', cache_topology='none').cache_topology == 'none'
    assert Little64CoreConfig(core_variant='v2', cache_topology='unified').cache_topology == 'unified'
    assert Little64CoreConfig(core_variant='v2', cache_topology='split').cache_topology == 'split'


def test_v3_core_variant_is_accepted_for_bringup() -> None:
    config = Little64CoreConfig(core_variant='v3')

    assert config.core_variant == 'v3'
    assert config.cache_topology == 'none'


def test_v3_core_accepts_cache_topologies() -> None:
    assert Little64CoreConfig(core_variant='v3', cache_topology='none').cache_topology == 'none'
    assert Little64CoreConfig(core_variant='v3', cache_topology='unified').cache_topology == 'unified'
    assert Little64CoreConfig(core_variant='v3', cache_topology='split').cache_topology == 'split'


def test_unknown_core_variant_is_rejected() -> None:
    with pytest.raises(ValueError):
        Little64CoreConfig(core_variant='future3')
