from __future__ import annotations

import pytest

from shared_program import run_program_source


pytestmark = pytest.mark.core_capabilities('commit-profile')


EXPECTED_COMMIT_COUNTS = {
    'basic': {
        'simple': 4,
        'memory': 6,
    },
    'v2': {
        'simple': 3,
        'memory': 5,
    },
    'v3': {
        'simple': 3,
        'memory': 5,
    },
    'v4': {
        'simple': 3,
        'memory': 5,
    },
}


def test_simple_program_commit_profile(shared_core_config, shared_core_variant: str) -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #42, R1',
            'LDI #7, R2',
            'ADD R1, R2',
            'STOP',
        ]),
        config=shared_core_config,
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_count'] == EXPECTED_COMMIT_COUNTS[shared_core_variant]['simple']


def test_memory_program_commit_profile(shared_core_config, shared_core_variant: str) -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #0x10, R2',
            'LDI.S1 #0x10, R2',
            'LDI #0xAB, R1',
            'STORE [R2], R1',
            'LOAD [R2], R3',
            'STOP',
        ]),
        config=shared_core_config,
        max_cycles=48,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_count'] == EXPECTED_COMMIT_COUNTS[shared_core_variant]['memory']