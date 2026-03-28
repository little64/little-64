# vbcc Little-64 Backend — Porting Progress

This document tracks the phased progress of porting vbcc to Little-64.

Each phase is a distinct milestone. Mark items `[x]` when complete.

---

## Phase 0 — Setup

Get vbcc source, understand the architecture, and study reference backends.

- [ ] Clone vbcc source as git submodule: `git submodule add https://github.com/easyaspi314/vbcc compilers/vbcc/vbcc`
- [ ] Read vbcc backend manual (Section 13 of `vbcc/doc/vbcc.pdf`)
- [ ] Study M68k backend: `vbcc/machines/m68k.h` and `m68k.c`
- [ ] Study PowerPC backend: `vbcc/machines/ppc.h` and `ppc.c` (alternative reference)
- [ ] Skim Little-64 ISA reference: `CPU_ARCH.md`
- [ ] Review calling convention: `CPU_ARCH.md` — Calling Convention section
- [ ] Review pseudo-instructions: `docs/assembly-syntax.md` — CALL, RET, LDI64

**Completion criterion**: You can explain vbcc's backend structure and how registers, types, and instructions are defined.

---

## Phase 1 — Skeleton Backend

Implement a minimal backend that compiles functions to valid Little-64 code (even if trivial).

### Register File and Type Sizes

- [ ] Define register names in `target/machine.h`:
  - R0 (zero), R1-R5 (general purpose, caller-saved)
  - R6-R10 (general purpose, callee-saved)
  - R11-R12 (address registers, callee-saved)
  - R13 (SP), R14 (LR), R15 (PC)
  - Which registers are available for allocation?
  - Which are reserved (SP, LR, PC)?

- [ ] Define type sizes in `target/machine.h`:
  - `char` = 8 bits
  - `short` = 16 bits
  - `int` = 64 bits (Little-64 is 64-bit!)
  - `long` = 64 bits
  - `pointer` = 64 bits

### Calling Convention

- [ ] Define argument passing in `target/machine.h`:
  - Arguments 0–4: R10, R9, R8, R7, R6 (in order)
  - Arguments 5+: On stack (caller-pushed, oldest first)

- [ ] Define return values in `target/machine.h`:
  - Single value (≤64 bits): R1
  - Pair value (128 bits): R1 (low), R2 (high)
  - Larger values: By reference (caller allocates)

- [ ] Define stack layout:
  - SP (R13) points to top of stack (lowest allocated address)
  - Stack grows downward (SP decreases on allocation)
  - Saved registers stored below local variables

### Minimal Code Generation

- [ ] Implement `target/machine.c` stub:
  - Function prologue (save callee-saved registers, allocate locals)
  - Function epilogue (restore callee-saved registers, deallocate, return)
  - Load immediate constants using LDI64 pseudo-instruction
  - Emit NOP or placeholder instructions (real code generation deferred to Phase 2)

- [ ] Build vbcc with Little-64 backend:
  ```bash
  cp compilers/vbcc/target/machine.* compilers/vbcc/vbcc/machines/
  cd compilers/vbcc/vbcc
  make
  ```

- [ ] Verify build succeeds and vbcc recognizes `-target=little64`

**Completion criterion**: `vbcc -target=little64 simple.c -o simple.s` produces valid Little-64 assembly (even if only function prologues/epilogues).

---

## Phase 2 — Code Generation

Implement instruction selection for real computation.

### Memory Operations

- [ ] Load/store with register addressing: `LOAD [Rs], Rd` / `STORE [Rs], Rd`
- [ ] Load/store with offset: `LOAD [Rs+N], Rd` (N ∈ {0,2,4,6})
- [ ] PC-relative load/store: `LOAD @label, Rd` / `STORE @label, Rd`
- [ ] PUSH/POP for stack operations (via PUSH/POP pseudo-instructions)
- [ ] Byte/short/word variants: BYTE_LOAD, SHORT_LOAD, WORD_LOAD, etc.
- [ ] Pointer dereferencing: translate `*ptr` to LOAD/STORE

### Arithmetic and Logic

- [ ] ADD, SUB, TEST for addition/subtraction/comparison
- [ ] AND, OR, XOR for bitwise operations
- [ ] Shifts: SLL, SRL, SRA (register shift count)
- [ ] Shift immediates: SLLI, SRLI, SRAI (4-bit immediate count)
- [ ] Constant loading via LDI64: translate large immediates to pseudo-instruction

### Branches and Comparisons

- [ ] Conditional branches: JUMP.Z, JUMP.C, JUMP.S, JUMP.GT, JUMP.LT
- [ ] Set condition codes (Zero, Carry, Sign) via TEST and ALU ops
- [ ] PC-relative branch targets (±511 instruction range)

### Function Calls

