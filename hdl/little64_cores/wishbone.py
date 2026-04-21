from __future__ import annotations

from amaranth import Signal


class WishboneMasterInterface:
    def __init__(self, *, data_width: int = 64, address_width: int = 64, name: str) -> None:
        if data_width % 8:
            raise ValueError('WishboneMasterInterface data width must be byte aligned')
        self.data_width = data_width
        self.address_width = address_width
        self.sel_width = data_width // 8

        self.adr = Signal(address_width, name=f'{name}_adr')
        self.dat_w = Signal(data_width, name=f'{name}_dat_w')
        self.dat_r = Signal(data_width, name=f'{name}_dat_r')
        self.sel = Signal(self.sel_width, name=f'{name}_sel')
        self.cyc = Signal(name=f'{name}_cyc')
        self.stb = Signal(name=f'{name}_stb')
        self.we = Signal(name=f'{name}_we')
        self.ack = Signal(name=f'{name}_ack')
        self.err = Signal(name=f'{name}_err')
        self.cti = Signal(3, name=f'{name}_cti')
        self.bte = Signal(2, name=f'{name}_bte')
