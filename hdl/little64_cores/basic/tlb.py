from __future__ import annotations

from math import log2

from amaranth import Array, Cat, Const, Elaboratable, Memory, Module, Mux, Signal


class Little64BasicTLB(Elaboratable):
    def __init__(self, *, entries: int = 64, address_width: int = 64, generation_bits: int = 8) -> None:
        if entries < 2 or entries & (entries - 1):
            raise ValueError('Little64BasicTLB entries must be a power of two and at least 2')
        if generation_bits < 1:
            raise ValueError('Little64BasicTLB generation_bits must be at least 1')

        self.entries = entries
        self.address_width = address_width
        self.generation_bits = generation_bits
        self.page_offset_bits = 12
        self.page_number_width = address_width - self.page_offset_bits
        self.index_bits = int(log2(entries))

        self.lookup_vaddr = Signal(address_width)
        self.lookup_hit = Signal()
        self.lookup_paddr = Signal(address_width)
        self.lookup_perm_read = Signal()
        self.lookup_perm_write = Signal()
        self.lookup_perm_execute = Signal()
        self.lookup_perm_user = Signal()

        self.fill_valid = Signal()
        self.fill_vpage = Signal(self.page_number_width)
        self.fill_ppage = Signal(self.page_number_width)
        self.fill_perm_read = Signal()
        self.fill_perm_write = Signal()
        self.fill_perm_execute = Signal()
        self.fill_perm_user = Signal()

        self.flush_all = Signal()

    def elaborate(self, platform):
        m = Module()

        # Pack all reset_less entry data into an inferred distributed RAM.
        # Word layout (LSB first via Cat): generation | vtag | ppage | perm_r | perm_w | perm_x | perm_u
        g = self.generation_bits
        p = self.page_number_width
        entry_mem = Memory(width=g + 2 * p + 4, depth=self.entries, name='tlb_entry_mem')
        m.submodules.entry_rp = entry_rp = entry_mem.read_port(domain='comb')
        m.submodules.entry_wp = entry_wp = entry_mem.write_port()

        generation_max = (1 << self.generation_bits) - 1
        current_generation = Signal(self.generation_bits, name='tlb_generation')
        valid_bits = [Signal(name=f'tlb_valid_{idx}') for idx in range(self.entries)]
        valid_array = Array(valid_bits)

        lookup_vpage = self.lookup_vaddr[self.page_offset_bits:]
        lookup_index = lookup_vpage[:self.index_bits]
        lookup_offset = self.lookup_vaddr[:self.page_offset_bits]

        # Unpack fields from the read port data word
        read_generation  = entry_rp.data[:g]
        read_vtag        = entry_rp.data[g:g + p]
        read_ppage       = entry_rp.data[g + p:g + 2 * p]
        read_perm_read   = entry_rp.data[g + 2 * p]
        read_perm_write  = entry_rp.data[g + 2 * p + 1]
        read_perm_execute = entry_rp.data[g + 2 * p + 2]
        read_perm_user   = entry_rp.data[g + 2 * p + 3]

        m.d.comb += [
            entry_rp.addr.eq(lookup_index),
            self.lookup_hit.eq(
                valid_array[lookup_index] &
                (read_generation == current_generation) &
                (read_vtag == lookup_vpage)
            ),
            self.lookup_paddr.eq((read_ppage << self.page_offset_bits) | lookup_offset),
            self.lookup_perm_read.eq(read_perm_read),
            self.lookup_perm_write.eq(read_perm_write),
            self.lookup_perm_execute.eq(read_perm_execute),
            self.lookup_perm_user.eq(read_perm_user),
        ]

        with m.If(self.flush_all):
            with m.If(current_generation == Const(generation_max, self.generation_bits)):
                m.d.sync += [current_generation.eq(0), *(bit.eq(0) for bit in valid_bits)]
            with m.Else():
                m.d.sync += current_generation.eq(current_generation + 1)
        with m.Elif(self.fill_valid):
            fill_index = self.fill_vpage[:self.index_bits]
            m.d.comb += [
                entry_wp.en.eq(1),
                entry_wp.addr.eq(fill_index),
                entry_wp.data.eq(Cat(
                    current_generation,
                    self.fill_vpage,
                    self.fill_ppage,
                    self.fill_perm_read,
                    self.fill_perm_write,
                    self.fill_perm_execute,
                    self.fill_perm_user,
                )),
            ]
            m.d.sync += valid_array[fill_index].eq(1)

        return m
