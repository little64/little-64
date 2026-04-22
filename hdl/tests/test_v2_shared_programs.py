from __future__ import annotations

import pytest

from little64_cores.config import Little64CoreConfig
from shared_program import load_jump_program_cases, load_memory_program_cases, run_program_source


CACHE_TOPOLOGIES = ('unified', 'split')


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
@pytest.mark.parametrize('case', load_memory_program_cases(), ids=lambda case: case.description)
def test_v2_shared_memory_program_cases(case, cache_topology: str) -> None:
    observed = run_program_source(
        case.source,
        config=Little64CoreConfig(core_variant='v2', cache_topology=cache_topology, reset_vector=0),
        max_cycles=384,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1

    if case.reg_a >= 0:
        assert observed['registers'][case.reg_a] == case.value_a
    if case.reg_b >= 0:
        assert observed['registers'][case.reg_b] == case.value_b
    if case.reg_c >= 0:
        assert observed['registers'][case.reg_c] == case.value_c