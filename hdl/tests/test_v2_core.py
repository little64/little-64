from __future__ import annotations

from amaranth.sim import Simulator

from little64_cores.config import Little64CoreConfig
from little64_cores.isa import TrapVector
from little64_cores.v2 import Little64V2Core, Little64V2FetchFrontend, V2PipelineState


STOP_INSTRUCTION = 0xDF00
LDI_R1_IMM12 = 0x8121
UNSUPPORTED_GP_INSTRUCTION = 0xC500


def test_v2_frontend_reuses_buffered_fetch_line() -> None:
    frontend = Little64V2FetchFrontend()
    sim = Simulator(frontend)
    sim.add_clock(1e-6)

    seen_addresses: list[int] = []
    observed = {}

    async def driver_process(ctx):
        ctx.set(frontend.pc, 0)
        for cycle in range(8):
            if cycle == 4:
                ctx.set(frontend.pc, 2)
            await ctx.tick()
        observed['line_valid'] = ctx.get(frontend.line_valid)
        observed['instruction_valid'] = ctx.get(frontend.instruction_valid)
        observed['instruction_word'] = ctx.get(frontend.instruction_word)

    async def bus_process(ctx):
        request_active_last = False
        while True:
            request_active = ctx.get(frontend.i_bus.cyc) and ctx.get(frontend.i_bus.stb)
            if request_active and not request_active_last:
                seen_addresses.append(ctx.get(frontend.i_bus.adr))
            if request_active:
                ctx.set(frontend.i_bus.dat_r, STOP_INSTRUCTION | (LDI_R1_IMM12 << 16))
                ctx.set(frontend.i_bus.ack, 1)
            else:
                ctx.set(frontend.i_bus.ack, 0)
            request_active_last = request_active
            await ctx.tick()

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(driver_process)
    sim.run_until(10e-6)

    assert seen_addresses == [0]
    assert observed['line_valid'] == 1
    assert observed['instruction_valid'] == 1
    assert observed['instruction_word'] == LDI_R1_IMM12


def test_v2_frontend_ignores_stale_response_after_invalidate() -> None:
    frontend = Little64V2FetchFrontend()
    sim = Simulator(frontend)
    sim.add_clock(1e-6)

    line0 = 0xE004_B10D_940D_800D
    line8 = 0x0000_0000_0000_00BE
    line16 = 0x1021_1002_101F_43B1

    seen_addresses: list[int] = []
    pending_responses: list[list[int]] = []
    observed = {}

    async def driver_process(ctx):
        ctx.set(frontend.pc, 0)
        ctx.set(frontend.invalidate, 0)
        for cycle in range(16):
            if cycle == 6:
                ctx.set(frontend.pc, 8)
            if cycle == 7:
                ctx.set(frontend.invalidate, 1)
                ctx.set(frontend.pc, 16)
            elif cycle == 8:
                ctx.set(frontend.invalidate, 0)
            await ctx.tick()
        observed['line_valid'] = ctx.get(frontend.line_valid)
        observed['line_base'] = ctx.get(frontend.line_base)
        observed['line_data'] = ctx.get(frontend.line_data)
        observed['instruction_valid'] = ctx.get(frontend.instruction_valid)
        observed['instruction_word'] = ctx.get(frontend.instruction_word)

    async def bus_process(ctx):
        request_active_last = False
        while True:
            ctx.set(frontend.i_bus.ack, 0)
            ctx.set(frontend.i_bus.err, 0)
            ctx.set(frontend.i_bus.dat_r, 0)
            request_active = ctx.get(frontend.i_bus.cyc) and ctx.get(frontend.i_bus.stb)
            if request_active and not request_active_last:
                address = ctx.get(frontend.i_bus.adr)
                seen_addresses.append(address)
                pending_responses.append([address, 1])

            for pending in pending_responses:
                pending[1] -= 1

            if pending_responses and pending_responses[0][1] < 0:
                address = pending_responses.pop(0)[0]
                value = {0: line0, 8: line8, 16: line16}[address]
                ctx.set(frontend.i_bus.dat_r, value)
                ctx.set(frontend.i_bus.ack, 1)

            request_active_last = request_active
            await ctx.tick()

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(driver_process)
    sim.run_until(20e-6)

    assert seen_addresses == [0, 8, 16]
    assert observed['line_valid'] == 1
    assert observed['line_base'] == 16
    assert observed['line_data'] == line16
    assert observed['instruction_valid'] == 1
    assert observed['instruction_word'] == 0x43B1


