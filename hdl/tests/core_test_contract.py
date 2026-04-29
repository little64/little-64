from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from little64_cores.basic.core import CoreState
from little64_cores.basic.special_registers import Little64BasicSpecialRegisterFile
from little64_cores.basic.tlb import Little64BasicTLB
from little64_cores.config import Little64CoreConfig, SUPPORTED_CORE_VARIANTS
from little64_cores.mmu import ACCESS_EXECUTE
from little64_cores.v2 import Little64V2SpecialRegisterFile, Little64V2TLB, V2PipelineState
from little64_cores.v3 import Little64V3SpecialRegisterFile, Little64V3TLB, V3PipelineState
from little64_cores.v4 import Little64V4Core
from little64_cores.variants import create_core


TLBFactory = Callable[..., object]
SpecialRegisterFileFactory = Callable[[Little64CoreConfig], object]


@dataclass(frozen=True, slots=True)
class CoreTestAdapter:
    variant: str
    capabilities: frozenset[str]
    special_register_file_factory: SpecialRegisterFileFactory
    tlb_factory: TLBFactory

    def create_core(self, config: Little64CoreConfig):
        return create_core(config)

    def create_special_register_file(self, config: Little64CoreConfig):
        return self.special_register_file_factory(config)

    def create_tlb(self, **kwargs):
        return self.tlb_factory(**kwargs)

    def seed_runtime_state(
        self,
        ctx,
        dut,
        config: Little64CoreConfig,
        *,
        initial_registers: dict[int, int] | None = None,
        initial_flags: int = 0,
        initial_special_registers: dict[str, int] | None = None,
    ) -> None:
        seeded_special_registers = initial_special_registers or {}
        initial_pc = (initial_registers or {}).get(15, config.reset_vector)

        if initial_registers:
            for index, value in initial_registers.items():
                ctx.set(dut.register_file[index], value)

        ctx.set(dut.register_file[15], initial_pc)
        ctx.set(dut.flags, initial_flags)
        if initial_special_registers:
            for name, value in initial_special_registers.items():
                ctx.set(getattr(dut.special_regs, name), value)

        ctx.set(dut.locked_up, 0)
        ctx.set(dut.irq_lines, 0)

        for trap_field in ('trap_cause', 'trap_fault_addr', 'trap_access', 'trap_pc', 'trap_aux'):
            if trap_field not in seeded_special_registers:
                ctx.set(getattr(dut.special_regs, trap_field), 0)

        if hasattr(dut, 'fetch_pc'):
            ctx.set(dut.fetch_pc, initial_pc)
        if hasattr(dut, 'fetch_phys_addr'):
            ctx.set(dut.fetch_phys_addr, initial_pc)
        if hasattr(dut, 'current_instruction'):
            ctx.set(dut.current_instruction, 0)
        if hasattr(dut, 'execute_instruction'):
            ctx.set(dut.execute_instruction, 0)
        if hasattr(dut, 'translate_virtual_addr'):
            ctx.set(dut.translate_virtual_addr, initial_pc)
        if hasattr(dut, 'translate_access'):
            ctx.set(dut.translate_access, ACCESS_EXECUTE)

        if self.variant == 'basic':
            ctx.set(dut.halted, 0)
            ctx.set(dut.state, CoreState.FETCH_TRANSLATE)
            return

        ctx.set(dut.frontend.line_valid, 0)
        if self.variant == 'v2':
            ctx.set(dut.state, V2PipelineState.FETCH_TRANSLATE)
            return

        ctx.set(dut.halted, 0)
        if hasattr(dut, 'execute_operand_a'):
            ctx.set(dut.execute_operand_a, 0)
        if hasattr(dut, 'execute_operand_b'):
            ctx.set(dut.execute_operand_b, 0)
        if hasattr(dut, 'execute_flags'):
            ctx.set(dut.execute_flags, 0)
        if self.variant == 'v4':
            # V4 has no pipeline-state enum; only valid bits drive the pipeline.
            return
        ctx.set(dut.state, V3PipelineState.FETCH)

    async def prepare_for_execution(
        self,
        ctx,
        dut,
        config: Little64CoreConfig,
        *,
        ready: dict[str, bool],
        initial_registers: dict[int, int] | None = None,
        initial_flags: int = 0,
        initial_special_registers: dict[str, int] | None = None,
    ) -> None:
        await ctx.tick()
        self.seed_runtime_state(
            ctx,
            dut,
            config,
            initial_registers=initial_registers,
            initial_flags=initial_flags,
            initial_special_registers=initial_special_registers,
        )

        await ctx.tick()
        if self.variant not in ('v3', 'v4'):
            self.seed_runtime_state(
                ctx,
                dut,
                config,
                initial_registers=initial_registers,
                initial_flags=initial_flags,
                initial_special_registers=initial_special_registers,
            )
        ready['value'] = True


