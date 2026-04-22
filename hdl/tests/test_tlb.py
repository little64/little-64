from __future__ import annotations

import pytest

from amaranth.sim import Simulator


pytestmark = pytest.mark.core_capabilities('tlb')


def test_tlb_fill_lookup_and_flush(shared_tlb_factory) -> None:
    dut = shared_tlb_factory(entries=8)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def process(ctx):
        ctx.set(dut.lookup_vaddr, 0x0000_0000_0000_1234)
        assert ctx.get(dut.lookup_hit) == 0

        ctx.set(dut.fill_valid, 1)
        ctx.set(dut.fill_vpage, 0x0000_0000_0000_1)
        ctx.set(dut.fill_ppage, 0x0000_0000_0001_01)
        ctx.set(dut.fill_perm_read, 1)
        ctx.set(dut.fill_perm_write, 1)
        ctx.set(dut.fill_perm_execute, 0)
        ctx.set(dut.fill_perm_user, 1)
        await ctx.tick()

        ctx.set(dut.fill_valid, 0)
        ctx.set(dut.lookup_vaddr, 0x0000_0000_0000_1234)
        assert ctx.get(dut.lookup_hit) == 1
        assert ctx.get(dut.lookup_paddr) == 0x0000_0000_0010_1234
        assert ctx.get(dut.lookup_perm_read) == 1
        assert ctx.get(dut.lookup_perm_write) == 1
        assert ctx.get(dut.lookup_perm_execute) == 0
        assert ctx.get(dut.lookup_perm_user) == 1

        ctx.set(dut.flush_all, 1)
        await ctx.tick()
        ctx.set(dut.flush_all, 0)
        assert ctx.get(dut.lookup_hit) == 0

    sim.add_testbench(process)
    sim.run()


def test_tlb_flush_generations_do_not_clear_entries_broadcast(shared_tlb_factory) -> None:
    dut = shared_tlb_factory(entries=8)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def process(ctx):
        ctx.set(dut.fill_valid, 1)
        ctx.set(dut.fill_vpage, 0x0000_0000_0000_2)
        ctx.set(dut.fill_ppage, 0x0000_0000_0002_02)
        ctx.set(dut.fill_perm_read, 1)
        await ctx.tick()

        ctx.set(dut.fill_valid, 0)
        ctx.set(dut.lookup_vaddr, 0x0000_0000_0000_2456)
        assert ctx.get(dut.lookup_hit) == 1
        assert ctx.get(dut.lookup_paddr) == 0x0000_0000_0020_2456

        ctx.set(dut.flush_all, 1)
        await ctx.tick()
        ctx.set(dut.flush_all, 0)
        assert ctx.get(dut.lookup_hit) == 0

        ctx.set(dut.fill_valid, 1)
        ctx.set(dut.fill_vpage, 0x0000_0000_0000_2)
        ctx.set(dut.fill_ppage, 0x0000_0000_0003_02)
        await ctx.tick()

        ctx.set(dut.fill_valid, 0)
        assert ctx.get(dut.lookup_hit) == 1
        assert ctx.get(dut.lookup_paddr) == 0x0000_0000_0030_2456

        ctx.set(dut.flush_all, 1)
        await ctx.tick()
        ctx.set(dut.flush_all, 0)
        assert ctx.get(dut.lookup_hit) == 0

    sim.add_testbench(process)
    sim.run()


def test_tlb_generation_wrap_clears_stale_entries(shared_tlb_factory) -> None:
    dut = shared_tlb_factory(entries=8, generation_bits=2)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def process(ctx):
        ctx.set(dut.fill_valid, 1)
        ctx.set(dut.fill_vpage, 0x0000_0000_0000_3)
        ctx.set(dut.fill_ppage, 0x0000_0000_0004_03)
        ctx.set(dut.fill_perm_read, 1)
        await ctx.tick()

        ctx.set(dut.fill_valid, 0)
        ctx.set(dut.lookup_vaddr, 0x0000_0000_0000_3567)
        assert ctx.get(dut.lookup_hit) == 1

        for _ in range(4):
            ctx.set(dut.flush_all, 1)
            await ctx.tick()
            ctx.set(dut.flush_all, 0)
            assert ctx.get(dut.lookup_hit) == 0

    sim.add_testbench(process)
    sim.run()
