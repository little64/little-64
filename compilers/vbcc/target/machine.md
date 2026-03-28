# Little-64 Machine Description for vbcc

This file describes the Little-64 target architecture for vbcc.

## Overview

**Little-64** is a minimal 64-bit CPU ISA designed for educational purposes and
kernel implementation. It features:

- **16 registers** (R0–R15): R0 is zero, R1–R12 are general/address, R13=SP, R14=LR, R15=PC
- **16-bit instructions** in four formats: LS Register, LS PC-Relative, LDI (Load Immediate), GP (ALU)
- **No hardware multiply/divide** (provided via software libcalls)
- **Conditional branches** with flag-based conditions (Z, C, S, GT, LT)
- **Downward-growing stack** with stack pointer in R13
- **Calling convention**: Arguments in R10–R6, return values in R1 (or R1+R2 for 128-bit)

## Register File

### General Purpose Registers

| Register | Role | Caller-Saved | Usage |
|----------|------|--------------|-------|
| R0 | Zero | — | Always zero; writes discarded |
| R1–R5 | General | Yes | Caller-saved, free for allocation |
| R6–R10 | General | No | Callee-saved, free for allocation |
| R11–R12 | Address | No | Callee-saved, address computation |
| R13 | Stack Pointer | No | Reserved; stack management |
| R14 | Link Register | No | Reserved; function returns |
| R15 | Program Counter | — | Reserved; control flow |

**Available for register allocation**: R1–R12
**Reserved**: R0 (zero), R13 (SP), R14 (LR), R15 (PC)

### Calling Convention

**Argument passing:**
- Arguments 0–4: R10, R9, R8, R7, R6 (in order)
- Arguments 5+: On stack (pushed by caller)

**Return values:**
- Single (≤64 bits): R1
- Pair (128 bits): R1 (low), R2 (high)
- Larger: By reference (caller allocates, passes pointer)

**Preserved across calls:**
- Caller-saved (caller preserves): R1–R5
- Callee-saved (callee preserves): R6–R12, R14

## Instruction Formats

### Format 00 — LS Register

```
[00][OPCODE_LS 4b][OFFSET 2b][Rs1 4b][Rd 4b]
```

Used for: LOAD, STORE, PUSH, POP, MOVE, BYTE_LOAD, BYTE_STORE, etc.

**Addressing modes:**
- `[Rs1]` — base address
- `[Rs1+N]` — base + offset (N ∈ {0, 2, 4, 6} bytes)

### Format 01 — LS PC-Relative

```
[01][OPCODE_LS 4b][PC_REL 6b][Rd 4b]
```

Used for: LOAD, STORE, PUSH, POP (PC-relative), and JUMP.* (branches)

**Addressing modes:**
- `@label` — PC-relative offset to label
- `@±N` — PC-relative offset (N is offset in instruction units)

**Branch range**: ±511 instructions (±1022 bytes) from next instruction

### Format 10 — LDI (Load Immediate)

```
[10][SHIFT 2b][IMM8 8b][Rd 4b]
```

Used for: LDI, LDI.S1, LDI.S2, LDI.S3 (building 64-bit immediates)

**Behavior:**
- SHIFT=0: `Rd = IMM8` (clears Rd)
- SHIFT>0: `Rd |= (IMM8 << (SHIFT×8))`

### Format 11 — GP (ALU)

```
[11][OPCODE_GP 6b][Rs1 4b][Rd 4b]
```

Used for: ADD, SUB, TEST, AND, OR, XOR, SLL, SRL, SRA, SLLI, SRLI, SRAI, etc.

## Type Sizes

| Type | Size |
|------|------|
| `char` | 1 byte |
| `short` | 2 bytes |
| `int` | 8 bytes (64-bit arch) |
| `long` | 8 bytes |
| `pointer` | 8 bytes |

**Alignment**: Natural alignment (char=1, short=2, int/long/ptr=8)

## Pseudo-Instructions

