from __future__ import annotations

import pytest
from amaranth.sim import Simulator

from little64_cores.config import Little64CoreConfig
from little64_cores.v2 import Little64V2Core
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

    async def bus_process(ctx):
        while True:
            if ctx.get(dut.i_bus.cyc) and ctx.get(dut.i_bus.stb):
                addr = ctx.get(dut.i_bus.adr)
                value = sum((memory.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))
                ctx.set(dut.i_bus.dat_r, value)
                ctx.set(dut.i_bus.ack, 1)
            else:
                ctx.set(dut.i_bus.ack, 0)

            if ctx.get(dut.d_bus.cyc) and ctx.get(dut.d_bus.stb):
                addr = ctx.get(dut.d_bus.adr)
                if ctx.get(dut.d_bus.we):
                    data = ctx.get(dut.d_bus.dat_w)
                    sel = ctx.get(dut.d_bus.sel)
                    for byte_index in range(8):
                        if sel & (1 << byte_index):
                            memory[addr + byte_index] = (data >> (8 * byte_index)) & 0xFF
                else:
                    value = sum((memory.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))
                    ctx.set(dut.d_bus.dat_r, value)
                ctx.set(dut.d_bus.ack, 1)
            else:
                ctx.set(dut.d_bus.ack, 0)
            await ctx.tick()

    async def driver_process(ctx):
        ctx.set(dut.register_file[1], STOP_INSTRUCTION << 16)
        ctx.set(dut.register_file[2], 0)
        for _ in range(48):
            if ctx.get(dut.halted) or ctx.get(dut.locked_up):
                break
            await ctx.tick()
        observed['halted'] = ctx.get(dut.halted)
        observed['locked_up'] = ctx.get(dut.locked_up)
        observed['pc'] = ctx.get(dut.register_file[15])
        observed['line_valid'] = ctx.get(dut.frontend.line_valid)

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(driver_process)
    sim.run_until(60e-6)

    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert memory[2] == 0x00
    assert memory[3] == 0xDF