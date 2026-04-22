from __future__ import annotations

import pytest

from shared_program import run_program_source


pytestmark = pytest.mark.core_capabilities('atomics')


def _u64_bytes(value: int) -> dict[int, int]:
    return {byte_index: (value >> (8 * byte_index)) & 0xFF for byte_index in range(8)}

def test_llr_scr_success_updates_memory_and_preserves_carry_sign(shared_core_config) -> None:
    observed = run_program_source(
        'LLR R14, R3\nSCR R14, R2\nSTOP',
        config=shared_core_config,
        initial_registers={14: 0x2000, 2: 0x0123_4567_89AB_CDEF},
        initial_data_memory={0x2000 + offset: byte for offset, byte in _u64_bytes(0x1122_3344_5566_7788).items()},
        initial_flags=0x6,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == 0x1122_3344_5566_7788
    assert observed['flags'] == 0x7
    assert observed['data_memory'][0x2000] == 0xEF
    assert observed['data_memory'][0x2007] == 0x01


@pytest.mark.parametrize(
    'interfering_store',
    [
        'BYTE_STORE [R14+2], R2',
        'SHORT_STORE [R14+2], R2',
        'WORD_STORE [R14+2], R2',
        'STORE [R14], R2',
    ],
)
def test_overlapping_store_invalidates_llr_reservation(interfering_store: str, shared_core_config) -> None:
    observed = run_program_source(
        f'LLR R14, R3\n{interfering_store}\nSCR R14, R1\nSTOP',
        config=shared_core_config,
        initial_registers={14: 0x2000, 1: 0x0123_4567_89AB_CDEF, 2: 0xAA},
        initial_data_memory={0x2000 + offset: byte for offset, byte in _u64_bytes(0x1122_3344_5566_7788).items()},
        initial_flags=0x6,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == 0x1122_3344_5566_7788
    assert observed['flags'] == 0x6
    assert observed['data_memory'][0x2000] != 0xEF