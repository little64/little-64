from __future__ import annotations

from dataclasses import dataclass

from amaranth import Elaboratable, Module

from .config import Little64CoreConfig
from .core import Little64Core


@dataclass(frozen=True, slots=True)
class Little64LiteXProfile:
    name: str = 'little64'
    family: str = 'little64'
    endianness: str = 'little'
    data_width: int = 64
    instruction_width: int = 64


class Little64LiteXShim(Elaboratable):
    def __init__(self, config: Little64CoreConfig | None = None) -> None:
        self.config = config or Little64CoreConfig()
        self.profile = Little64LiteXProfile(
            data_width=self.config.data_bus_width,
            instruction_width=self.config.instruction_bus_width,
        )
        self.core = Little64Core(self.config)

        self.ibus = self.core.i_bus
        self.dbus = self.core.d_bus
        self.irq_lines = self.core.irq_lines
        self.halted = self.core.halted
        self.locked_up = self.core.locked_up

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = self.core
        return m