CORE_TEST_CAPABILITIES = {
    'basic': frozenset({
        'commit-profile',
        'interrupts',
        'mmu',
        'reset',
        'shared-architecture',
        'special-register-file',
        'tlb',
        'unaligned',
    }),
    'v2': frozenset({
        'atomics',
        'cache-topology',
        'commit-profile',
        'interrupts',
        'litex',
        'mmio-trace',
        'mmu',
        'pipelined',
        'reset',
        'shared-architecture',
        'special-register-file',
        'tlb',
        'unaligned',
    }),
    'v3': frozenset({
        'atomics',
        'cache-topology',
        'commit-profile',
        'interrupts',
        'litex',
        'mmio-trace',
        'mmu',
        'pipelined',
        'reset',
        'shared-architecture',
        'special-register-file',
        'tlb',
        'unaligned',
    }),
    'v4': frozenset({
        'atomics',
        'cache-topology',
        'commit-profile',
        'interrupts',
        'litex',
        'mmio-trace',
        'mmu',
        'pipelined',
        'reset',
        'shared-architecture',
        'special-register-file',
        'tlb',
        'unaligned',
    }),
}


CORE_TEST_ADAPTERS = {
    'basic': CoreTestAdapter(
        variant='basic',
        capabilities=CORE_TEST_CAPABILITIES['basic'],
        special_register_file_factory=Little64BasicSpecialRegisterFile,
        tlb_factory=Little64BasicTLB,
    ),
    'v2': CoreTestAdapter(
        variant='v2',
        capabilities=CORE_TEST_CAPABILITIES['v2'],
        special_register_file_factory=Little64V2SpecialRegisterFile,
        tlb_factory=Little64V2TLB,
    ),
    'v3': CoreTestAdapter(
        variant='v3',
        capabilities=CORE_TEST_CAPABILITIES['v3'],
        special_register_file_factory=Little64V3SpecialRegisterFile,
        tlb_factory=Little64V3TLB,
    ),
    'v4': CoreTestAdapter(
        variant='v4',
        capabilities=CORE_TEST_CAPABILITIES['v4'],
        # V4 reuses V3's special-register and TLB implementations.
        special_register_file_factory=Little64V3SpecialRegisterFile,
        tlb_factory=Little64V3TLB,
    ),
}


def adapter_for_variant(core_variant: str) -> CoreTestAdapter:
    try:
        return CORE_TEST_ADAPTERS[core_variant]
    except KeyError as exc:
        raise ValueError(
            f'Unsupported core variant for the HDL test contract: {core_variant}; expected one of {SUPPORTED_CORE_VARIANTS}'
        ) from exc


def variants_with_capabilities(variants: list[str], required_capabilities: set[str]) -> list[str]:
    if not required_capabilities:
        return variants
    return [variant for variant in variants if required_capabilities <= CORE_TEST_CAPABILITIES[variant]]


__all__ = [
    'CORE_TEST_ADAPTERS',
    'CORE_TEST_CAPABILITIES',
    'CoreTestAdapter',
    'adapter_for_variant',
    'variants_with_capabilities',
]