# Little-64 Linux Userspace Syscall ABI Note

This note records the Little-64 Linux syscall ABI now that the architecture has
crossed into real userspace.

The current tree now implements this ABI in the Linux port, and the replacement
hardware documentation set documents it in the privileged-architecture
chapter. In particular:

- `../hardware/privileged-architecture.md` documents the Linux userspace syscall convention.
- [arch/little64/include/asm/syscall.h](../../target/linux_port/linux/arch/little64/include/asm/syscall.h) maps the Linux syscall helpers onto the new register layout.
- [arch/little64/kernel/traps.c](../../target/linux_port/linux/arch/little64/kernel/traps.c) dispatches `TRAP_SYSCALL` through the real syscall table.

Signal delivery and `rt_sigreturn` are now implemented in the Linux port.
The current remaining ABI-adjacent limitation is the signal restorer path:
Little64 currently uses an on-stack trampoline instead of a VDSO-mapped signal
restorer because the wider VDSO infrastructure has not been added yet.

## Goals

1. Fit Linux's normal 6-argument syscall model cleanly.
2. Keep the ABI easy to implement in the current trap-entry code.
3. Avoid requiring an `orig_a0`-style saved register just to support syscall restart.
4. Stay close to the existing Little-64 C ABI where that reduces wrapper cost.
5. Use a dedicated syscall-number register, following modern 64-bit Linux practice.

## External Inspiration

Modern Linux ports converge on a small set of patterns:

- `arm64`: `svc #0`, syscall number in `x8`, args in `x0-x5`, return in `x0`
- `riscv`: `ecall`, syscall number in `a7`, args in `a0-a5`, return in `a0`
- `loongarch`: `syscall 0`, syscall number in `a7`, args in `a0-a6`, return in `a0`
- `x86_64`: `syscall`, syscall number in `rax`, args in `rdi,rsi,rdx,r10,r8,r9`, return in `rax`
- `powerpc64`: `sc`, syscall number in `r0`, args in `r3-r8`, return in `r3`

The useful common ideas are:

- dedicate one register to the syscall number,
- support 6 register arguments,
- return the result in the normal primary integer return register,
- encode errors as negative return values rather than a separate architectural error flag,
- avoid exotic pair-alignment rules on a 64-bit ABI.

## Recommended ABI

### Entry instruction

- Use the existing `SYSCALL` instruction.
- In user mode it raises `TRAP_SYSCALL`.
- Linux should treat `TRAP_SYSCALL_FROM_SUPERVISOR` as a kernel bug path, not as part of the userspace ABI.

### Register convention

| Purpose | Register |
|---|---|
| syscall number | `R4` |
| arg0 | `R10` |
| arg1 | `R9` |
| arg2 | `R8` |
| arg3 | `R7` |
| arg4 | `R6` |
| arg5 | `R5` |
| return value / `-errno` | `R1` |

Additional notes:

- `R2` is not part of the Linux syscall ABI. Leave it unchanged unless a future Little-64-specific extension needs a second return register.
- `R3` remains scratch and can stay available for vDSO or libc wrapper use.
- `R0` remains architecturally zero and is never part of the syscall ABI.

### Error convention

- On success: `R1 >= 0` or syscall-defined positive/zero result.
- On failure: `R1 = -errno`.
- No separate error register or flag bit.

This matches the dominant modern Linux model and keeps libc wrappers simple.

### Restart semantics

This layout intentionally keeps the return register separate from all syscall
argument registers.

That has one important payoff: the kernel does not need an `orig_R10`-style
saved first-argument field merely to restart interrupted syscalls. All six
original arguments remain present in `pt_regs` even after the kernel writes the
return value to `R1`.

If Little-64 later wants explicit `orig_syscall_nr` bookkeeping for tracing or
ptrace, that can be added independently, but restart correctness does not depend
on it.

## Why This Shape Fits Little-64 Better

## 1. It respects the actual C ABI

The current LLVM Little-64 C ABI uses:

- arguments 0-4 in `R10, R9, R8, R7, R6`,
- return in `R1`.

