from __future__ import annotations

import pytest
from amaranth.sim import Simulator

from little64_cores.config import Little64CoreConfig
from little64_cores.v3 import Little64V3Core
from shared_program import assemble_source, encode_gp_imm, encode_ls_reg


STOP_INSTRUCTION = encode_gp_imm('STOP', 0, 0)
STORE_R1_TO_R2 = encode_ls_reg('STORE', 0, 2, 1)
UNSUPPORTED = 0x0000
CACHE_TOPOLOGIES = ('none', 'unified', 'split')


def _qword_bytes(value: int) -> dict[int, int]:
    return {index: (value >> (8 * index)) & 0xFF for index in range(8)}


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
def test_v3_store_reaches_updated_instruction_stream(cache_topology: str) -> None:
    dut = Little64V3Core(Little64CoreConfig(core_variant='v3', cache_topology=cache_topology, reset_vector=0))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    memory: dict[int, int] = {
        0: STORE_R1_TO_R2 & 0xFF,
        1: (STORE_R1_TO_R2 >> 8) & 0xFF,
        2: UNSUPPORTED & 0xFF,
        3: (UNSUPPORTED >> 8) & 0xFF,
    }
    memory.update(_qword_bytes(STOP_INSTRUCTION << 16))

    observed: dict[str, int] = {}

    def bus_process():
        while True:
            if (yield dut.i_bus.cyc) and (yield dut.i_bus.stb):
                addr = (yield dut.i_bus.adr)
                value = sum((memory.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))
                yield dut.i_bus.dat_r.eq(value)
                yield dut.i_bus.ack.eq(1)
            else:
                yield dut.i_bus.ack.eq(0)

            if (yield dut.d_bus.cyc) and (yield dut.d_bus.stb):
                addr = (yield dut.d_bus.adr)
                if (yield dut.d_bus.we):
                    data = (yield dut.d_bus.dat_w)
                    sel = (yield dut.d_bus.sel)
                    for byte_index in range(8):
                        if sel & (1 << byte_index):
                            memory[addr + byte_index] = (data >> (8 * byte_index)) & 0xFF
                else:
                    value = sum((memory.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))
                    yield dut.d_bus.dat_r.eq(value)
                yield dut.d_bus.ack.eq(1)
            else:
                yield dut.d_bus.ack.eq(0)
            yield

    def driver_process():
        yield dut.register_file[1].eq(STOP_INSTRUCTION << 16)
        yield dut.register_file[2].eq(0)
        for _ in range(48):
            if (yield dut.halted) or (yield dut.locked_up):
                break
            yield
        observed['halted'] = (yield dut.halted)
        observed['locked_up'] = (yield dut.locked_up)
        observed['pc'] = (yield dut.register_file[15])

    sim.add_sync_process(bus_process)
    sim.add_sync_process(driver_process)
    sim.run_until(60e-6, run_passive=True)

    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert observed['pc'] == 0x4
    assert memory[2] == 0x00
    assert memory[3] == 0xDF


@pytest.mark.parametrize(
    ('cache_topology', 'expected_read_transactions'),
    [
        ('none', 2),
        ('unified', 1),
        ('split', 1),
    ],
)
def test_v3_repeated_load_reuses_cached_line(cache_topology: str, expected_read_transactions: int) -> None:
    dut = Little64V3Core(Little64CoreConfig(core_variant='v3', cache_topology=cache_topology, reset_vector=0))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    code = {}
    for word_index, word in enumerate(assemble_source('LOAD [R2], R1\nLOAD [R2], R3\nSTOP')):
        base = word_index * 2
        code[base] = word & 0xFF
        code[base + 1] = (word >> 8) & 0xFF

    data = {
        0x2000: 0x88,
        0x2001: 0x77,
        0x2002: 0x66,
        0x2003: 0x55,
        0x2004: 0x44,
        0x2005: 0x33,
        0x2006: 0x22,
        0x2007: 0x11,
    }
    observed: dict[str, int] = {}
    data_reads = {'count': 0}
    d_request = {'active': False, 'responded': False, 'addr': 0, 'data': 0, 'sel': 0, 'we': 0}

    def bus_process():
        while True:
            if (yield dut.i_bus.cyc) and (yield dut.i_bus.stb):
                addr = (yield dut.i_bus.adr)
                value = sum((code.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))
                yield dut.i_bus.dat_r.eq(value)
                yield dut.i_bus.ack.eq(1)
            else:
                yield dut.i_bus.ack.eq(0)

            if (yield dut.d_bus.cyc) and (yield dut.d_bus.stb):
                addr = (yield dut.d_bus.adr)
                sel = (yield dut.d_bus.sel)
                write = (yield dut.d_bus.we)
                write_data = (yield dut.d_bus.dat_w)
                if (
                    (not d_request['active']) or
                    d_request['addr'] != addr or
                    d_request['data'] != write_data or
                    d_request['sel'] != sel or
                    d_request['we'] != write
                ):
                    d_request.update(active=True, responded=False, addr=addr, data=write_data, sel=sel, we=write)
                    yield dut.d_bus.ack.eq(0)
                    yield
                    continue

                if d_request['responded']:
                    yield dut.d_bus.ack.eq(0)
                    yield
                    continue

                if write:
                    data_value = (yield dut.d_bus.dat_w)
                    for byte_index in range(8):
                        if sel & (1 << byte_index):
                            data[addr + byte_index] = (data_value >> (8 * byte_index)) & 0xFF
                else:
                    data_reads['count'] += 1
                    value = sum((data.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))
                    yield dut.d_bus.dat_r.eq(value)
                yield dut.d_bus.ack.eq(1)
                d_request['responded'] = True
            else:
                yield dut.d_bus.ack.eq(0)
                d_request.update(active=False, responded=False, addr=0, data=0, sel=0, we=0)
            yield

    def driver_process():
        yield dut.register_file[2].eq(0x2000)
        for _ in range(64):
            if (yield dut.halted) or (yield dut.locked_up):
                break
            yield
        observed['halted'] = (yield dut.halted)
        observed['locked_up'] = (yield dut.locked_up)
        observed['pc'] = (yield dut.register_file[15])
        observed['r1'] = (yield dut.register_file[1])
        observed['r3'] = (yield dut.register_file[3])

    sim.add_sync_process(bus_process)
    sim.add_sync_process(driver_process)
    sim.run_until(80e-6, run_passive=True)

    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert observed['pc'] == 0x6
    assert observed['r1'] == 0x1122334455667788
    assert observed['r3'] == 0x1122334455667788
    assert data_reads['count'] == expected_read_transactions