/*
 * Little-64 Backend for vbcc
 *
 * Target machine header: register definitions, type sizes, calling convention.
 * This file defines the target architecture for the vbcc compiler.
 */

#ifndef LITTLE64_MACHINE_H
#define LITTLE64_MACHINE_H

/* ========================================================================
 * Register Definitions
 * ======================================================================== */

/* Registers available for allocation (caller-saved, general purpose) */
#define R1 1   /* General purpose, caller-saved */
#define R2 2   /* General purpose, caller-saved */
#define R3 3   /* General purpose, caller-saved */
#define R4 4   /* General purpose, caller-saved */
#define R5 5   /* General purpose, caller-saved */

/* Callee-saved registers */
#define R6  6  /* General purpose, callee-saved */
#define R7  7  /* General purpose, callee-saved */
#define R8  8  /* General purpose, callee-saved */
#define R9  9  /* General purpose, callee-saved */
#define R10 10 /* General purpose, callee-saved */

/* Special registers */
#define R11 11 /* Address register, callee-saved */
#define R12 12 /* Address register, callee-saved */
#define R13 13 /* Stack pointer (SP) */
#define R14 14 /* Link register (LR) */
#define R15 15 /* Program counter (PC) */
#define R0  0  /* Zero register (writes discarded, reads return 0) */

/* Total registers: 16 (R0–R15) */
#define MAXREG 16

/* Special register indices for calling convention */
#define SP_REG 13 /* Stack pointer */
#define LR_REG 14 /* Link register */
#define PC_REG 15 /* Program counter */
#define ZERO_REG 0 /* Zero register */

/* ========================================================================
 * Type Sizes
 * ======================================================================== */

/* Little-64 is a 64-bit architecture */

#define CHAR_SIZE 1           /* char = 8 bits */
#define SHORT_SIZE 2          /* short = 16 bits */
#define INT_SIZE 8            /* int = 64 bits (on 64-bit arch!) */
#define LONG_SIZE 8           /* long = 64 bits */
#define LONGLONG_SIZE 8       /* long long = 64 bits */
#define POINTER_SIZE 8        /* pointer = 64 bits */

#define CHAR_ALIGN 1
#define SHORT_ALIGN 2
#define INT_ALIGN 8
#define LONG_ALIGN 8
#define LONGLONG_ALIGN 8
#define POINTER_ALIGN 8

/* Floating point (not yet supported by Little-64 ISA) */
#define FLOAT_SIZE 0          /* Not supported */
#define DOUBLE_SIZE 0         /* Not supported */
#define LONGDOUBLE_SIZE 0     /* Not supported */

/* ========================================================================
 * Calling Convention
 * ======================================================================== */

/*
 * Argument Passing:
 *  - Arguments 0–4: R10, R9, R8, R7, R6 (in order, first arg in R10)
 *  - Arguments 5+: On stack (caller-pushed, oldest first)
 *
 * Return Values:
 *  - Single value (≤64 bits): In R1
 *  - Pair (128 bits): R1 (low 64), R2 (high 64)
 *  - Larger: By reference (caller allocates, pointer passed as first arg)
 *
 * Register Preservation:
 *  - Caller-saved (caller must save if needed after call): R1–R5
 *  - Callee-saved (callee must restore before return): R6–R14
 *  - Reserved: R0 (zero), R13 (SP), R14 (LR), R15 (PC)
 *
 * Stack:
 *  - Grows downward (SP decreases on allocation)
 *  - SP points to the top of stack (lowest allocated address)
 *  - Stack alignment: 8 bytes (natural for 64-bit values)
 */

/* Argument registers in order (first arg, second arg, etc.) */
#define ARG_REG_1 10  /* R10 */
#define ARG_REG_2 9   /* R9 */
#define ARG_REG_3 8   /* R8 */
#define ARG_REG_4 7   /* R7 */
#define ARG_REG_5 6   /* R6 */
#define NUM_ARG_REGS 5

/* Return value registers */
#define RETURN_REG_LOW 1  /* R1 for 64-bit or low 64 bits of 128-bit */
#define RETURN_REG_HIGH 2 /* R2 for high 64 bits of 128-bit */