The assembler provides several pseudo-instructions that expand to real instructions:

| Pseudo | Expands To |
|--------|-----------|
| `JAL @label` | MOVE R15+2, R14 ; JUMP @label |
| `CALL @label` | PUSH R14 ; MOVE R15+2, R14 ; JUMP @label ; POP R14 |
| `RET` | MOVE R14, R15 |
| `LDI64 #imm64, Rd` | LOAD @+1, Rd ; JUMP @+4 ; .long imm64 |

## Stack Layout

**Stack grows downward** (SP decreases on allocation):

```
Address
   |
   v
+-------+
| Arg N |  (SP before CALL)
+-------+
| Arg 5 |
+-------+
|  LR   |  (saved by CALL pseudo-instr)
+-------+
| Local |
| Var 1 |  (allocated by PUSH or SUBI SP, #size)
| Local |
| Var 2 |
+-------+
   ^
   |
  SP    (SP after function prologue)
```

**Stack frame management:**
- Prologue: Save LR and callee-saved registers; allocate locals
- Epilogue: Deallocate locals; restore registers; return

## Libcalls (Software Implementations)

Since Little-64 has no hardware multiply/divide, vbcc must emit library calls:

| Operation | Function | Signature |
|-----------|----------|-----------|
| `a * b` | `__muldi3` | `int64_t __muldi3(int64_t a, int64_t b)` |
| `a / b` (signed) | `__divdi3` | `int64_t __divdi3(int64_t a, int64_t b)` |
| `a / b` (unsigned) | `__udivdi3` | `uint64_t __udivdi3(uint64_t a, uint64_t b)` |
| `a % b` (signed) | `__moddi3` | `int64_t __moddi3(int64_t a, int64_t b)` |
| `a % b` (unsigned) | `__umoddi3` | `uint64_t __umoddi3(uint64_t a, uint64_t b)` |

These are provided by a linked runtime library (implemented in Phase 3).

## Addressing Mode Summary

| Mode | Format | Example | Notes |
|------|--------|---------|-------|
| Register | Format 00 | `[R7]` | Direct register |
| Register + Offset | Format 00 | `[R7+4]` | Offset ∈ {0,2,4,6} bytes |
| PC-Relative | Format 01 | `@label` | For LOAD, STORE, JUMP |
| Immediate | Format 10 | `#255` | 8-bit via LDI |
| Large Immediate | Pseudo | `#0x1234567890ABCDEF` | Expanded to LDI64 |

## Constraints & Limitations

1. **No hardware multiply/divide** — Requires libcall infrastructure
2. **Limited branch range** — ±511 instructions; large functions may need branch splitting
3. **Limited immediate** — Only 8-bit LDI; larger values via LDI64 or register-relative addressing
4. **No indexed addressing** — No `[Rs1 + Rs2*scale]` mode; must be synthesized
5. **No floating point** — Not supported by ISA

## Code Generation Strategy

### Register Allocation

- **Prefer caller-saved** (R1–R5) for temporary values (cheaper to spill)
- **Use callee-saved** (R6–R12) for variables that live long (amortize save/restore cost)
- **SP (R13), LR (R14), PC (R15) are reserved** — never allocate

### Instruction Selection

- **Load immediates via LDI64** for any 64-bit constant
- **Use pseudo-instructions** (CALL, RET, LDI64) — assembler handles expansion
- **Minimize memory accesses** — register allocation is critical
- **Branch splitting** — if function exceeds branch range, emit intermediate jumps

### Optimization Opportunities

- **Constant folding** — Evaluate compile-time constants, reduce instruction count
- **Dead code elimination** — Remove unreachable code
- **Function inlining** — Inline small functions to reduce call overhead
- **Register coalescing** — Minimize moves between registers

## References

- **CPU_ARCH.md** — Full ISA reference (register file, instruction formats, opcodes)
- **docs/assembly-syntax.md** — Assembler syntax reference
- **vbcc Backend Manual (Section 13)** — How to write a vbcc backend
