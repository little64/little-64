from __future__ import annotations

from amaranth.sim import Simulator

from little64_cores.config import Little64CoreConfig

from core_test_contract import adapter_for_variant
from shared_program import assemble_source


def _read_qword(memory: dict[int, int], addr: int) -> int:
    return sum((memory.get(addr + index, 0) & 0xFF) << (8 * index) for index in range(8))


def run_program_with_mmio_trace(
    source: str,
    *,
    config: Little64CoreConfig,
    initial_registers: dict[int, int],
    initial_data_memory: dict[int, int] | None = None,
    max_cycles: int = 128,
) -> dict[str, object]:
    adapter = adapter_for_variant(config.core_variant)
    dut = adapter.create_core(config)
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

    async def bus_process(ctx):
        while True:
            i_active = ready['value'] and ctx.get(dut.i_bus.cyc) and ctx.get(dut.i_bus.stb)
            i_addr = ctx.get(dut.i_bus.adr)
            if not i_active:
                ctx.set(dut.i_bus.ack, 0)
                i_request.update(active=False, responded=False, addr=0)
            elif (not i_request['active']) or i_request['addr'] != i_addr:
                ctx.set(dut.i_bus.ack, 0)
                i_request.update(active=True, responded=False, addr=i_addr)
            elif not i_request['responded']:
                ctx.set(dut.i_bus.dat_r, _read_qword(code_memory, i_addr))
                ctx.set(dut.i_bus.ack, 1)
                i_request['responded'] = True
            else:
                ctx.set(dut.i_bus.ack, 0)

            d_active = ready['value'] and ctx.get(dut.d_bus.cyc) and ctx.get(dut.d_bus.stb)
            d_addr = ctx.get(dut.d_bus.adr)
            d_sel = ctx.get(dut.d_bus.sel)
            d_value = ctx.get(dut.d_bus.dat_w)
            d_we = ctx.get(dut.d_bus.we)
            if not d_active:
                ctx.set(dut.d_bus.ack, 0)
                d_request.update(active=False, responded=False, addr=0, data=0, sel=0, we=0)
            elif (
                (not d_request['active']) or
                d_request['addr'] != d_addr or
                d_request['data'] != d_value or
                d_request['sel'] != d_sel or
                d_request['we'] != d_we
            ):
                ctx.set(dut.d_bus.ack, 0)
                d_request.update(active=True, responded=False, addr=d_addr, data=d_value, sel=d_sel, we=d_we)
            elif not d_request['responded']:
                if d_we:
                    mmio_writes.append((d_addr, d_sel, d_value))
                    for byte_index in range(8):
                        if d_sel & (1 << byte_index):
                            data_memory[d_addr + byte_index] = (d_value >> (8 * byte_index)) & 0xFF
                else:
                    ctx.set(dut.d_bus.dat_r, _read_qword(data_memory, d_addr))
                ctx.set(dut.d_bus.ack, 1)
                d_request['responded'] = True
            else:
                ctx.set(dut.d_bus.ack, 0)
            await ctx.tick()

    async def observe_process(ctx):
        await adapter.prepare_for_execution(
            ctx,
            dut,
            config,
            ready=ready,
            initial_registers=initial_registers,
        )

        ready['value'] = True

        for _ in range(max_cycles):
            await ctx.tick()
            if ctx.get(dut.commit_valid):
                commit_pcs.append(ctx.get(dut.commit_pc))
            if ctx.get(dut.halted) or ctx.get(dut.locked_up):
                break

        observed['commit_pcs'] = commit_pcs
        observed['mmio_writes'] = mmio_writes
        observed['halted'] = ctx.get(dut.halted)
        observed['locked_up'] = ctx.get(dut.locked_up)
        observed['pc'] = ctx.get(dut.register_file[15])
        observed['r1'] = ctx.get(dut.register_file[1])

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(observe_process)
    sim.run_until((max_cycles + 8) * 1e-6)
    return observed