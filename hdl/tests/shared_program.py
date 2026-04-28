from __future__ import annotations

import ast
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from amaranth import Elaboratable, Module, ResetInserter, Signal
from amaranth.sim import Simulator

from little64_cores.config import Little64CoreConfig

from core_test_contract import adapter_for_variant


REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_CASE_DIR = REPO_ROOT / 'tests' / 'shared'

GP_OPCODE = {
    'ADD': 0,
    'SUB': 1,
    'TEST': 2,
    'LLR': 3,
    'SCR': 4,
    'AND': 16,
    'OR': 17,
    'XOR': 18,
    'SLL': 20,
    'SRL': 21,
    'SRA': 22,
    'SLLI': 23,
    'SRLI': 24,
    'SRAI': 25,
    'SYSCALL': 27,
    'LSR': 28,
    'SSR': 29,
    'IRET': 30,
    'STOP': 31,
}


LS_OPCODE = {
    'LOAD': 0,
    'STORE': 1,
    'PUSH': 2,
    'POP': 3,
    'MOVE': 4,
    'BYTE_LOAD': 5,
    'BYTE_STORE': 6,
    'SHORT_LOAD': 7,
    'SHORT_STORE': 8,
    'WORD_LOAD': 9,
    'WORD_STORE': 10,
    'JUMP.Z': 11,
    'JUMP.C': 12,
    'JUMP.S': 13,
    'JUMP.GT': 14,
    'JUMP.LT': 15,
}


@dataclass(frozen=True, slots=True)
class ProgramRegsCase:
    description: str
    source: str
    reg_a: int
    value_a: int
    reg_b: int
    value_b: int
    reg_c: int
    value_c: int


@dataclass(frozen=True, slots=True)
class GpTwoRegCase:
    opcode_name: str
    rs1: int
    rs1_value: int
    rd: int
    rd_value: int
    expected_rd: int
    expected_flags: int
    description: str


@dataclass(frozen=True, slots=True)
class GpImmCase:
    opcode_name: str
    imm4: int
    rd: int
    initial: int
    expected_rd: int
    expected_flags: int
    description: str


@dataclass(frozen=True, slots=True)
class LdiCase:
    shift: int
    imm8: int
    rd: int
    initial: int
    expected_rd: int
    initial_flags: int
    expected_flags: int
    description: str


@dataclass(slots=True)
class ProgramExecution:
    words: list[int]
    initial_registers: dict[int, int] | None = None
    initial_flags: int = 0
    initial_special_registers: dict[str, int] | None = None
    extra_code_words: dict[int, int] | None = None
    initial_data_memory: dict[int, int] | None = None
    irq_schedule: dict[int, int] | None = None
    max_cycles: int = 256


class _ResettableCore(Elaboratable):
    def __init__(self, core) -> None:
        self._core = core
        self.test_reset = Signal()

    def __getattr__(self, name: str):
        return getattr(self._core, name)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = ResetInserter(self.test_reset)(self._core)
        return m


def _load_macro_args(path: Path, macro_name: str) -> list[tuple[Any, ...]]:
    pattern = re.compile(rf'^{re.escape(macro_name)}\((.*)\)$')
    rows: list[tuple[Any, ...]] = []
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('//'):
            continue
        match = pattern.match(line)
        if not match:
            continue
        rows.append(ast.literal_eval(f'({match.group(1)})'))
    return rows


def load_jump_program_cases() -> list[ProgramRegsCase]:
    return [ProgramRegsCase(*row) for row in _load_macro_args(SHARED_CASE_DIR / 'jump_program_cases.def', 'LITTLE64_PROGRAM_REGS_CASE')]


def load_memory_program_cases() -> list[ProgramRegsCase]:
    return [ProgramRegsCase(*row) for row in _load_macro_args(SHARED_CASE_DIR / 'memory_program_cases.def', 'LITTLE64_PROGRAM_REGS_CASE')]


