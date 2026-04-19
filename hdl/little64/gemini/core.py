from __future__ import annotations

from amaranth import Array, Cat, Const, Elaboratable, Module, Mux, Signal

from ..config import Little64CoreConfig
from ..isa import (
    CPU_CONTROL_CUR_INT_MASK,
    CPU_CONTROL_CUR_INT_SHIFT,
    CPU_CONTROL_IN_INTERRUPT,
    CPU_CONTROL_INT_ENABLE,
    CPU_CONTROL_PAGING_ENABLE,
    CPU_CONTROL_USER_MODE,
    TrapVector,
    SpecialRegister,
    LSOpcode,
    GPOpcode,
    FLAG_Z,
    FLAG_C,
    FLAG_S,
)
from ..special_registers import Little64SpecialRegisterFile
from ..v2.frontend import Little64V2FetchFrontend
from ..v2.lsu import Little64V2LSU
from ..decode import (
    instruction_rd,
    instruction_rs1,
    instruction_ls_opcode,
    instruction_gp_opcode,
    instruction_ldi_imm8,
    instruction_ldi_shift,
    instruction_ls_offset2,
    instruction_top2,
    instruction_top3,
    is_ldi_format,
    is_gp_format,
)
from ..alu import ls_condition, flag_value, sign_extend

