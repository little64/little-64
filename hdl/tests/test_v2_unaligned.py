from __future__ import annotations

import pytest

from little64_cores.config import Little64CoreConfig
from shared_program import run_program_source


CACHE_TOPOLOGIES = ('unified', 'split')


def _bytes_of(value: int, width: int) -> dict[int, int]:
    return {i: (value >> (8 * i)) & 0xFF for i in range(width)}


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
@pytest.mark.parametrize(
    ('opcode', 'addr', 'value'),
    [
        ('LOAD', 0x1007, 0x0102_0304_0506_0708),
        ('WORD_LOAD', 0x1006, 0xDEAD_BEEF),
        ('SHORT_LOAD', 0x1007, 0xBEEF),
    ],
)
def test_v2_unaligned_split_loads(cache_topology: str, opcode: str, addr: int, value: int) -> None:
    width = {'LOAD': 8, 'WORD_LOAD': 4, 'SHORT_LOAD': 2}[opcode]
    observed = run_program_source(
        f'{opcode} [R2], R1\nSTOP',
        config=Little64CoreConfig(core_variant='v2', cache_topology=cache_topology, reset_vector=0),
        initial_registers={2: addr},
        initial_data_memory={addr + i: byte for i, byte in _bytes_of(value, width).items()},
        max_cycles=160,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == value


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
@pytest.mark.parametrize(
    ('opcode', 'addr', 'value', 'width'),
    [
        ('STORE', 0x1007, 0x0102_0304_0506_0708, 8),
        ('WORD_STORE', 0x1006, 0xDEAD_BEEF, 4),
        ('SHORT_STORE', 0x1007, 0xBEEF, 2),
    ],
)
def test_v2_unaligned_split_stores(cache_topology: str, opcode: str, addr: int, value: int, width: int) -> None:
    observed = run_program_source(
        f'{opcode} [R2], R1\nSTOP',
        config=Little64CoreConfig(core_variant='v2', cache_topology=cache_topology, reset_vector=0),
        initial_registers={1: value, 2: addr},
        max_cycles=160,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    for index in range(width):
        assert observed['data_memory'].get(addr + index, 0) == ((value >> (8 * index)) & 0xFF)


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
@pytest.mark.parametrize('offset', range(8), ids=[f'off{i}' for i in range(8)])
def test_v2_push_pop_with_unaligned_stack(cache_topology: str, offset: int) -> None:
    sp = 0x2000 + offset
    value = 0xCAFE_BABE_DEAD_BEEF
    observed = run_program_source(
        'PUSH R1, R13\nPOP R3, R13\nSTOP',
        config=Little64CoreConfig(core_variant='v2', cache_topology=cache_topology, reset_vector=0),
        initial_registers={1: value, 13: sp},
        max_cycles=192,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == value
    assert observed['registers'][13] == sp