def load_gp_two_reg_cases() -> list[GpTwoRegCase]:
    return [GpTwoRegCase(*row) for row in _load_macro_args(SHARED_CASE_DIR / 'gp_alu_cases.def', 'LITTLE64_GP_TWO_REG_CASE')]


def load_gp_imm_cases() -> list[GpImmCase]:
    return [GpImmCase(*row) for row in _load_macro_args(SHARED_CASE_DIR / 'gp_alu_cases.def', 'LITTLE64_GP_IMM_CASE')]


def load_ldi_cases() -> list[LdiCase]:
    return [LdiCase(*row) for row in _load_macro_args(SHARED_CASE_DIR / 'ldi_cases.def', 'LITTLE64_LDI_CASE')]


def encode_gp_rr(opcode_name: str, rs1: int, rd: int) -> int:
    return (0b110 << 13) | (GP_OPCODE[opcode_name] << 8) | ((rs1 & 0xF) << 4) | (rd & 0xF)


def encode_gp_imm(opcode_name: str, imm4: int, rd: int) -> int:
    return (0b110 << 13) | (GP_OPCODE[opcode_name] << 8) | ((imm4 & 0xF) << 4) | (rd & 0xF)


def encode_ldi(shift: int, imm8: int, rd: int) -> int:
    return (0b10 << 14) | ((shift & 0x3) << 12) | ((imm8 & 0xFF) << 4) | (rd & 0xF)


def encode_ls_reg(opcode_name: str, offset2: int, rs1: int, rd: int) -> int:
    return ((LS_OPCODE[opcode_name] & 0xF) << 10) | ((offset2 & 0x3) << 8) | ((rs1 & 0xF) << 4) | (rd & 0xF)


def encode_ls_pc(opcode_name: str, offset_words: int, rd: int) -> int:
    return (0b01 << 14) | ((LS_OPCODE[opcode_name] & 0xF) << 10) | ((offset_words & 0x3F) << 4) | (rd & 0xF)


def encode_ls_pc_jump(opcode_name: str, offset_words: int) -> int:
    return (0b01 << 14) | ((LS_OPCODE[opcode_name] & 0xF) << 10) | (offset_words & 0x3FF)


def encode_ujump(offset_words: int) -> int:
    return (0b111 << 13) | (offset_words & 0x1FFF)


def _parse_int(text: str) -> int:
    return int(text, 0)


def _resolve_pcrel_operand(text: str, labels: dict[str, int], instruction_index: int) -> int:
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', text):
        return labels[text] - (instruction_index + 1)
    return _parse_int(text)