Using `R10..R6` for the first five syscall arguments means raw syscall wrappers
do not need to remap the hot-path arguments into an unrelated register bank.

Only two additional syscall-specific inputs remain:

- arg5 in `R5`,
- syscall number in `R4`.

That is a smaller mismatch than the current bring-up convention using `R1-R6`.

## 2. It avoids the hard-wired-zero trap

Any ABI that names `R0` as a writable return register is simply invalid for the
current ISA. The kernel would appear to "return" zero regardless of syscall
result.

`R1` is the only sensible primary result register because it already matches the
existing LLVM backend.

## 3. It avoids an unnecessary `orig_arg0` field

ABIs that use the same register for arg0 and return value often need an
additional saved field in `pt_regs` for restart and tracing. Little-64 can avoid
that entirely by not overlapping arg0 with the return register.

## 4. It still follows normal Linux architecture practice

This is not copying any single existing port verbatim. It is the same basic
idea adapted to Little-64's register file:

- one dedicated syscall-number register,
- six register arguments,
- one primary return register,
- negative error returns.

## Alternatives Considered

### `R8 = nr, R1-R6 = args, R1 = ret`

Pros:

- close to the current Linux bring-up stub,
- dedicated syscall-number register.

Cons:

- does not match the Little-64 C ABI argument bank,
- overlaps arg0 with the return register, so restart and tracing want extra saved state,
- gives up the main benefit of the existing compiler calling convention.

### `R1 = nr, R2-R7 = args, R1 = ret`

Pros:

- simple to describe,
- matches the very early project convention.

Cons:

- syscall number is destroyed by the return value,
- still overlaps the return register with an input role,
- weaker fit for Linux tracing, seccomp, ptrace, and restart paths.

### Keep `R8 = nr` but move to C-ABI-like args

For example: args in `R10,R9,R7,R6,R5,R4`.

This preserves a dedicated number register but splits the argument bank around
the number register, which is harder to explain and harder to treat as a normal
6-argument interface.

## Kernel Implementation Notes

For the Linux port, the practical shape should be:

1. Trap entry saves all GPRs as it already does.
2. `do_trap()` recognizes `TRAP_SYSCALL`.
3. The handler advances `regs->epc` by 2 bytes.
4. The handler reads:
   - syscall number from `regs->regs[4]`
   - args from `regs->regs[10]` down to `regs->regs[5]`
5. The return path writes the final result to `regs->regs[1]`.

The existing [entry.S](../../target/linux_port/linux/arch/little64/kernel/entry.S)
already preserves the entire register file, so this ABI does not require an
entry-path redesign.

## Userspace Wrapper Notes

Raw syscall wrappers in libc or a temporary userspace support library should:

- place the syscall number in `R4`,
- place arguments in `R10,R9,R8,R7,R6,R5`,
- execute `SYSCALL`,
- interpret `R1` in the usual Linux way.

Because the first five syscall arguments match the normal Little-64 function ABI,
the wrapper glue is smaller than with the current bring-up mapping.

## Recommended Follow-up Changes

ABI updates should still land atomically across all of the following:

1. `../hardware/privileged-architecture.md`
2. [target/linux_port/linux/arch/little64/include/asm/syscall.h](../../target/linux_port/linux/arch/little64/include/asm/syscall.h)
3. [target/linux_port/linux/arch/little64/kernel/traps.c](../../target/linux_port/linux/arch/little64/kernel/traps.c)
4. any future libc/raw-syscall helper code
5. syscall-focused Linux self-tests or emulator tests

## Current Summary

Recommended Little-64 Linux syscall ABI:

- `SYSCALL`
- `R4 = syscall number`
- `R10,R9,R8,R7,R6,R5 = args 0..5`
- `R1 = return value or -errno`

This is the cleanest fit for the current ISA, the current LLVM backend, and the
Linux kernel's restart/tracing expectations.

Current implementation notes:

- `rt_sigreturn` is wired through the Little64 arch signal path rather than
   `sys_ni_syscall`.
- the current signal restorer uses an on-stack Little64 trampoline,
   not a VDSO symbol.