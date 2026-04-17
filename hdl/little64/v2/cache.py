from __future__ import annotations

from math import log2

from amaranth import Array, Cat, Const, Elaboratable, Module, Mux, Signal


class Little64V2LineCache(Elaboratable):
    def __init__(self, *, entries: int = 4, address_width: int = 64, data_width: int = 64) -> None:
        if entries < 1 or entries & (entries - 1):
            raise ValueError('Little64V2LineCache entries must be a power of two and at least 1')
        if data_width != 64:
            raise ValueError('Little64V2LineCache currently expects 64-bit cache lines')

        self.entries = entries
        self.address_width = address_width
        self.data_width = data_width
        self.index_bits = 0 if entries == 1 else int(log2(entries))
        self.line_offset_bits = 3
        self.line_number_width = address_width - self.line_offset_bits

        self.lookup_addr = Signal(address_width)
        self.lookup_hit = Signal()
        self.lookup_data = Signal(data_width)

        self.fill_valid = Signal()
        self.fill_addr = Signal(address_width)
        self.fill_data = Signal(data_width)

        self.flush_all = Signal()

        self.invalidate_valid = Signal()
        self.invalidate_addr = Signal(address_width)

        self.store_update_valid = Signal()
        self.store_update_addr = Signal(address_width)
        self.store_update_sel = Signal(data_width // 8)
        self.store_update_data = Signal(data_width)

    def elaborate(self, platform):
        m = Module()

        valid_bits = [Signal(name=f'cache_valid_{index}') for index in range(self.entries)]
        tags = [Signal(self.line_number_width, name=f'cache_tag_{index}') for index in range(self.entries)]
        line_data = [Signal(self.data_width, name=f'cache_line_{index}') for index in range(self.entries)]

        lookup_line = self.lookup_addr[self.line_offset_bits:]
        lookup_index = Const(0, 1) if self.index_bits == 0 else lookup_line[:self.index_bits]
        lookup_tag = lookup_line

        indexed_valid = Array(valid_bits)[lookup_index]
        indexed_tag = Array(tags)[lookup_index]
        indexed_data = Array(line_data)[lookup_index]

        m.d.comb += [
            self.lookup_hit.eq(indexed_valid & (indexed_tag == lookup_tag)),
            self.lookup_data.eq(indexed_data),
        ]

        with m.If(self.flush_all):
            for valid_bit in valid_bits:
                m.d.sync += valid_bit.eq(0)
        with m.Elif(self.invalidate_valid):
            invalidate_line = self.invalidate_addr[self.line_offset_bits:]
            invalidate_index = Const(0, 1) if self.index_bits == 0 else invalidate_line[:self.index_bits]
            invalidate_tag = invalidate_line
            with m.Switch(invalidate_index):
                for index in range(self.entries):
                    with m.Case(index):
                        with m.If(valid_bits[index] & (tags[index] == invalidate_tag)):
                            m.d.sync += valid_bits[index].eq(0)
        with m.Elif(self.store_update_valid):
            update_line = self.store_update_addr[self.line_offset_bits:]
            update_index = Const(0, 1) if self.index_bits == 0 else update_line[:self.index_bits]
            update_tag = update_line
            with m.Switch(update_index):
                for index in range(self.entries):
                    with m.Case(index):
                        with m.If(valid_bits[index] & (tags[index] == update_tag)):
                            m.d.sync += line_data[index].eq(Cat(*[
                                Mux(
                                    self.store_update_sel[byte_index],
                                    self.store_update_data[byte_index * 8:(byte_index + 1) * 8],
                                    line_data[index][byte_index * 8:(byte_index + 1) * 8],
                                )
                                for byte_index in range(self.data_width // 8)
                            ]))
        with m.Elif(self.fill_valid):
            fill_line = self.fill_addr[self.line_offset_bits:]
            fill_index = Const(0, 1) if self.index_bits == 0 else fill_line[:self.index_bits]
            fill_tag = fill_line
            with m.Switch(fill_index):
                for index in range(self.entries):
                    with m.Case(index):
                        m.d.sync += [
                            valid_bits[index].eq(1),
                            tags[index].eq(fill_tag),
                            line_data[index].eq(self.fill_data),
                        ]

        return m


__all__ = ['Little64V2LineCache']