def assemble_source(source: str) -> list[int]:
    lines: list[str] = []
    labels: dict[str, int] = {}

    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith(':'):
            labels[line[:-1]] = len(lines)
            continue
        lines.append(line)

    words: list[int] = []
    for index, line in enumerate(lines):
        if match := re.fullmatch(r'LDI(?:\.S([123]))?\s+#?([^,\s]+),\s*R(\d+)', line):
            shift = int(match.group(1) or '0')
            imm8 = _parse_int(match.group(2)) & 0xFF
            rd = int(match.group(3))
            words.append(encode_ldi(shift, imm8, rd))
            continue

        if match := re.fullmatch(r'(ADD|SUB|TEST|AND|OR|XOR|SLL|SRL|SRA|LLR|SCR|LSR|SSR)\s+R(\d+),\s*R(\d+)', line):
            words.append(encode_gp_rr(match.group(1), int(match.group(2)), int(match.group(3))))
            continue

        if match := re.fullmatch(r'(SLLI|SRLI|SRAI)\s+#?(\d+),\s*R(\d+)', line):
            words.append(encode_gp_imm(match.group(1), int(match.group(2)), int(match.group(3))))
            continue

        if line == 'SYSCALL':
            words.append(encode_gp_imm('SYSCALL', 0, 0))
            continue

        if line == 'IRET':
            words.append(encode_gp_imm('IRET', 0, 0))
            continue

        if line == 'STOP':
            words.append(encode_gp_imm('STOP', 0, 0))
            continue

        if match := re.fullmatch(r'JUMP\s+@([A-Za-z_][A-Za-z0-9_]*)', line):
            target = labels[match.group(1)]
            offset = target - (index + 1)
            words.append(encode_ujump(offset))
            continue

        if match := re.fullmatch(r'(JUMP\.Z|JUMP\.C|JUMP\.S|JUMP\.GT|JUMP\.LT)\s+@([A-Za-z_][A-Za-z0-9_]*)', line):
            target = labels[match.group(2)]
            offset = target - (index + 1)
            words.append(encode_ls_pc_jump(match.group(1), offset))
            continue

        if match := re.fullmatch(r'(LOAD|STORE|BYTE_LOAD|BYTE_STORE|SHORT_LOAD|SHORT_STORE|WORD_LOAD|WORD_STORE|MOVE|PUSH|POP)\s+@([^,\s]+),\s*R(\d+)', line):
            offset = _resolve_pcrel_operand(match.group(2), labels, index)
            rd = int(match.group(3))
            words.append(encode_ls_pc(match.group(1), offset, rd))
            continue

        if match := re.fullmatch(r'(LOAD|STORE|BYTE_LOAD|BYTE_STORE|SHORT_LOAD|SHORT_STORE|WORD_LOAD|WORD_STORE)\s+\[R(\d+)(?:\+(\d+))?\],\s*R(\d+)', line):
            opcode = match.group(1)
            rs1 = int(match.group(2))
            offset = int(match.group(3) or '0')
            rd = int(match.group(4))
            words.append(encode_ls_reg(opcode, offset // 2, rs1, rd))
            continue

        if match := re.fullmatch(r'PUSH\s+R(\d+),\s*R(\d+)', line):
            rs1 = int(match.group(1))
            rd = int(match.group(2))
            words.append(encode_ls_reg('PUSH', 0, rs1, rd))
            continue

        if match := re.fullmatch(r'POP\s+R(\d+),\s*R(\d+)', line):
            rs1 = int(match.group(1))
            rd = int(match.group(2))
            words.append(encode_ls_reg('POP', 0, rs1, rd))
            continue

        if match := re.fullmatch(r'MOVE\s+R(\d+)(?:\+(\d+))?,\s*R(\d+)', line):
            rs1 = int(match.group(1))
            offset = int(match.group(2) or '0')
            rd = int(match.group(3))
            words.append(encode_ls_reg('MOVE', offset // 2, rs1, rd))
            continue

        raise ValueError(f'Unsupported shared program syntax: {line}')

    return words


def _load_program_execution(code_memory: dict[int, int], data_memory: dict[int, int], execution: ProgramExecution) -> None:
    code_memory.clear()
    data_memory.clear()

    for word_index, word in enumerate(execution.words):
        base = word_index * 2
        code_memory[base] = word & 0xFF
        code_memory[base + 1] = (word >> 8) & 0xFF

    if execution.extra_code_words:
        for base, word in execution.extra_code_words.items():
            code_memory[base] = word & 0xFF
            code_memory[base + 1] = (word >> 8) & 0xFF

    if execution.initial_data_memory:
        for address, value in execution.initial_data_memory.items():
            data_memory[address] = value & 0xFF


def _snapshot_execution(
    ctx,
    dut,
    data_memory: dict[int, int],
    commit_count: int,
    executed_cycles: int,
) -> dict[str, object]:
    registers = [ctx.get(dut.register_file[index]) for index in range(16)]
    return {
        'registers': registers,
        'flags': ctx.get(dut.flags),
        'halted': ctx.get(dut.halted),
        'locked_up': ctx.get(dut.locked_up),
        'trap_cause': ctx.get(dut.special_regs.trap_cause),
        'trap_fault_addr': ctx.get(dut.special_regs.trap_fault_addr),
        'trap_access': ctx.get(dut.special_regs.trap_access),
        'trap_pc': ctx.get(dut.special_regs.trap_pc),
        'trap_aux': ctx.get(dut.special_regs.trap_aux),
        'special_registers': {
            'cpu_control': ctx.get(dut.special_regs.cpu_control),
            'interrupt_table_base': ctx.get(dut.special_regs.interrupt_table_base),
            'interrupt_mask': ctx.get(dut.special_regs.interrupt_mask),
            'interrupt_mask_high': ctx.get(dut.special_regs.interrupt_mask_high),
            'interrupt_states': ctx.get(dut.special_regs.interrupt_states),
            'interrupt_states_high': ctx.get(dut.special_regs.interrupt_states_high),
            'interrupt_epc': ctx.get(dut.special_regs.interrupt_epc),
            'interrupt_eflags': ctx.get(dut.special_regs.interrupt_eflags),
            'interrupt_cpu_control': ctx.get(dut.special_regs.interrupt_cpu_control),
        },
        'data_memory': dict(data_memory),
        'commit_count': commit_count,
        'executed_cycles': executed_cycles,
    }


async def _pulse_reset(ctx, dut) -> None:
    ctx.set(dut.test_reset, 1)
    await ctx.tick()
    await ctx.tick()
    ctx.set(dut.test_reset, 0)
    await ctx.tick()
    await ctx.tick()


def run_batched_program_words(executions: list[ProgramExecution], *, config: Little64CoreConfig | None = None) -> list[dict[str, object]]:
    resolved_config = config or Little64CoreConfig(reset_vector=0)
    adapter = adapter_for_variant(resolved_config.core_variant)
    dut = _ResettableCore(adapter.create_core(resolved_config))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    code_memory: dict[int, int] = {}
    data_memory: dict[int, int] = {}
    ready = {'value': False}
    current_irq_lines = {'value': 0}
    results: list[dict[str, object]] = []

    def read_code_qword(addr: int) -> int:
        return sum((code_memory.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))

    def read_data_qword(addr: int) -> int:
        return sum((data_memory.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))

    async def bus_process(ctx):
        ctx.set(dut.i_bus.ack, 0)
        ctx.set(dut.d_bus.ack, 0)
        while True:
            await ctx.tick()

            if ready['value'] and ctx.get(dut.i_bus.cyc) and ctx.get(dut.i_bus.stb):
                ctx.set(dut.i_bus.dat_r, read_code_qword(ctx.get(dut.i_bus.adr)))
                ctx.set(dut.i_bus.ack, 1)
            else:
                ctx.set(dut.i_bus.ack, 0)

            if ready['value'] and ctx.get(dut.d_bus.cyc) and ctx.get(dut.d_bus.stb):
                d_addr = ctx.get(dut.d_bus.adr)
                if ctx.get(dut.d_bus.we):
                    d_value = ctx.get(dut.d_bus.dat_w)
                    d_sel = ctx.get(dut.d_bus.sel)
                    for byte_index in range(8):
                        if d_sel & (1 << byte_index):
                            data_memory[d_addr + byte_index] = (d_value >> (8 * byte_index)) & 0xFF
                else:
                    ctx.set(dut.d_bus.dat_r, read_data_qword(d_addr))
                ctx.set(dut.d_bus.ack, 1)
            else:
                ctx.set(dut.d_bus.ack, 0)

    async def observe_process(ctx):
        ctx.set(dut.test_reset, 0)
        ctx.set(dut.irq_lines, 0)

        for execution in executions:
            ready['value'] = False
            current_irq_lines['value'] = 0
            _load_program_execution(code_memory, data_memory, execution)

            await _pulse_reset(ctx, dut)
            ctx.set(dut.irq_lines, 0)

            await adapter.prepare_for_execution(
                ctx,
                dut,
                resolved_config,
                ready=ready,
                initial_registers=execution.initial_registers,
                initial_flags=execution.initial_flags,
                initial_special_registers=execution.initial_special_registers,
            )

            commit_count = 0
            executed_cycles = 0
            for cycle in range(execution.max_cycles):
                if execution.irq_schedule and cycle in execution.irq_schedule:
                    current_irq_lines['value'] = execution.irq_schedule[cycle]
                    ctx.set(dut.irq_lines, current_irq_lines['value'])
                await ctx.tick()
                executed_cycles += 1
                if ctx.get(dut.commit_valid):
                    commit_count += 1
                if ctx.get(dut.halted) or ctx.get(dut.locked_up):
                    break

            results.append(_snapshot_execution(ctx, dut, data_memory, commit_count, executed_cycles))

        ready['value'] = False
        ctx.set(dut.irq_lines, 0)

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(observe_process)
    total_cycles = sum(execution.max_cycles for execution in executions) + (12 * len(executions)) + 8
    sim.run_until(total_cycles * 1e-6)
    return results


def _run_program_words_fresh(words: list[int],
                             *,
                             config: Little64CoreConfig | None = None,
                             initial_registers: dict[int, int] | None = None,
                             initial_flags: int = 0,
                             initial_special_registers: dict[str, int] | None = None,
                             extra_code_words: dict[int, int] | None = None,
                             initial_data_memory: dict[int, int] | None = None,
                             irq_schedule: dict[int, int] | None = None,
                             max_cycles: int = 256) -> dict[str, object]:
    resolved_config = config or Little64CoreConfig(reset_vector=0)
    adapter = adapter_for_variant(resolved_config.core_variant)
    dut = adapter.create_core(resolved_config)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    code_memory: dict[int, int] = {}
    data_memory: dict[int, int] = {}
    _load_program_execution(
        code_memory,
        data_memory,
        ProgramExecution(
            words=list(words),
            extra_code_words=extra_code_words,
            initial_data_memory=initial_data_memory,
        ),
    )

    observed: dict[str, object] = {}
    ready = {'value': False}
    current_irq_lines = {'value': 0}
    commit_count = {'value': 0}
    executed_cycles = {'value': 0}

    def read_code_qword(addr: int) -> int:
        return sum((code_memory.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))

    def read_data_qword(addr: int) -> int:
        return sum((data_memory.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))

    async def bus_process(ctx):
        ctx.set(dut.i_bus.ack, 0)
        ctx.set(dut.d_bus.ack, 0)
        while True:
            await ctx.tick()

            if ready['value'] and ctx.get(dut.i_bus.cyc) and ctx.get(dut.i_bus.stb):
                ctx.set(dut.i_bus.dat_r, read_code_qword(ctx.get(dut.i_bus.adr)))
                ctx.set(dut.i_bus.ack, 1)
            else:
                ctx.set(dut.i_bus.ack, 0)

            if ready['value'] and ctx.get(dut.d_bus.cyc) and ctx.get(dut.d_bus.stb):
                d_addr = ctx.get(dut.d_bus.adr)
                if ctx.get(dut.d_bus.we):
                    d_value = ctx.get(dut.d_bus.dat_w)
                    d_sel = ctx.get(dut.d_bus.sel)
                    for byte_index in range(8):
                        if d_sel & (1 << byte_index):
                            data_memory[d_addr + byte_index] = (d_value >> (8 * byte_index)) & 0xFF
                else:
                    ctx.set(dut.d_bus.dat_r, read_data_qword(d_addr))
                ctx.set(dut.d_bus.ack, 1)
            else:
                ctx.set(dut.d_bus.ack, 0)

    async def observe_process(ctx):
        await adapter.prepare_for_execution(
            ctx,
            dut,
            resolved_config,
            ready=ready,
            initial_registers=initial_registers,
            initial_flags=initial_flags,
            initial_special_registers=initial_special_registers,
        )

        for cycle in range(max_cycles):
            if irq_schedule and cycle in irq_schedule:
                current_irq_lines['value'] = irq_schedule[cycle]
                ctx.set(dut.irq_lines, current_irq_lines['value'])
            await ctx.tick()
            executed_cycles['value'] += 1
            if ctx.get(dut.commit_valid):
                commit_count['value'] += 1
            if ctx.get(dut.halted) or ctx.get(dut.locked_up):
                break

        observed.update(
            _snapshot_execution(
                ctx,
                dut,
                data_memory,
                commit_count['value'],
                executed_cycles['value'],
            )
        )

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(observe_process)
    sim.run_until((max_cycles + 8) * 1e-6)
    return observed


def run_program_words(words: list[int],
                      *,
                      config: Little64CoreConfig | None = None,
                      initial_registers: dict[int, int] | None = None,
                      initial_flags: int = 0,
                      initial_special_registers: dict[str, int] | None = None,
                      extra_code_words: dict[int, int] | None = None,
                      initial_data_memory: dict[int, int] | None = None,
                      irq_schedule: dict[int, int] | None = None,
                      max_cycles: int = 256) -> dict[str, object]:
    return _run_program_words_fresh(
        words,
        config=config,
        initial_registers=initial_registers,
        initial_flags=initial_flags,
        initial_special_registers=initial_special_registers,
        extra_code_words=extra_code_words,
        initial_data_memory=initial_data_memory,
        irq_schedule=irq_schedule,
        max_cycles=max_cycles,
    )


def run_single_instruction(word: int,
                           *,
                           config: Little64CoreConfig | None = None,
                           initial_registers: dict[int, int] | None = None,
                           initial_flags: int = 0,
                           initial_special_registers: dict[str, int] | None = None,
                           extra_code_words: dict[int, int] | None = None,
                           initial_data_memory: dict[int, int] | None = None,
                           irq_schedule: dict[int, int] | None = None,
                           max_cycles: int = 20) -> dict[str, object]:
    return run_program_words(
        [word, encode_gp_imm('STOP', 0, 0)],
        config=config,
        initial_registers=initial_registers,
        initial_flags=initial_flags,
        initial_special_registers=initial_special_registers,
        extra_code_words=extra_code_words,
        initial_data_memory=initial_data_memory,
        irq_schedule=irq_schedule,
        max_cycles=max_cycles,
    )


def run_program_source(source: str,
                       *,
                       config: Little64CoreConfig | None = None,
                       initial_registers: dict[int, int] | None = None,
                       initial_flags: int = 0,
                       initial_special_registers: dict[str, int] | None = None,
                       extra_code_words: dict[int, int] | None = None,
                       initial_data_memory: dict[int, int] | None = None,
                       irq_schedule: dict[int, int] | None = None,
                       max_cycles: int = 256) -> dict[str, object]:
    return run_program_words(
        assemble_source(source),
        config=config,
        initial_registers=initial_registers,
        initial_flags=initial_flags,
        initial_special_registers=initial_special_registers,
        extra_code_words=extra_code_words,
        initial_data_memory=initial_data_memory,
        irq_schedule=irq_schedule,
        max_cycles=max_cycles,
    )


# ---------------------------------------------------------------------------
# Flat-ELF runner (unified address space for compiled C programmes)
# ---------------------------------------------------------------------------

_EM_LITTLE64 = 0x4C36
_PT_LOAD = 1


def _load_elf_flat(elf_bytes: bytes) -> tuple[int, dict[int, int]]:
    """Parse a Little-64 ELF64 binary into (entry_point, byte_dict).

    All PT_LOAD segments are merged into a single flat byte dictionary keyed
    by virtual address.  BSS regions (memsz > filesz) are zero-filled so the
    caller does not need a separate BSS-clearing step.
    """
    (
        e_ident,
        _,            # e_type
        e_machine,
        _,            # e_version
        e_entry,
        e_phoff,
        _,            # e_shoff
        _,            # e_flags
        _,            # e_ehsize
        e_phentsize,
        e_phnum,
        _, _, _,      # e_shentsize, e_shnum, e_shstrndx
    ) = struct.unpack_from('<16sHHIQQQIHHHHHH', elf_bytes, 0)

    if e_ident[0:4] != b'\x7fELF':
        raise ValueError('Not an ELF file')
    if e_machine != _EM_LITTLE64:
        raise ValueError(
            f'ELF machine 0x{e_machine:x} is not Little-64 (expected 0x{_EM_LITTLE64:x})'
        )

    flat: dict[int, int] = {}
    for i in range(e_phnum):
        p_type, _, p_offset, p_vaddr, _, p_filesz, p_memsz, _ = struct.unpack_from(
            '<IIQQQQQQ', elf_bytes, e_phoff + i * e_phentsize
        )
        if p_type != _PT_LOAD:
            continue
        for j in range(p_filesz):
            flat[p_vaddr + j] = elf_bytes[p_offset + j]
        for j in range(p_filesz, p_memsz):
            flat[p_vaddr + j] = 0

    return e_entry, flat


def run_elf_flat(
    elf_bytes: bytes,
    *,
    config: Little64CoreConfig | None = None,
    stack_top: int = 0x0004_0000,
    max_cycles: int = 131072,
) -> dict[str, object]:
    """Run a flat-linked Little-64 ELF using a unified memory model.

    Both the instruction bus and the data bus are backed by the same flat byte
    dictionary, matching the bare-metal linker's single address-space layout.
    The ELF entry point is used as the initial PC; *stack_top* is loaded into
    R13 before the first instruction executes.

    Returns the same snapshot dict as ``run_program_words`` (including
    ``executed_cycles`` and ``commit_count``).  The ``data_memory`` field in
    the snapshot is always ``{}`` to avoid capturing the full program image.
    """
    entry_point, flat_memory = _load_elf_flat(elf_bytes)
    resolved_config = config or Little64CoreConfig(core_variant='v2', reset_vector=0)
    adapter = adapter_for_variant(resolved_config.core_variant)
    dut = adapter.create_core(resolved_config)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    memory: dict[int, int] = flat_memory
    observed: dict[str, object] = {}
    ready = {'value': False}
    commit_count = {'value': 0}
    executed_cycles = {'value': 0}

    def read_qword(addr: int) -> int:
        return sum((memory.get(addr + b, 0) & 0xFF) << (8 * b) for b in range(8))

    async def bus_process(ctx):
        ctx.set(dut.i_bus.ack, 0)
        ctx.set(dut.d_bus.ack, 0)
        while True:
            await ctx.tick()
            if ready['value'] and ctx.get(dut.i_bus.cyc) and ctx.get(dut.i_bus.stb):
                ctx.set(dut.i_bus.dat_r, read_qword(ctx.get(dut.i_bus.adr)))
                ctx.set(dut.i_bus.ack, 1)
            else:
                ctx.set(dut.i_bus.ack, 0)
            if ready['value'] and ctx.get(dut.d_bus.cyc) and ctx.get(dut.d_bus.stb):
                d_addr = ctx.get(dut.d_bus.adr)
                if ctx.get(dut.d_bus.we):
                    d_value = ctx.get(dut.d_bus.dat_w)
                    d_sel = ctx.get(dut.d_bus.sel)
                    for byte_index in range(8):
                        if d_sel & (1 << byte_index):
                            memory[d_addr + byte_index] = (d_value >> (8 * byte_index)) & 0xFF
                else:
                    ctx.set(dut.d_bus.dat_r, read_qword(d_addr))
                ctx.set(dut.d_bus.ack, 1)
            else:
                ctx.set(dut.d_bus.ack, 0)

    async def observe_process(ctx):
        await adapter.prepare_for_execution(
            ctx,
            dut,
            resolved_config,
            ready=ready,
            initial_registers={13: stack_top, 15: entry_point},
        )
        for _ in range(max_cycles):
            await ctx.tick()
            executed_cycles['value'] += 1
            if ctx.get(dut.commit_valid):
                commit_count['value'] += 1
            if ctx.get(dut.halted) or ctx.get(dut.locked_up):
                break
        observed.update(
            _snapshot_execution(ctx, dut, {}, commit_count['value'], executed_cycles['value'])
        )

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(observe_process)
    sim.run_until((max_cycles + 8) * 1e-6)
    return observed
