from __future__ import annotations

import pytest

from little64.config import Little64CoreConfig


def test_default_config_matches_reference_choices() -> None:
    config = Little64CoreConfig()

    assert config.instruction_bus_width == 64
    assert config.data_bus_width == 64
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