/* ========================================================================
 * Code Generation Parameters
 * ======================================================================== */

/* Stack frame alignment (in bytes) */
#define STACK_ALIGN 8

/* Minimum frame size (prologue saves at least these registers) */
#define MIN_FRAME_SIZE 8  /* At minimum, save LR */

/* Maximum immediate value that fits in LDI (8-bit) */
#define MAX_LDI_IMM 255

/* Branch offset range (in instruction units, ±511) */
#define BRANCH_RANGE_MIN -511
#define BRANCH_RANGE_MAX 511

/* ========================================================================
 * Instruction Format / Encoding Details
 * ======================================================================== */

/*
 * Little-64 instruction formats (16-bit):
 *
 * Format 00 (LS Register):     [00][OPCODE_LS 4b][OFFSET 2b][Rs1 4b][Rd 4b]
 * Format 01 (LS PC-Relative):  [01][OPCODE_LS 4b][PC_REL 6b][Rd 4b]
 * Format 10 (LDI):             [10][SHIFT 2b][IMM8 8b][Rd 4b]
 * Format 11 (GP ALU):          [11][OPCODE_GP 6b][Rs1 4b][Rd 4b]
 *
 * All instructions are 16 bits (2 bytes). Code density is tight.
 */

/* Instruction size (in bytes) */
#define INSTRUCTION_SIZE 2

/* Maximum number of instructions in a function prologue */
#define MAX_PROLOGUE_INSTRS 16

/* ========================================================================
 * Addressing Modes
 * ======================================================================== */

/*
 * Register + Immediate Offset (Format 00):
 *   [Rs1 + OFFSET*2]  where OFFSET ∈ {0, 1, 2, 3} → effective offset ∈ {0, 2, 4, 6}
 *
 * Register (Format 00, OFFSET=0):
 *   [Rs1]
 *
 * PC-Relative (Format 01):
 *   @label  or  @±N  (6-bit signed offset, ±31 instruction units)
 *
 * Immediate (Format 10, LDI):
 *   #imm8   (8-bit immediate, loaded via LDI)
 *
 * Large Immediate (pseudo-instruction, LDI64):
 *   #imm64  (64-bit immediate, expanded to LOAD + JUMP + embedded data)
 */

/* Maximum offset in register mode (in bytes) */
#define MAX_REG_OFFSET 6

/* ========================================================================
 * Opcodes (Reference)
 * ======================================================================== */

/* LS Format Opcodes (0–15) */
#define OP_LOAD       0
#define OP_STORE      1
#define OP_PUSH       2
#define OP_POP        3
#define OP_MOVE       4
#define OP_BYTE_LOAD  5
#define OP_BYTE_STORE 6
#define OP_SHORT_LOAD 7
#define OP_SHORT_STORE 8
#define OP_WORD_LOAD  9
#define OP_WORD_STORE 10
#define OP_JUMP_Z     11
#define OP_JUMP_C     12
#define OP_JUMP_S     13
#define OP_JUMP_GT    14
#define OP_JUMP_LT    15

/* GP Format Opcodes (selected) */
#define OP_ADD   0
#define OP_SUB   1
#define OP_TEST  2
#define OP_AND   16
#define OP_OR    17
#define OP_XOR   18
#define OP_SLL   20
#define OP_SRL   21
#define OP_SRA   22
#define OP_SLLI  23
#define OP_SRLI  24
#define OP_SRAI  25

/* ========================================================================
 * Pseudo-Instructions (Generated by Assembler)
 * ======================================================================== */

/*
 * JAL @target        → MOVE R15+2, R14 ; JUMP @target
 * CALL @target       → PUSH R14 ; MOVE R15+2, R14 ; JUMP @target ; POP R14
 * RET                → MOVE R14, R15
 * LDI64 #imm64, Rd   → LOAD @+1, Rd ; JUMP @+4 ; .long imm64
 */

/* ========================================================================
 * Target Identification
 * ======================================================================== */

#define TARGET_NAME "little64"
#define TARGET_DESCRIPTION "Little-64 minimal 64-bit CPU ISA"

#endif /* LITTLE64_MACHINE_H */
