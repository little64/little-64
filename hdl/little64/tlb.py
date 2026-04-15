from __future__ import annotations

from math import log2

from amaranth import Array, Const, Elaboratable, Module, Mux, Signal


class Little64TLB(Elaboratable):
    def __init__(self, *, entries: int = 64, address_width: int = 64) -> None:
        if entries < 2 or entries & (entries - 1):
            raise ValueError('Little64TLB entries must be a power of two and at least 2')

        self.entries = entries
        self.address_width = address_width
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
        self.fill_vaddr = Signal(address_width)
        self.fill_paddr = Signal(address_width)
        self.fill_perm_read = Signal()
        self.fill_perm_write = Signal()
        self.fill_perm_execute = Signal()
        self.fill_perm_user = Signal()

        self.flush_all = Signal()

    def elaborate(self, platform):
        m = Module()

        valid_bits = [Signal(name=f'tlb_valid_{idx}') for idx in range(self.entries)]
        virtual_tags = [Signal(self.page_number_width, name=f'tlb_tag_{idx}') for idx in range(self.entries)]
        physical_pages = [Signal(self.page_number_width, name=f'tlb_ppn_{idx}') for idx in range(self.entries)]
        perm_read = [Signal(name=f'tlb_perm_r_{idx}') for idx in range(self.entries)]
        perm_write = [Signal(name=f'tlb_perm_w_{idx}') for idx in range(self.entries)]
        perm_execute = [Signal(name=f'tlb_perm_x_{idx}') for idx in range(self.entries)]
        perm_user = [Signal(name=f'tlb_perm_u_{idx}') for idx in range(self.entries)]

        lookup_vpage = self.lookup_vaddr[self.page_offset_bits:]
        lookup_index = lookup_vpage[:self.index_bits]
        lookup_offset = self.lookup_vaddr[:self.page_offset_bits]

        indexed_valid = Array(valid_bits)[lookup_index]
        indexed_tag = Array(virtual_tags)[lookup_index]
        indexed_page = Array(physical_pages)[lookup_index]
        indexed_perm_read = Array(perm_read)[lookup_index]
        indexed_perm_write = Array(perm_write)[lookup_index]
        indexed_perm_execute = Array(perm_execute)[lookup_index]
        indexed_perm_user = Array(perm_user)[lookup_index]

        m.d.comb += [
            self.lookup_hit.eq(indexed_valid & (indexed_tag == lookup_vpage)),
            self.lookup_paddr.eq((indexed_page << self.page_offset_bits) | lookup_offset),
            self.lookup_perm_read.eq(indexed_perm_read),
            self.lookup_perm_write.eq(indexed_perm_write),
            self.lookup_perm_execute.eq(indexed_perm_execute),
            self.lookup_perm_user.eq(indexed_perm_user),
        ]

        with m.If(self.flush_all):
            for valid_bit in valid_bits:
                m.d.sync += valid_bit.eq(0)
        with m.Elif(self.fill_valid):
            fill_vpage = self.fill_vaddr[self.page_offset_bits:]
            fill_index = fill_vpage[:self.index_bits]
            fill_ppage = self.fill_paddr[self.page_offset_bits:]

            with m.Switch(fill_index):
                for idx in range(self.entries):
                    with m.Case(idx):
                        m.d.sync += [
                            valid_bits[idx].eq(1),
                            virtual_tags[idx].eq(fill_vpage),
                            physical_pages[idx].eq(fill_ppage),
                            perm_read[idx].eq(self.fill_perm_read),
                            perm_write[idx].eq(self.fill_perm_write),
                            perm_execute[idx].eq(self.fill_perm_execute),
                            perm_user[idx].eq(self.fill_perm_user),
                        ]

        return m
