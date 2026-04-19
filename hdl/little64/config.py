from __future__ import annotations

from dataclasses import dataclass


CORE_VARIANTS = ('basic', 'v2')
EXPERIMENTAL_CORE_VARIANTS = ('v3',)
SUPPORTED_CORE_VARIANTS = CORE_VARIANTS + EXPERIMENTAL_CORE_VARIANTS
CACHE_TOPOLOGIES = ('none', 'unified', 'split')


@dataclass(frozen=True, slots=True)
class Little64CoreConfig:
    instruction_bus_width: int = 64
    data_bus_width: int = 64
    address_width: int = 64
    core_variant: str = 'v2'
    cache_topology: str = 'none'
    enable_mmu: bool = True
    enable_tlb: bool = True
    tlb_entries: int = 64
    optional_platform_registers: bool = False
    irq_input_count: int = 63
    reset_vector: int = 0

    def __post_init__(self) -> None:
        if self.instruction_bus_width != 64:
            raise ValueError('Little64CoreConfig requires a 64-bit instruction bus')
        if self.data_bus_width != 64:
            raise ValueError('Little64CoreConfig requires a 64-bit data bus')
        if self.address_width < 39:
            raise ValueError('Little64CoreConfig address width must cover canonical 39-bit VA space')
        if self.core_variant not in SUPPORTED_CORE_VARIANTS:
            raise ValueError(f'Little64CoreConfig core_variant must be one of {SUPPORTED_CORE_VARIANTS}')
        if self.cache_topology not in CACHE_TOPOLOGIES:
            raise ValueError(f'Little64CoreConfig cache_topology must be one of {CACHE_TOPOLOGIES}')
        if self.core_variant == 'basic' and self.cache_topology != 'none':
            raise ValueError('Little64CoreConfig basic core only supports cache_topology="none"')
        if self.irq_input_count < 1 or self.irq_input_count > 63:
            raise ValueError('Little64CoreConfig irq_input_count must be in the range 1..63')
        if self.enable_tlb:
            if self.tlb_entries < 2:
                raise ValueError('Little64CoreConfig requires at least 2 TLB entries when TLB is enabled')
            if self.tlb_entries & (self.tlb_entries - 1):
                raise ValueError('Little64CoreConfig tlb_entries must be a power of two')
        elif self.tlb_entries != 0:
            raise ValueError('Little64CoreConfig tlb_entries must be 0 when TLB is disabled')
        if self.reset_vector & 0x1:
            raise ValueError('Little64CoreConfig reset_vector must be 16-bit aligned')

    @property
    def first_irq_vector(self) -> int:
        return 65

    @property
    def last_irq_vector(self) -> int:
        return self.first_irq_vector + self.irq_input_count - 1