class Little64GeminiCore(Elaboratable):
    """
    Pipelined Gemini Core.
    Goal: 1 IPC.
    5 stages: IF, ID, EX, MEM, WB.
    """
    def __init__(self, config: Little64CoreConfig | None = None) -> None:
        self.config = config or Little64CoreConfig(core_variant='gemini')
        
        self.frontend = Little64V2FetchFrontend(
            data_width=self.config.instruction_bus_width,
            address_width=self.config.address_width,
        )
        self.lsu = Little64V2LSU(
            data_width=self.config.data_bus_width,
            address_width=self.config.address_width,
        )
        self.special_regs = Little64SpecialRegisterFile(self.config)
        
        self.i_bus = self.frontend.i_bus
        self.d_bus = self.lsu.bus

        self.irq_lines = Signal(self.config.irq_input_count)
        self.halted = Signal()
        self.locked_up = Signal()

        # Extra signals for LiteX/Linux Boot / Verilator Harness
        self.boot_r1 = Signal(64)
        self.boot_r13 = Signal(64)
        self.state = Signal(4)
        self.current_instruction = Signal(16)
        self.fetch_phys_addr = Signal(64)
        self.page_table_root_physical = Signal(64)
        
        # Architected State
        self.register_file = [
            Signal(64, name=f'r{index}', init=self.config.reset_vector if index == 15 else 0)
            for index in range(16)
        ]
        # Expose individual registers as attributes for Verilator visibility
        self.r0 = self.register_file[0]
        self.r1 = self.register_file[1]
        self.r2 = self.register_file[2]
        self.r3 = self.register_file[3]
        self.r4 = self.register_file[4]
        self.r5 = self.register_file[5]
        self.r6 = self.register_file[6]
        self.r7 = self.register_file[7]
        self.r8 = self.register_file[8]
        self.r9 = self.register_file[9]
        self.r10 = self.register_file[10]
        self.r11 = self.register_file[11]
        self.r12 = self.register_file[12]
        self.r13 = self.register_file[13]
        self.r14 = self.register_file[14]
        self.r15 = self.register_file[15]
        
        self.regs = Array(self.register_file)
        self.flags = Signal(3) # Z, C, S
        
        # Internal fetch PC (architected PC is regs[15])
        self.fetch_pc = Signal(64, init=self.config.reset_vector)
        
        # Pipeline Registers
        # IF/ID
        self.id_pc = Signal(64)
        self.id_instruction = Signal(16)
        self.id_valid = Signal()
        
        # ID/EX
        self.ex_pc = Signal(64)
        self.ex_instruction = Signal(16)
        self.ex_valid = Signal()
        self.ex_op_a = Signal(64)
        self.ex_op_b = Signal(64)
        self.ex_rd = Signal(4)
        self.ex_rs1 = Signal(4)
        self.ex_reg_write = Signal()
        self.ex_reg_write2 = Signal()
        self.ex_rd2 = Signal(4)
        self.ex_lsu_read = Signal()
        self.ex_lsu_write = Signal()
        self.ex_lsu_width = Signal(4)
        self.ex_is_jump = Signal()
        self.ex_is_gp = Signal()
        self.ex_gp_opcode = Signal(5)
        self.ex_ls_opcode = Signal(4)
        self.ex_imm8 = Signal(8)
        self.ex_shift = Signal(2)
        self.ex_offset2 = Signal(2)
        self.ex_halt = Signal()
        
        # EX/MEM
        self.mem_pc = Signal(64)
        self.mem_valid = Signal()
        self.mem_instruction = Signal(16)
        self.mem_alu_result = Signal(64)
        self.mem_rd = Signal(4)
        self.mem_reg_write = Signal()
        self.mem_reg_write2 = Signal()
        self.mem_rd2 = Signal(4)
        self.mem_store_val = Signal(64)
        self.mem_lsu_read = Signal()
        self.mem_lsu_write = Signal()
        self.mem_lsu_width = Signal(4)
        self.mem_update_flags = Signal()
        self.mem_new_flags = Signal(3)
        self.mem_special_write = Signal()
        self.mem_special_sel = Signal(16)
        self.mem_halt = Signal()
        self.mem_trap = Signal()
        self.mem_trap_cause = Signal(64)
        
        # MEM/WB
        self.wb_pc = Signal(64)
        self.wb_valid = Signal()
        self.wb_instruction = Signal(16)
        self.wb_rd = Signal(4)
        self.wb_reg_write = Signal()
        self.wb_rd2 = Signal(4)
        self.wb_reg_write2 = Signal()
        self.wb_result = Signal(64)
        self.wb_result2 = Signal(64)
        self.wb_update_flags = Signal()
        self.wb_new_flags = Signal(3)
        self.wb_halt = Signal()
        self.wb_trap = Signal()
        self.wb_next_pc = Signal(64)
        
        # Test observability
        self.commit_valid = Signal()
        self.commit_pc = Signal(64)
        self.commit_instruction = Signal(16)

        # Internal state
        self.lsu_started = Signal()

    def elaborate(self, platform):
        m = Module()
        
        m.submodules.frontend = self.frontend
        m.submodules.lsu = self.lsu
        m.submodules.special_regs = self.special_regs
        
        # Stall / Flush Signals
        stall_if = Signal()
        stall_id = Signal()
        stall_ex = Signal()
        stall_mem = Signal()
        
        flush_id = Signal()
        flush_ex = Signal()
        
        redirect_valid = Signal()
        redirect_pc = Signal(64)
        
        # Trap handling
        trap_entry_active = Signal()
        trap_entry_vector = Signal(64)
        trap_entry_epc = Signal(64)
        trap_entry_redirect_valid = Signal()
        trap_entry_redirect_pc = Signal(64)
        
        # LSU connectivity
        mem_lsu_active = self.mem_valid & (self.mem_lsu_read | self.mem_lsu_write)
        mem_lsu_done = self.lsu.response_valid
        
        # Global Redirect logic
        ex_redirect_valid = Signal()
        ex_redirect_pc = Signal(64)
        mem_redirect_valid = Signal()
        mem_redirect_pc = Signal(64)

        m.d.comb += [
            redirect_valid.eq(ex_redirect_valid | mem_redirect_valid | trap_entry_redirect_valid),
            redirect_pc.eq(Mux(trap_entry_redirect_valid, trap_entry_redirect_pc,
                           Mux(mem_redirect_valid, mem_redirect_pc, ex_redirect_pc))),
        ]
        
        # R0 is always zero
        m.d.comb += self.register_file[0].eq(0)

        # Intermediate signals for EX stage
        sll_carry_shamt = Signal(7)
        srl_carry_idx = Signal(7)
        sra_carry_idx = Signal(7)

        # Extra signals for observability/boot
        m.d.comb += [
            self.current_instruction.eq(self.id_instruction),
            self.fetch_phys_addr.eq(self.frontend.fetch_phys_addr),
            self.state.eq(Mux(self.id_valid, 3, 7)), # 3=DECODE for harness tracing
            self.page_table_root_physical.eq(self.special_regs.page_table_root_physical),
        ]

        # Register initialization for boot
        is_first_cycle = Signal(init=1)
        m.d.sync += is_first_cycle.eq(0)
        with m.If(is_first_cycle):
            m.d.sync += [
                self.register_file[1].eq(self.boot_r1),
                self.register_file[13].eq(self.boot_r13),
            ]

        # --- IF Stage ---
        m.d.comb += [
            self.frontend.pc.eq(self.fetch_pc),
            self.frontend.invalidate.eq(redirect_valid),
        ]
        
        # IF/ID Pipeline Register update
        with m.If(redirect_valid):
            m.d.sync += [
                self.id_valid.eq(0),
                self.fetch_pc.eq(redirect_pc),
                # Clear latched redirect bits
                trap_entry_redirect_valid.eq(0),
            ]
        with m.Elif(~stall_if):
            with m.If(flush_id):
                m.d.sync += [
                    self.id_valid.eq(0),
                ]
            with m.Elif(self.frontend.instruction_valid):
                m.d.sync += [
                    self.id_instruction.eq(self.frontend.instruction_word),
                    self.id_pc.eq(self.fetch_pc),
                    self.id_valid.eq(1),
                    self.fetch_pc.eq(self.fetch_pc + 2),
                ]
            with m.Else():
                m.d.sync += self.id_valid.eq(0)

        # --- ID Stage ---
        id_instruction = self.id_instruction
        id_rd = instruction_rd(id_instruction)
        id_rs1 = instruction_rs1(id_instruction)
        id_top2 = instruction_top2(id_instruction)
        id_top3 = instruction_top3(id_instruction)
        id_ls_op = instruction_ls_opcode(id_instruction)
        id_gp_op = instruction_gp_opcode(id_instruction)
        id_imm8 = instruction_ldi_imm8(id_instruction)
        id_shift = instruction_ldi_shift(id_instruction)
        id_offset2 = instruction_ls_offset2(id_instruction)
        
        id_reg_write = Signal()
        id_reg_write2 = Signal()
        id_rd2 = Signal(4)
        id_lsu_read = Signal()
        id_lsu_write = Signal()
        id_lsu_width = Signal(4, init=8)
        id_is_jump = Signal()
        id_is_gp = Signal()
        id_halt = Signal()
        
        # Decoding defaults
        m.d.comb += [
            id_reg_write.eq(0),
            id_reg_write2.eq(0),
            id_lsu_read.eq(0),
            id_lsu_write.eq(0),
            id_is_jump.eq(0),
            id_is_gp.eq(0),
            id_halt.eq(0),
        ]

        # Decoding
        with m.If(self.id_valid):
            with m.Switch(id_top2):
                with m.Case(0b00): # LS Register
                    m.d.comb += id_is_gp.eq(0)
                    with m.Switch(id_ls_op):
                        with m.Case(LSOpcode.LOAD): m.d.comb += [id_reg_write.eq(1), id_lsu_read.eq(1), id_lsu_width.eq(8)]
                        with m.Case(LSOpcode.STORE): m.d.comb += [id_lsu_write.eq(1), id_lsu_width.eq(8)]
                        with m.Case(LSOpcode.BYTE_LOAD): m.d.comb += [id_reg_write.eq(1), id_lsu_read.eq(1), id_lsu_width.eq(1)]
                        with m.Case(LSOpcode.BYTE_STORE): m.d.comb += [id_lsu_write.eq(1), id_lsu_width.eq(1)]
                        with m.Case(LSOpcode.SHORT_LOAD): m.d.comb += [id_reg_write.eq(1), id_lsu_read.eq(1), id_lsu_width.eq(2)]
                        with m.Case(LSOpcode.SHORT_STORE): m.d.comb += [id_lsu_write.eq(1), id_lsu_width.eq(2)]
                        with m.Case(LSOpcode.WORD_LOAD): m.d.comb += [id_reg_write.eq(1), id_lsu_read.eq(1), id_lsu_width.eq(4)]
                        with m.Case(LSOpcode.WORD_STORE): m.d.comb += [id_lsu_write.eq(1), id_lsu_width.eq(4)]
                        with m.Case(LSOpcode.PUSH): m.d.comb += [id_lsu_write.eq(1), id_reg_write.eq(1), id_lsu_width.eq(8)]
                        with m.Case(LSOpcode.POP): m.d.comb += [id_lsu_read.eq(1), id_reg_write.eq(1), id_reg_write2.eq(1), id_rd2.eq(id_rs1), id_lsu_width.eq(8)]
                        with m.Case(LSOpcode.MOVE): m.d.comb += id_reg_write.eq(1)
                        with m.Case(LSOpcode.JUMP_Z, LSOpcode.JUMP_C, LSOpcode.JUMP_S, LSOpcode.JUMP_GT, LSOpcode.JUMP_LT):
                            m.d.comb += [id_is_jump.eq(1), id_reg_write.eq(1)]
                with m.Case(0b01): # LS PC-Relative
                    m.d.comb += id_is_gp.eq(0)
                    with m.Switch(id_ls_op):
                        with m.Case(LSOpcode.LOAD): m.d.comb += [id_reg_write.eq(1), id_lsu_read.eq(1), id_lsu_width.eq(8)]
                        with m.Case(LSOpcode.STORE): m.d.comb += [id_lsu_write.eq(1), id_lsu_width.eq(8)]
                        with m.Case(LSOpcode.BYTE_LOAD): m.d.comb += [id_reg_write.eq(1), id_lsu_read.eq(1), id_lsu_width.eq(1)]
                        with m.Case(LSOpcode.BYTE_STORE): m.d.comb += [id_lsu_write.eq(1), id_lsu_width.eq(1)]
                        with m.Case(LSOpcode.SHORT_LOAD): m.d.comb += [id_reg_write.eq(1), id_lsu_read.eq(1), id_lsu_width.eq(2)]
                        with m.Case(LSOpcode.SHORT_STORE): m.d.comb += [id_lsu_write.eq(1), id_lsu_width.eq(2)]
                        with m.Case(LSOpcode.WORD_LOAD): m.d.comb += [id_reg_write.eq(1), id_lsu_read.eq(1), id_lsu_width.eq(4)]
                        with m.Case(LSOpcode.WORD_STORE): m.d.comb += [id_lsu_write.eq(1), id_lsu_width.eq(4)]
                        with m.Case(LSOpcode.MOVE): m.d.comb += id_reg_write.eq(1)
                        with m.Case(LSOpcode.JUMP_Z, LSOpcode.JUMP_C, LSOpcode.JUMP_S, LSOpcode.JUMP_GT, LSOpcode.JUMP_LT):
                            m.d.comb += id_is_jump.eq(1)
                with m.Case(0b10): # LDI
                    m.d.comb += [id_reg_write.eq(1), id_is_gp.eq(0)]
                with m.Case(0b11): # Extended
                    with m.Switch(id_top3):
                        with m.Case(0b110): # GP
                            m.d.comb += id_is_gp.eq(1)
                            with m.Switch(id_gp_op):
                                with m.Case(GPOpcode.ADD, GPOpcode.SUB, GPOpcode.AND, GPOpcode.OR, GPOpcode.XOR, 
                                            GPOpcode.SLL, GPOpcode.SRL, GPOpcode.SRA, 
                                            GPOpcode.SLLI, GPOpcode.SRLI, GPOpcode.SRAI,
                                            GPOpcode.LSR, GPOpcode.SSR):
                                    m.d.comb += id_reg_write.eq(1)
                                with m.Case(GPOpcode.TEST):
                                    m.d.comb += id_reg_write.eq(0)
                                with m.Case(GPOpcode.LLR):
                                    m.d.comb += [id_reg_write.eq(1), id_lsu_read.eq(1), id_lsu_width.eq(8)]
                                with m.Case(GPOpcode.SCR):
                                    m.d.comb += [id_lsu_write.eq(1), id_lsu_width.eq(8)]
                                with m.Case(GPOpcode.STOP):
                                    m.d.comb += id_halt.eq(1)
                        with m.Case(0b111): # Unconditional jump
                            m.d.comb += [id_is_jump.eq(1), id_is_gp.eq(0)]

        # Forwarding Logic
        id_val_a_fwd = Signal(64)
        id_val_b_fwd = Signal(64)
        
        ex_alu_result_comb = Signal(64)
        
        # R15 (PC) reading in ID stage
        def read_reg_id(index):
            return Mux(index == 15, self.id_pc, self.regs[index])

        # Forward A
        match_rs1_ex = (self.ex_rd == id_rs1) | (self.ex_rd2 == id_rs1)
        match_rs1_mem = (self.mem_rd == id_rs1) | (self.mem_rd2 == id_rs1)
        match_rs1_wb = (self.wb_rd == id_rs1) | (self.wb_rd2 == id_rs1)

        with m.If(self.ex_valid & match_rs1_ex & (id_rs1 != 15) & (id_rs1 != 0)):
            with m.If(self.ex_reg_write & (self.ex_rd == id_rs1)):
                m.d.comb += id_val_a_fwd.eq(ex_alu_result_comb)
            with m.Else():
                m.d.comb += id_val_a_fwd.eq(0) # Will stall if match_rs1_ex & ex_lsu_read
        with m.Elif(self.mem_valid & match_rs1_mem & (id_rs1 != 15) & (id_rs1 != 0)):
            with m.If(self.mem_reg_write & (self.mem_rd == id_rs1)):
                with m.If(self.mem_lsu_read):
                    m.d.comb += id_val_a_fwd.eq(self.lsu.response_load_value)
                with m.Else():
                    m.d.comb += id_val_a_fwd.eq(self.mem_alu_result)
            with m.Elif(self.mem_reg_write2 & (self.mem_rd2 == id_rs1)):
                m.d.comb += id_val_a_fwd.eq(self.lsu.response_load_value)
        with m.Elif(self.wb_valid & match_rs1_wb & (id_rs1 != 15) & (id_rs1 != 0)):
            with m.If(self.wb_reg_write & (self.wb_rd == id_rs1)):
                m.d.comb += id_val_a_fwd.eq(self.wb_result)
            with m.Else():
                m.d.comb += id_val_a_fwd.eq(self.wb_result2)
        with m.Else():
            m.d.comb += id_val_a_fwd.eq(read_reg_id(id_rs1))

        # Forward B
        match_rd_ex = (self.ex_rd == id_rd) | (self.ex_rd2 == id_rd)
        match_rd_mem = (self.mem_rd == id_rd) | (self.mem_rd2 == id_rd)
        match_rd_wb = (self.wb_rd == id_rd) | (self.wb_rd2 == id_rd)

        with m.If(self.ex_valid & match_rd_ex & (id_rd != 15) & (id_rd != 0)):
            with m.If(self.ex_reg_write & (self.ex_rd == id_rd)):
                m.d.comb += id_val_b_fwd.eq(ex_alu_result_comb)
            with m.Else():
                m.d.comb += id_val_b_fwd.eq(0)
        with m.Elif(self.mem_valid & match_rd_mem & (id_rd != 15) & (id_rd != 0)):
            with m.If(self.mem_reg_write & (self.mem_rd == id_rd)):
                with m.If(self.mem_lsu_read):
                    m.d.comb += id_val_b_fwd.eq(self.lsu.response_load_value)
                with m.Else():
                    m.d.comb += id_val_b_fwd.eq(self.mem_alu_result)
            with m.Elif(self.mem_reg_write2 & (self.mem_rd2 == id_rd)):
                m.d.comb += id_val_b_fwd.eq(self.lsu.response_load_value)
        with m.Elif(self.wb_valid & match_rd_wb & (id_rd != 15) & (id_rd != 0)):
            with m.If(self.wb_reg_write & (self.wb_rd == id_rd)):
                m.d.comb += id_val_b_fwd.eq(self.wb_result)
            with m.Else():
                m.d.comb += id_val_b_fwd.eq(self.wb_result2)
        with m.Else():
            m.d.comb += id_val_b_fwd.eq(read_reg_id(id_rd))
            
        # RAW Hazards
        raw_stall = Signal()
        with m.If(self.id_valid):
            # EX stage is a LOAD/POP (result not yet available at all)
            with m.If(self.ex_valid & self.ex_lsu_read):
                with m.If(((self.ex_rd == id_rs1) | (self.ex_rd2 == id_rs1)) & (id_rs1 != 0) & (id_rs1 != 15)):
                    m.d.comb += raw_stall.eq(1)
                with m.If(((self.ex_rd == id_rd) | (self.ex_rd2 == id_rd)) & (id_rd != 0) & (id_rd != 15)):
                    m.d.comb += raw_stall.eq(1)
            
            # MEM stage is a LOAD/POP that hasn't finished yet
            with m.If(self.mem_valid & self.mem_lsu_read):
                with m.If(~self.lsu.response_valid):
                    with m.If(((self.mem_rd == id_rs1) | (self.mem_rd2 == id_rs1)) & (id_rs1 != 0) & (id_rs1 != 15)):
                        m.d.comb += raw_stall.eq(1)
                    with m.If(((self.mem_rd == id_rd) | (self.mem_rd2 == id_rd)) & (id_rd != 0) & (id_rd != 15)):
                        m.d.comb += raw_stall.eq(1)

        m.d.comb += [
            stall_if.eq(raw_stall | (mem_lsu_active & ~mem_lsu_done) | trap_entry_active | self.halted | self.locked_up | id_halt | redirect_valid),
            stall_id.eq(raw_stall | (mem_lsu_active & ~mem_lsu_done) | trap_entry_active),
        ]

        # ID/EX Pipeline Register
        with m.If(~stall_id):
            with m.If(flush_ex | redirect_valid | trap_entry_active):
                m.d.sync += self.ex_valid.eq(0)
            with m.Else():
                m.d.sync += [
                    self.ex_pc.eq(self.id_pc),
                    self.ex_instruction.eq(self.id_instruction),
                    self.ex_valid.eq(self.id_valid),
                    self.ex_op_a.eq(id_val_a_fwd),
                    self.ex_op_b.eq(id_val_b_fwd),
                    self.ex_rd.eq(id_rd),
                    self.ex_rs1.eq(id_rs1),
                    self.ex_reg_write.eq(id_reg_write),
                    self.ex_reg_write2.eq(id_reg_write2),
                    self.ex_rd2.eq(id_rd2),
                    self.ex_lsu_read.eq(id_lsu_read),
                    self.ex_lsu_write.eq(id_lsu_write),
                    self.ex_lsu_width.eq(id_lsu_width),
                    self.ex_is_jump.eq(id_is_jump),
                    self.ex_is_gp.eq(id_is_gp),
                    self.ex_gp_opcode.eq(id_gp_op),
                    self.ex_ls_opcode.eq(id_ls_op),
                    self.ex_imm8.eq(id_imm8),
                    self.ex_shift.eq(id_shift),
                    self.ex_offset2.eq(id_offset2),
                    self.ex_halt.eq(id_halt),
                ]

        # --- EX Stage ---
        ex_new_flags = Signal(3)
        ex_update_flags = Signal()
        ex_store_val = Signal(64)
        ex_special_write = Signal()
        ex_special_sel = Signal(16)
        ex_trap = Signal()
        ex_trap_cause = Signal(64)
        
        # LS address calc
        ls_offset_val = Signal(64)
        m.d.comb += ls_offset_val.eq(sign_extend(self.ex_offset2, 2, 64) << 1)
        
        # PC-Rel calc
        pcrel6 = Signal(64)
        m.d.comb += pcrel6.eq(sign_extend(self.ex_instruction[4:10], 6, 64) << 1)
        pcrel10 = Signal(64)
        m.d.comb += pcrel10.eq(sign_extend(self.ex_instruction[0:10], 10, 64) << 1)
        pcrel13 = Signal(64)
        m.d.comb += pcrel13.eq(sign_extend(self.ex_instruction[0:13], 13, 64) << 1)
        
        ls_ea = Signal(64)
        with m.Switch(instruction_top2(self.ex_instruction)):
            with m.Case(0b00): m.d.comb += ls_ea.eq(self.ex_op_a + ls_offset_val)
            with m.Case(0b01): m.d.comb += ls_ea.eq(self.ex_pc + 2 + pcrel6)
        
        # Connect special regs read selector in EX
        m.d.comb += self.special_regs.read_selector.eq(self.ex_op_a[0:16])

        with m.If(self.ex_valid):
            # Privilege Check via SpecialRegisterFile
            is_lsr_ssr = self.ex_is_gp & ((self.ex_gp_opcode == GPOpcode.LSR) | (self.ex_gp_opcode == GPOpcode.SSR))
            
            with m.If(is_lsr_ssr):
                with m.If(self.special_regs.read_access_fault | self.special_regs.write_access_fault):
                    m.d.comb += [
                        ex_trap.eq(1),
                        ex_trap_cause.eq(TrapVector.PRIVILEGED_INSTRUCTION),
                    ]
            
            with m.If(~ex_trap):
                with m.If(self.ex_is_gp):
                    with m.Switch(self.ex_gp_opcode):
                        with m.Case(GPOpcode.ADD):
                            sum_res = Signal(65)
                            m.d.comb += [
                                sum_res.eq(self.ex_op_b + self.ex_op_a),
                                ex_alu_result_comb.eq(sum_res[:64]),
                                ex_update_flags.eq(1),
                                ex_new_flags[FLAG_Z].eq(ex_alu_result_comb == 0),
                                ex_new_flags[FLAG_C].eq(sum_res[64]), # Carry
                                ex_new_flags[FLAG_S].eq(ex_alu_result_comb[63]), # Sign
                            ]
                        with m.Case(GPOpcode.SUB, GPOpcode.TEST):
                            sub_res = Signal(65)
                            m.d.comb += [
                                sub_res.eq(self.ex_op_b - self.ex_op_a),
                                ex_alu_result_comb.eq(sub_res[:64]),
                                ex_update_flags.eq(1),
                                ex_new_flags[FLAG_Z].eq(ex_alu_result_comb == 0),
                                ex_new_flags[FLAG_C].eq(sub_res[64]), # Borrow
                                ex_new_flags[FLAG_S].eq(ex_alu_result_comb[63]), # Sign
                            ]
                        with m.Case(GPOpcode.AND):
                            m.d.comb += [
                                ex_alu_result_comb.eq(self.ex_op_b & self.ex_op_a),
                                ex_update_flags.eq(1),
                                ex_new_flags[FLAG_Z].eq(ex_alu_result_comb == 0),
                                ex_new_flags[FLAG_C].eq(self.flags[FLAG_C]),
                                ex_new_flags[FLAG_S].eq(ex_alu_result_comb[63]),
                            ]
                        with m.Case(GPOpcode.OR):
                            m.d.comb += [
                                ex_alu_result_comb.eq(self.ex_op_b | self.ex_op_a),
                                ex_update_flags.eq(1),
                                ex_new_flags[FLAG_Z].eq(ex_alu_result_comb == 0),
                                ex_new_flags[FLAG_C].eq(self.flags[FLAG_C]),
                                ex_new_flags[FLAG_S].eq(ex_alu_result_comb[63]),
                            ]
                        with m.Case(GPOpcode.XOR):
                            m.d.comb += [
                                ex_alu_result_comb.eq(self.ex_op_b ^ self.ex_op_a),
                                ex_update_flags.eq(1),
                                ex_new_flags[FLAG_Z].eq(ex_alu_result_comb == 0),
                                ex_new_flags[FLAG_C].eq(self.flags[FLAG_C]),
                                ex_new_flags[FLAG_S].eq(ex_alu_result_comb[63]),
                            ]
                        with m.Case(GPOpcode.SLL, GPOpcode.SLLI):
                            shift_amt_full = Mux(self.ex_gp_opcode == GPOpcode.SLL, self.ex_op_a, self.ex_rs1)
                            shift_amt = shift_amt_full[:7]
                            with m.If(shift_amt == 0):
                                m.d.comb += [ex_alu_result_comb.eq(self.ex_op_b), ex_new_flags[FLAG_C].eq(self.flags[FLAG_C])]
                            with m.Elif(shift_amt >= 64):
                                m.d.comb += [ex_alu_result_comb.eq(0), ex_new_flags[FLAG_C].eq(self.ex_op_b != 0)]
                            with m.Else():
                                shamt = shift_amt[:6]
                                m.d.comb += [
                                    sll_carry_shamt.eq(64 - shamt),
                                    ex_alu_result_comb.eq(self.ex_op_b << shamt),
                                    ex_new_flags[FLAG_C].eq((self.ex_op_b >> sll_carry_shamt) != 0),
                                ]
                            m.d.comb += [
                                ex_update_flags.eq(1),
                                ex_new_flags[FLAG_Z].eq(ex_alu_result_comb == 0),
                                ex_new_flags[FLAG_S].eq(ex_alu_result_comb[63]),
                            ]
                        with m.Case(GPOpcode.SRL, GPOpcode.SRLI):
                            shift_amt_full = Mux(self.ex_gp_opcode == GPOpcode.SRL, self.ex_op_a, self.ex_rs1)
                            shift_amt = shift_amt_full[:7]
                            with m.If(shift_amt == 0):
                                m.d.comb += [ex_alu_result_comb.eq(self.ex_op_b), ex_new_flags[FLAG_C].eq(self.flags[FLAG_C])]
                            with m.Elif(shift_amt >= 65):
                                m.d.comb += [ex_alu_result_comb.eq(0), ex_new_flags[FLAG_C].eq(0)]
                            with m.Elif(shift_amt == 64):
                                m.d.comb += [ex_alu_result_comb.eq(0), ex_new_flags[FLAG_C].eq(self.ex_op_b[63])]
                            with m.Else():
                                shamt = shift_amt[:6]
                                m.d.comb += [
                                    srl_carry_idx.eq(shamt - 1),
                                    ex_alu_result_comb.eq(self.ex_op_b >> shamt),
                                    ex_new_flags[FLAG_C].eq(self.ex_op_b.bit_select(srl_carry_idx, 1)),
                                ]
                            m.d.comb += [
                                ex_update_flags.eq(1),
                                ex_new_flags[FLAG_Z].eq(ex_alu_result_comb == 0),
                                ex_new_flags[FLAG_S].eq(ex_alu_result_comb[63]),
                            ]
                        with m.Case(GPOpcode.SRA, GPOpcode.SRAI):
                            shift_amt_full = Mux(self.ex_gp_opcode == GPOpcode.SRA, self.ex_op_a, self.ex_rs1)
                            shift_amt = shift_amt_full[:7]
                            with m.If(shift_amt == 0):
                                m.d.comb += [ex_alu_result_comb.eq(self.ex_op_b), ex_new_flags[FLAG_C].eq(self.flags[FLAG_C])]
                            with m.Elif(shift_amt >= 64):
                                filler = Mux(self.ex_op_b[63], 0xFFFFFFFFFFFFFFFF, 0)
                                m.d.comb += [ex_alu_result_comb.eq(filler), ex_new_flags[FLAG_C].eq(self.ex_op_b[63])]
                            with m.Else():
                                shamt = shift_amt[:6]
                                m.d.comb += [
                                    sra_carry_idx.eq(shamt - 1),
                                    ex_alu_result_comb.eq(self.ex_op_b.as_signed() >> shamt),
                                    ex_new_flags[FLAG_C].eq(self.ex_op_b.bit_select(sra_carry_idx, 1)),
                                ]
                            m.d.comb += [
                                ex_update_flags.eq(1),
                                ex_new_flags[FLAG_Z].eq(ex_alu_result_comb == 0),
                                ex_new_flags[FLAG_S].eq(ex_alu_result_comb[63]),
                            ]
                        with m.Case(GPOpcode.LSR):
                            m.d.comb += ex_alu_result_comb.eq(self.special_regs.read_data)
                        with m.Case(GPOpcode.SSR):
                            m.d.comb += [ex_special_write.eq(1), ex_special_sel.eq(self.ex_op_a[:16]), ex_store_val.eq(self.ex_op_b)]
                        with m.Case(GPOpcode.STOP):
                            pass
                with m.Elif(is_ldi_format(self.ex_instruction)):
                    with m.Switch(self.ex_shift):
                        with m.Case(0): m.d.comb += ex_alu_result_comb.eq(self.ex_imm8)
                        with m.Case(1): m.d.comb += ex_alu_result_comb.eq(self.ex_op_b | (self.ex_imm8 << 8))
                        with m.Case(2): m.d.comb += ex_alu_result_comb.eq(self.ex_op_b | (self.ex_imm8 << 16))
                        with m.Case(3): 
                            val = self.ex_op_b | (self.ex_imm8 << 24)
                            m.d.comb += ex_alu_result_comb.eq(Mux(self.ex_imm8[7], val | 0xFFFFFFFF00000000, val))
                with m.Else(): # LS or unconditional jump
                    with m.If(instruction_top3(self.ex_instruction) == 0b111):
                        m.d.comb += ex_alu_result_comb.eq(self.ex_pc + 2 + pcrel13)
                    with m.Else():
                        with m.Switch(self.ex_ls_opcode):
                            with m.Case(LSOpcode.MOVE): m.d.comb += ex_alu_result_comb.eq(ls_ea)
                            with m.Case(LSOpcode.PUSH): m.d.comb += [ex_alu_result_comb.eq(self.ex_op_b - 8), ex_store_val.eq(self.ex_op_a)]
                            with m.Case(LSOpcode.POP): m.d.comb += ex_alu_result_comb.eq(self.ex_op_b + 8)
                            with m.Case(LSOpcode.LOAD, LSOpcode.BYTE_LOAD, LSOpcode.SHORT_LOAD, LSOpcode.WORD_LOAD):
                                m.d.comb += ex_alu_result_comb.eq(ls_ea)
                            with m.Case(LSOpcode.STORE, LSOpcode.BYTE_STORE, LSOpcode.SHORT_STORE, LSOpcode.WORD_STORE):
                                m.d.comb += [ex_alu_result_comb.eq(ls_ea), ex_store_val.eq(self.ex_op_b)]
                            with m.Case(LSOpcode.JUMP_Z, LSOpcode.JUMP_C, LSOpcode.JUMP_S, LSOpcode.JUMP_GT, LSOpcode.JUMP_LT):
                                target = Mux(instruction_top2(self.ex_instruction) == 0b01, self.ex_pc + 2 + pcrel10, ls_ea)
                                m.d.comb += ex_alu_result_comb.eq(target)

        # ALU Branch resolution (happens in EX)
        with m.If(self.ex_valid & ~ex_trap):
            taken = Signal()
            with m.If(instruction_top3(self.ex_instruction) == 0b111):
                m.d.comb += taken.eq(1)
            with m.Elif(self.ex_is_jump):
                m.d.comb += taken.eq(ls_condition(self.flags, self.ex_ls_opcode))
            
            # ALU jumps and register writes to R15 (immediate/register jumps)
            with m.If((taken | (self.ex_reg_write & (self.ex_rd == 15))) & ~self.ex_lsu_read):
                m.d.comb += [ex_redirect_valid.eq(1), ex_redirect_pc.eq(ex_alu_result_comb)]

        # EX/MEM Pipeline Register
        with m.If(~stall_ex):
            m.d.sync += [
                self.mem_pc.eq(self.ex_pc),
                self.mem_valid.eq(self.ex_valid),
                self.mem_instruction.eq(self.ex_instruction),
                self.mem_alu_result.eq(ex_alu_result_comb),
                self.mem_rd.eq(self.ex_rd),
                self.mem_reg_write.eq(self.ex_reg_write & ~ex_trap),
                self.mem_reg_write2.eq(self.ex_reg_write2 & ~ex_trap),
                self.mem_rd2.eq(self.ex_rd2),
                self.mem_store_val.eq(ex_store_val),
                self.mem_lsu_read.eq(self.ex_lsu_read & ~ex_trap),
                self.mem_lsu_write.eq(self.ex_lsu_write & ~ex_trap),
                self.mem_lsu_width.eq(self.ex_lsu_width),
                self.mem_update_flags.eq(ex_update_flags & ~ex_trap),
                self.mem_new_flags.eq(ex_new_flags),
                self.mem_special_write.eq(ex_special_write & ~ex_trap),
                self.mem_special_sel.eq(ex_special_sel),
                self.mem_halt.eq(self.ex_halt & ~ex_trap),
                self.mem_trap.eq(ex_trap),
                self.mem_trap_cause.eq(ex_trap_cause),
                self.lsu_started.eq(0),
            ]
        with m.Else():
            with m.If(~stall_mem):
                m.d.sync += self.mem_valid.eq(0)

        # --- MEM Stage ---
        m.d.comb += [
            self.lsu.request_valid.eq(mem_lsu_active & ~self.lsu_started & ~trap_entry_active),
            self.lsu.request_addr.eq(self.mem_alu_result),
            self.lsu.request_write.eq(self.mem_lsu_write),
            self.lsu.request_width_bytes.eq(self.mem_lsu_width),
            self.lsu.request_store_value.eq(self.mem_store_val),
            self.special_regs.write_stb.eq(self.mem_valid & self.mem_special_write & ~trap_entry_active),
            self.special_regs.write_selector.eq(self.mem_special_sel),
            self.special_regs.write_data.eq(self.mem_store_val),
        ]
        
        with m.If(self.lsu.request_valid):
            m.d.sync += self.lsu_started.eq(1)

        # Memory Branch resolution (for LOAD R15)
        with m.If(self.mem_valid & self.mem_lsu_read & (self.mem_rd == 15) & self.lsu.response_valid):
            m.d.comb += [
                mem_redirect_valid.eq(1),
                mem_redirect_pc.eq(self.lsu.response_load_value),
            ]

        # Stall logic for memory
        m.d.comb += stall_ex.eq((mem_lsu_active & ~mem_lsu_done) | trap_entry_active)
        m.d.comb += stall_mem.eq(trap_entry_active)

        # Lockup and Halt logic
        paging_without_mmu = (self.special_regs.cpu_control & CPU_CONTROL_PAGING_ENABLE) != 0
        if self.config.enable_mmu:
            paging_without_mmu = Const(0, 1)
        
        # Trap Entry Logic
        with m.If(self.mem_valid & self.mem_trap & ~trap_entry_active):
            m.d.sync += [
                trap_entry_active.eq(1),
                trap_entry_vector.eq(self.mem_trap_cause),
                trap_entry_epc.eq(self.mem_pc),
                # Trap reporting
                self.special_regs.core_trap_write.eq(1),
                self.special_regs.core_trap_cause_data.eq(self.mem_trap_cause),
                self.special_regs.core_trap_pc_data.eq(self.mem_pc),
                self.special_regs.core_trap_fault_addr_data.eq(0),
                self.special_regs.core_trap_access_data.eq(0),
                self.special_regs.core_trap_aux_data.eq(0),
            ]
        with m.Elif(trap_entry_active):
            m.d.comb += [
                self.lsu.request_valid.eq(1),
                self.lsu.request_addr.eq(self.special_regs.interrupt_table_base + (trap_entry_vector << 3)),
                self.lsu.request_write.eq(0),
                self.lsu.request_width_bytes.eq(8),
            ]
            with m.If(self.lsu.response_valid):
                with m.If(self.lsu.response_load_value == 0):
                    m.d.sync += self.locked_up.eq(1)
                with m.Else():
                    m.d.sync += [
                        trap_entry_active.eq(0),
                        trap_entry_redirect_valid.eq(1),
                        trap_entry_redirect_pc.eq(self.lsu.response_load_value),
                        # Force supervisor mode
                        self.special_regs.core_cpu_control_write.eq(1),
                        self.special_regs.core_cpu_control_data.eq(
                            (self.special_regs.cpu_control & ~CPU_CONTROL_USER_MODE) | CPU_CONTROL_IN_INTERRUPT
                        ),
                        self.special_regs.core_interrupt_epc_write.eq(1),
                        self.special_regs.core_interrupt_epc_data.eq(trap_entry_epc),
                    ]

        # MEM/WB Pipeline Register
        with m.If(~stall_mem):
            m.d.sync += [
                self.wb_pc.eq(self.mem_pc),
                self.wb_valid.eq(self.mem_valid),
                self.wb_instruction.eq(self.mem_instruction),
                self.wb_rd.eq(self.mem_rd),
                self.wb_reg_write.eq(self.mem_reg_write),
                self.wb_rd2.eq(self.mem_rd2),
                self.wb_reg_write2.eq(self.mem_reg_write2),
                self.wb_result.eq(Mux(self.mem_lsu_read, self.lsu.response_load_value, self.mem_alu_result)),
                self.wb_result2.eq(self.lsu.response_load_value),
                self.wb_update_flags.eq(self.mem_update_flags),
                self.wb_new_flags.eq(self.mem_new_flags),
                self.wb_halt.eq(self.mem_halt),
                self.wb_trap.eq(self.mem_trap),
                self.wb_next_pc.eq(Mux(self.mem_rd == 15, Mux(self.mem_lsu_read, self.lsu.response_load_value, self.mem_alu_result), self.mem_pc + 2)),
            ]
        with m.Else():
            m.d.sync += self.wb_valid.eq(0)

        # --- WB Stage ---
        with m.If(self.wb_valid):
            # GP writes - skip r0 and r15
            for i in range(16):
                if i != 0 and i != 15:
                    with m.If(self.wb_reg_write & (self.wb_rd == i)):
                        m.d.sync += self.register_file[i].eq(self.wb_result)
                    with m.If(self.wb_reg_write2 & (self.wb_rd2 == i)):
                        m.d.sync += self.register_file[i].eq(self.wb_result2)
            
            # PC update
            m.d.sync += self.register_file[15].eq(self.wb_next_pc)

            with m.If(self.wb_update_flags):
                m.d.sync += self.flags.eq(self.wb_new_flags)
            
            # Priority: Trap/Lockup > Halt
            with m.If(paging_without_mmu | self.wb_trap):
                m.d.sync += self.locked_up.eq(1)
            with m.Elif(self.wb_halt):
                m.d.sync += self.halted.eq(1)

        # Global commit observability
        with m.If(self.wb_valid & ~self.wb_halt & ~self.wb_trap):
            m.d.comb += [
                self.commit_valid.eq(1),
                self.commit_pc.eq(self.wb_pc),
                self.commit_instruction.eq(self.wb_instruction),
            ]

        return m