- [ ] CALL pseudo-instruction for function calls
- [ ] RET pseudo-instruction for returns
- [ ] Argument passing: load R10–R6, then stack if needed
- [ ] Return value handling: place result in R1 (or R1+R2 for 128-bit)
- [ ] Callee-saved register preservation

### Control Flow

- [ ] If-else statements (branches based on flags)
- [ ] Loops (branch back to loop start)
- [ ] Switch statements (jump table if supported, else if-cascade)

**Completion criterion**: Compile a function with arithmetic, memory access, calls, and branches. Assemble and verify on emulator.

---

## Phase 3 — Library Call Stubs

Provide software implementations of missing hardware operations.

- [ ] `__muldi3`: 64-bit signed multiply (A × B)
  - Implement in Little-64 assembly or C
  - Store in `asm/libcalls/muldi3.asm`
  - Test: `a * b` where a, b are non-zero

- [ ] `__udivdi3`: 64-bit unsigned divide (A ÷ B)
  - Implement in Little-64 assembly or C
  - Store in `asm/libcalls/udivdi3.asm`
  - Test: `a / b` where a > b

- [ ] `__divdi3`: 64-bit signed divide (A ÷ B)
  - Implement in Little-64 assembly or C
  - Store in `asm/libcalls/divdi3.asm`
  - Test: negative operands

- [ ] `__moddi3`: 64-bit signed modulo (A % B)
  - Implement in Little-64 assembly or C
  - Store in `asm/libcalls/moddi3.asm`
  - Test: `a % b` with various signs

- [ ] Create a simple C runtime library stub (`libc.a` or similar)
  - Link against vbcc-compiled code
  - Provides libcall symbols

**Completion criterion**: Compile a function using `int a = 12 * 34; printf("%ld\n", a);` and it runs correctly on emulator.

---

## Phase 4 — Validation

Test the compiler against real-world C code patterns.

### Basic Functionality

- [ ] **Hello World**: Compile and run a simple program that prints via serial/stdout
  - Tests: constants, function calls, I/O

- [ ] **Recursion**: Compile Fibonacci or factorial function
  - Tests: function prologue/epilogue, call/return, register preservation

- [ ] **Struct Access**: Compile code with struct members
  - Tests: addressing modes, offset calculations

- [ ] **Array Access**: Compile code with array indexing
  - Tests: pointer arithmetic, scaling (if supported)

- [ ] **Pointer Arithmetic**: Compile code with `ptr++`, `ptr += offset`
  - Tests: addition/subtraction on pointers

- [ ] **Multiply/Divide**: Compile code using `*`, `/`, `%`
  - Tests: libcall stubs for software multiply/divide

- [ ] **Bitwise Operations**: Compile code with `&`, `|`, `^`, `<<`, `>>`
  - Tests: logical operations, shifts

- [ ] **Loop Constructs**: for, while, do-while loops
  - Tests: branch generation, loop condition testing

- [ ] **Conditionals**: if, if-else, nested conditionals
  - Tests: flag-based branching

**Completion criterion**: All above tests compile and run correctly on the emulator.

---

## Phase 5 — Kernel Readiness

Prepare the compiler for OS/kernel code.

- [ ] **Interrupt Handlers**: Compile a function that can serve as an ISR
  - Tests: proper register saving, IRET support
  - Ensure no function prologue/epilogue optimization breaks ISR semantics

- [ ] **Inline Assembly**: Verify vbcc supports inline assembly (if needed)
  - Test: `__asm__("instruction")` or similar syntax
  - Allows hand-coded kernel primitives alongside compiled code

- [ ] **ABI Interoperability**: Compile mixed C + hand-written assembly
  - Write a C function, call hand-written assembly, verify calling convention
  - Write hand-written assembly, call C function, verify calling convention

- [ ] **Memory Barriers / Special Registers**: If needed, test access to special registers via `LSR`/`SSR`
  - Example: `LSR 0, R1` to read `cpu_control`

- [ ] **Volatile Semantics**: Test volatile variables (memory-mapped I/O)
  - Ensure compiler doesn't optimize away volatile reads/writes

- [ ] **Performance Profile**: Measure code size and performance
  - Compare against hand-written assembly for same functions
  - Identify optimization gaps

**Completion criterion**: Kernel initialization code can be compiled, linked, and run on the emulator. Mixed C/asm programs work correctly.

---

## Summary

| Phase | Focus | Timeline | Blocker |
|-------|-------|----------|---------|
| 0 | Setup & learning | 1–2 weeks | None |
| 1 | Minimal backend | 1–2 weeks | vbcc source |
| 2 | Real code gen | 2–3 weeks | Phase 1 complete |
| 3 | Libcalls | 1 week | Phase 2 complete |
| 4 | Validation | 2–3 weeks | Phase 3 complete |
| 5 | Kernel | 1–2 weeks | Phase 4 complete |

**Overall estimate**: 8–14 weeks for full kernel-ready compiler.

Each completed phase unlocks the next. Document blockers here if they arise.
