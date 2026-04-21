from __future__ import annotations

import pytest

from little64_cores.config import Little64CoreConfig
from mmio_trace import run_program_with_mmio_trace


CACHE_TOPOLOGIES = ('none', 'unified', 'split')
UART_MMIO_BASE = 0xF0001000


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
def test_v2_mmio_byte_store_commits_once_and_writes_once(cache_topology: str) -> None:
    observed = run_program_with_mmio_trace(
        'BYTE_STORE [R2], R1\nSTOP',
        config=Little64CoreConfig(core_variant='v2', cache_topology=cache_topology, reset_vector=0),
        initial_registers={1: 0x41, 2: UART_MMIO_BASE, 15: 0},
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_pcs'] == [0]
    assert observed['mmio_writes'] == [(UART_MMIO_BASE, 0x01, 0x41)]
    assert observed['pc'] == 0x4


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
def test_v2_mmio_branch_to_store_has_single_terminal_write(cache_topology: str) -> None:
    observed = run_program_with_mmio_trace(
        'BYTE_LOAD [R3], R1\nTEST R0, R1\nJUMP.Z @emit\nSTOP\nemit:\nBYTE_STORE [R2], R1\nSTOP',
        config=Little64CoreConfig(core_variant='v2', cache_topology=cache_topology, reset_vector=0),
        initial_registers={2: UART_MMIO_BASE, 3: 0x2000, 15: 0},
        initial_data_memory={0x2000: 0x00},
        max_cycles=160,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_pcs'] == [0, 2, 4, 8]
    assert observed['mmio_writes'] == [(UART_MMIO_BASE, 0x01, 0x00)]
    assert observed['pc'] == 0xC


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
def test_v2_aligned_load_completes_with_single_delayed_ack(cache_topology: str) -> None:
    observed = run_program_with_mmio_trace(
        'LOAD [R2], R1\nSTOP',
        config=Little64CoreConfig(core_variant='v2', cache_topology=cache_topology, reset_vector=0),
        initial_registers={2: 0x2000, 15: 0},
        initial_data_memory={
            0x2000: 0x88,
            0x2001: 0x77,
            0x2002: 0x66,
            0x2003: 0x55,
            0x2004: 0x44,
            0x2005: 0x33,
            0x2006: 0x22,
            0x2007: 0x11,
        },
        max_cycles=160,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_pcs'] == [0]
    assert observed['r1'] == 0x1122334455667788
    assert observed['pc'] == 0x4


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
def test_v2_split_load_completes_with_held_bus_request(cache_topology: str) -> None:
    observed = run_program_with_mmio_trace(
        'LOAD [R2], R1\nSTOP',
        config=Little64CoreConfig(core_variant='v2', cache_topology=cache_topology, reset_vector=0),
        initial_registers={2: 0x2003, 15: 0},
        initial_data_memory={0x2000 + index: index for index in range(16)},
        max_cycles=192,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_pcs'] == [0]
    assert observed['r1'] == 0x0A09080706050403
    assert observed['pc'] == 0x4