from __future__ import annotations

import pytest
from amaranth.sim import Simulator

from little64.config import Little64CoreConfig
from little64.variants import create_core
from shared_program import assemble_source


CACHE_TOPOLOGIES = ('none', 'unified', 'split')
UART_MMIO_BASE = 0xF0001000
FETCH_TRANSLATE_STATE = 1


def _read_qword(memory: dict[int, int], addr: int) -> int:
    return sum((memory.get(addr + index, 0) & 0xFF) << (8 * index) for index in range(8))


def _run_v2_program_with_mmio_trace(
    source: str,
    *,
    cache_topology: str,
    initial_registers: dict[int, int],
    initial_data_memory: dict[int, int] | None = None,
    max_cycles: int = 128,
) -> dict[str, object]:
    dut = create_core(Little64CoreConfig(core_variant='v2', cache_topology=cache_topology, reset_vector=0))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    code_memory: dict[int, int] = {}
    data_memory: dict[int, int] = dict(initial_data_memory or {})
    for word_index, word in enumerate(assemble_source(source)):
        base = word_index * 2
        code_memory[base] = word & 0xFF
        code_memory[base + 1] = (word >> 8) & 0xFF

    mmio_writes: list[tuple[int, int, int]] = []
    commit_pcs: list[int] = []
    ready = {'value': False}
    i_request = {'active': False, 'responded': False, 'addr': 0}
    d_request = {'active': False, 'responded': False, 'addr': 0, 'data': 0, 'sel': 0, 'we': 0}
    observed: dict[str, object] = {}

    def bus_process():
        while True:
            i_active = ready['value'] and (yield dut.i_bus.cyc) and (yield dut.i_bus.stb)
            i_addr = (yield dut.i_bus.adr)
            if not i_active:
                yield dut.i_bus.ack.eq(0)
                i_request.update(active=False, responded=False, addr=0)
            elif (not i_request['active']) or i_request['addr'] != i_addr:
                yield dut.i_bus.ack.eq(0)
                i_request.update(active=True, responded=False, addr=i_addr)
            elif not i_request['responded']:
                yield dut.i_bus.dat_r.eq(_read_qword(code_memory, i_addr))
                yield dut.i_bus.ack.eq(1)
                i_request['responded'] = True
            else:
                yield dut.i_bus.ack.eq(0)

            d_active = ready['value'] and (yield dut.d_bus.cyc) and (yield dut.d_bus.stb)
            d_addr = (yield dut.d_bus.adr)
            d_sel = (yield dut.d_bus.sel)
            d_value = (yield dut.d_bus.dat_w)
            d_we = (yield dut.d_bus.we)
            if not d_active:
                yield dut.d_bus.ack.eq(0)
                d_request.update(active=False, responded=False, addr=0, data=0, sel=0, we=0)
            elif (
                (not d_request['active']) or
                d_request['addr'] != d_addr or
                d_request['data'] != d_value or
                d_request['sel'] != d_sel or
                d_request['we'] != d_we
            ):
                yield dut.d_bus.ack.eq(0)
                d_request.update(active=True, responded=False, addr=d_addr, data=d_value, sel=d_sel, we=d_we)
            elif not d_request['responded']:
                if d_we:
                    mmio_writes.append((d_addr, d_sel, d_value))
                    for byte_index in range(8):
                        if d_sel & (1 << byte_index):
                            data_memory[d_addr + byte_index] = (d_value >> (8 * byte_index)) & 0xFF
                else:
                    yield dut.d_bus.dat_r.eq(_read_qword(data_memory, d_addr))
                yield dut.d_bus.ack.eq(1)
                d_request['responded'] = True
            else:
                yield dut.d_bus.ack.eq(0)
            yield

    def observe_process():
        yield
        for index, value in initial_registers.items():
            yield dut.register_file[index].eq(value)
        yield dut.frontend.line_valid.eq(0)
        yield dut.fetch_pc.eq(0)
        yield dut.fetch_phys_addr.eq(0)
        yield dut.current_instruction.eq(0)
        yield dut.execute_instruction.eq(0)
        yield dut.locked_up.eq(0)
        yield dut.state.eq(FETCH_TRANSLATE_STATE)
        yield
        ready['value'] = True

        for _ in range(max_cycles):
            yield
            if (yield dut.commit_valid):
                commit_pcs.append((yield dut.commit_pc))
            if (yield dut.halted) or (yield dut.locked_up):
                break

        observed['commit_pcs'] = commit_pcs
        observed['mmio_writes'] = mmio_writes
        observed['halted'] = (yield dut.halted)
        observed['locked_up'] = (yield dut.locked_up)
        observed['pc'] = (yield dut.register_file[15])
        observed['r1'] = (yield dut.register_file[1])

    sim.add_sync_process(bus_process)
    sim.add_sync_process(observe_process)
    sim.run_until((max_cycles + 8) * 1e-6, run_passive=True)
    return observed


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
def test_v2_mmio_byte_store_commits_once_and_writes_once(cache_topology: str) -> None:
    observed = _run_v2_program_with_mmio_trace(
        'BYTE_STORE [R2], R1\nSTOP',
        cache_topology=cache_topology,
        initial_registers={1: 0x41, 2: UART_MMIO_BASE, 15: 0},
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_pcs'] == [0]
    assert observed['mmio_writes'] == [(UART_MMIO_BASE, 0x01, 0x41)]
    assert observed['pc'] == 0x4


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
def test_v2_mmio_branch_to_store_has_single_terminal_write(cache_topology: str) -> None:
    observed = _run_v2_program_with_mmio_trace(
        'BYTE_LOAD [R3], R1\nTEST R0, R1\nJUMP.Z @emit\nSTOP\nemit:\nBYTE_STORE [R2], R1\nSTOP',
        cache_topology=cache_topology,
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
    observed = _run_v2_program_with_mmio_trace(
        'LOAD [R2], R1\nSTOP',
        cache_topology=cache_topology,
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
    observed = _run_v2_program_with_mmio_trace(
        'LOAD [R2], R1\nSTOP',
        cache_topology=cache_topology,
        initial_registers={2: 0x2003, 15: 0},
        initial_data_memory={0x2000 + index: index for index in range(16)},
        max_cycles=192,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_pcs'] == [0]
    assert observed['r1'] == 0x0A09080706050403
    assert observed['pc'] == 0x4