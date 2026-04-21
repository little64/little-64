from __future__ import annotations

from math import log2

from amaranth import Array, Const, Elaboratable, Module, Mux, Signal


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

        generation_max = (1 << self.generation_bits) - 1
        current_generation = Signal(self.generation_bits, name='tlb_generation')
        valid_bits = [Signal(name=f'tlb_valid_{idx}') for idx in range(self.entries)]
        generations = [Signal(self.generation_bits, name=f'tlb_gen_{idx}', reset_less=True) for idx in range(self.entries)]
        virtual_tags = [Signal(self.page_number_width, name=f'tlb_tag_{idx}', reset_less=True) for idx in range(self.entries)]
        physical_pages = [Signal(self.page_number_width, name=f'tlb_ppn_{idx}', reset_less=True) for idx in range(self.entries)]
        perm_read = [Signal(name=f'tlb_perm_r_{idx}', reset_less=True) for idx in range(self.entries)]
        perm_write = [Signal(name=f'tlb_perm_w_{idx}', reset_less=True) for idx in range(self.entries)]
        perm_execute = [Signal(name=f'tlb_perm_x_{idx}', reset_less=True) for idx in range(self.entries)]
        perm_user = [Signal(name=f'tlb_perm_u_{idx}', reset_less=True) for idx in range(self.entries)]

        lookup_vpage = self.lookup_vaddr[self.page_offset_bits:]
        lookup_index = lookup_vpage[:self.index_bits]
        lookup_offset = self.lookup_vaddr[:self.page_offset_bits]

        valid_array = Array(valid_bits)
        generation_array = Array(generations)
        virtual_tag_array = Array(virtual_tags)
        physical_page_array = Array(physical_pages)
        perm_read_array = Array(perm_read)
        perm_write_array = Array(perm_write)
        perm_execute_array = Array(perm_execute)
        perm_user_array = Array(perm_user)

        indexed_valid = valid_array[lookup_index]
        indexed_generation = generation_array[lookup_index]
        indexed_tag = virtual_tag_array[lookup_index]
        indexed_page = physical_page_array[lookup_index]
        indexed_perm_read = perm_read_array[lookup_index]
        indexed_perm_write = perm_write_array[lookup_index]
        indexed_perm_execute = perm_execute_array[lookup_index]
        indexed_perm_user = perm_user_array[lookup_index]

        m.d.comb += [
            self.lookup_hit.eq(indexed_valid & (indexed_generation == current_generation) & (indexed_tag == lookup_vpage)),
            self.lookup_paddr.eq((indexed_page << self.page_offset_bits) | lookup_offset),
            self.lookup_perm_read.eq(indexed_perm_read),
            self.lookup_perm_write.eq(indexed_perm_write),
            self.lookup_perm_execute.eq(indexed_perm_execute),
            self.lookup_perm_user.eq(indexed_perm_user),
        ]

        with m.If(self.flush_all):
            with m.If(current_generation == Const(generation_max, self.generation_bits)):
                m.d.sync += [current_generation.eq(0), *(valid_bit.eq(0) for valid_bit in valid_bits)]
            with m.Else():
                m.d.sync += current_generation.eq(current_generation + 1)
        with m.Elif(self.fill_valid):
            fill_index = self.fill_vpage[:self.index_bits]

            m.d.sync += [
                valid_array[fill_index].eq(1),
                generation_array[fill_index].eq(current_generation),
                virtual_tag_array[fill_index].eq(self.fill_vpage),
                physical_page_array[fill_index].eq(self.fill_ppage),
                perm_read_array[fill_index].eq(self.fill_perm_read),
                perm_write_array[fill_index].eq(self.fill_perm_write),
                perm_execute_array[fill_index].eq(self.fill_perm_execute),
                perm_user_array[fill_index].eq(self.fill_perm_user),
            ]

        return m