def test_v2_frontend_reissues_redirected_fetch_after_cancelled_ack() -> None:
    frontend = Little64V2FetchFrontend()
    sim = Simulator(frontend)
    sim.add_clock(1e-6)

    line78 = 0x4444_3333_2222_1111
    line80 = 0x8888_7777_6666_5555
    line88 = 0xCCCC_BBBB_AAAA_9999
    expected_lines = {0x78: line78, 0x80: line80, 0x88: line88}

    seen_addresses: list[int] = []
    pending_responses: list[list[int]] = []
    observed = {}

    async def driver_process(ctx):
        ctx.set(frontend.pc, 0x78)
        ctx.set(frontend.invalidate, 0)
        for cycle in range(22):
            if cycle == 7:
                ctx.set(frontend.pc, 0x80)
            if cycle == 9:
                ctx.set(frontend.invalidate, 1)
                ctx.set(frontend.pc, 0x88)
            elif cycle == 11:
                ctx.set(frontend.invalidate, 0)
            await ctx.tick()
        observed['line_valid'] = ctx.get(frontend.line_valid)
        observed['line_base'] = ctx.get(frontend.line_base)
        observed['line_data'] = ctx.get(frontend.line_data)
        observed['instruction_valid'] = ctx.get(frontend.instruction_valid)
        observed['instruction_word'] = ctx.get(frontend.instruction_word)

    async def bus_process(ctx):
        request_active_last = False
        while True:
            ctx.set(frontend.i_bus.ack, 0)
            ctx.set(frontend.i_bus.err, 0)
            ctx.set(frontend.i_bus.dat_r, 0)

            request_active = ctx.get(frontend.i_bus.cyc) and ctx.get(frontend.i_bus.stb)
            if request_active and not request_active_last:
                address = ctx.get(frontend.i_bus.adr)
                if address in expected_lines:
                    seen_addresses.append(address)
                pending_responses.append([address, 1])

            for pending in pending_responses:
                pending[1] -= 1

            if pending_responses and pending_responses[0][1] < 0:
                address = pending_responses.pop(0)[0]
                value = expected_lines.get(address, 0)
                ctx.set(frontend.i_bus.dat_r, value)
                ctx.set(frontend.i_bus.ack, 1)

            request_active_last = request_active
            await ctx.tick()

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(driver_process)
    sim.run_until(28e-6)

    assert seen_addresses == [0x78, 0x80, 0x88]
    assert observed['line_valid'] == 1
    assert observed['line_base'] == 0x88
    assert observed['line_data'] == line88
    assert observed['instruction_valid'] == 1
    assert observed['instruction_word'] == 0x9999


def test_v2_core_fetches_stop_then_halts() -> None:
    dut = Little64V2Core(Little64CoreConfig(core_variant='v2', reset_vector=0))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    observed = {'commit_count': 0}

    async def bus_process(ctx):
        while True:
            if ctx.get(dut.i_bus.cyc) and ctx.get(dut.i_bus.stb):
                ctx.set(dut.i_bus.dat_r, STOP_INSTRUCTION)
                ctx.set(dut.i_bus.ack, 1)
            else:
                ctx.set(dut.i_bus.ack, 0)
            await ctx.tick()

    async def checker_process(ctx):
        for _ in range(32):
            if ctx.get(dut.commit_valid):
                observed['commit_count'] += 1
            if ctx.get(dut.halted) or ctx.get(dut.locked_up):
                break
            await ctx.tick()
        observed['halted'] = ctx.get(dut.halted)
        observed['locked_up'] = ctx.get(dut.locked_up)
        observed['state'] = ctx.get(dut.state)
        observed['instruction'] = ctx.get(dut.current_instruction)

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(checker_process)
    sim.run_until(40e-6)

    assert observed['commit_count'] == 0
    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert observed['state'] == V2PipelineState.HALTED
    assert observed['instruction'] == STOP_INSTRUCTION


def test_v2_core_decodes_stop_from_upper_fetch_slot() -> None:
    dut = Little64V2Core(Little64CoreConfig(core_variant='v2', reset_vector=6))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    observed = {}

    async def bus_process(ctx):
        while True:
            if ctx.get(dut.i_bus.cyc) and ctx.get(dut.i_bus.stb):
                ctx.set(dut.i_bus.dat_r, STOP_INSTRUCTION << 48)
                ctx.set(dut.i_bus.ack, 1)
            else:
                ctx.set(dut.i_bus.ack, 0)
            await ctx.tick()

    async def checker_process(ctx):
        for _ in range(20):
            if ctx.get(dut.halted) or ctx.get(dut.locked_up):
                break
            await ctx.tick()
        observed['instruction'] = ctx.get(dut.current_instruction)
        observed['halted'] = ctx.get(dut.halted)
        observed['fetch_pc'] = ctx.get(dut.fetch_pc)
        observed['fetch_phys_addr'] = ctx.get(dut.fetch_phys_addr)

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(checker_process)
    sim.run_until(20e-6)

    assert observed['instruction'] == STOP_INSTRUCTION
    assert observed['halted'] == 1
    assert observed['fetch_pc'] == 6
    assert observed['fetch_phys_addr'] == 6


def test_v2_core_records_invalid_instruction_trap_before_lockup() -> None:
    dut = Little64V2Core(Little64CoreConfig(core_variant='v2', reset_vector=0))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    observed = {'commit_count': 0}

    async def bus_process(ctx):
        while True:
            if ctx.get(dut.i_bus.cyc) and ctx.get(dut.i_bus.stb):
                ctx.set(dut.i_bus.dat_r, UNSUPPORTED_GP_INSTRUCTION)
                ctx.set(dut.i_bus.ack, 1)
            else:
                ctx.set(dut.i_bus.ack, 0)

            if ctx.get(dut.d_bus.cyc) and ctx.get(dut.d_bus.stb):
                ctx.set(dut.d_bus.dat_r, 0)
                ctx.set(dut.d_bus.ack, 1)
            else:
                ctx.set(dut.d_bus.ack, 0)
            await ctx.tick()

    async def checker_process(ctx):
        for _ in range(32):
            if ctx.get(dut.commit_valid):
                observed['commit_count'] += 1
            if ctx.get(dut.halted) or ctx.get(dut.locked_up):
                break
            await ctx.tick()
        observed['halted'] = ctx.get(dut.halted)
        observed['locked_up'] = ctx.get(dut.locked_up)
        observed['state'] = ctx.get(dut.state)
        observed['trap_cause'] = ctx.get(dut.special_regs.trap_cause)
        observed['trap_pc'] = ctx.get(dut.special_regs.trap_pc)

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(checker_process)
    sim.run_until(40e-6)

    assert observed['commit_count'] == 0
    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['state'] == V2PipelineState.STALLED
    assert observed['trap_cause'] == TrapVector.INVALID_INSTRUCTION
    assert observed['trap_pc'] == 0