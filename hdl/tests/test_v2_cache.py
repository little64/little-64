from __future__ import annotations

import pytest
from amaranth.sim import Simulator

from little64.config import Little64CoreConfig
from little64.v2 import Little64V2Core
from shared_program import encode_gp_imm, encode_ls_reg


STOP_INSTRUCTION = encode_gp_imm('STOP', 0, 0)
STORE_R1_TO_R2 = encode_ls_reg('STORE', 0, 2, 1)
UNSUPPORTED = 0x0000
CACHE_TOPOLOGIES = ('none', 'unified', 'split')


def _qword_bytes(value: int) -> dict[int, int]:
    return {index: (value >> (8 * index)) & 0xFF for index in range(8)}


@pytest.mark.parametrize('cache_topology', CACHE_TOPOLOGIES)
def test_v2_store_invalidates_frontend_line(cache_topology: str) -> None:
    dut = Little64V2Core(Little64CoreConfig(core_variant='v2', cache_topology=cache_topology, reset_vector=0))
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
        observed['line_valid'] = (yield dut.frontend.line_valid)

    sim.add_sync_process(bus_process)
    sim.add_sync_process(driver_process)
    sim.run_until(60e-6, run_passive=True)

    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert memory[2] == 0x00
    assert memory[3] == 0xDF