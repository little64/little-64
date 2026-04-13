# Privileged Architecture

This chapter defines the supervisor-visible state and the trap and interrupt model.

## Privilege Model

Little-64 currently has two privilege levels:

| Mode | Meaning |
|---|---|
| supervisor | full access to privileged instructions and supervisor memory |
| user | restricted special-register access and page-permission checks |

User mode is encoded in `cpu_control` bit 17.

## Special-Registers

Little-64 has a special register map, storing per-core configuration. The special registers numbered in the below map SHOULD be present in any compliant implementation implementing all features.
If any features are not implemented, they MUST be signaled like this:

- If the implementation does not support a MMU, it MUST ignore all writes to `page_table_root_physical`, and MUST return all-zeros or all-ones on read. The CPU MUST enter a lockup state if the software attempts to enable paging without MMU support.
- If the implementation does not implement a interrupt line, the bit corresponding to that line in the `interrupt_mask_high` register MAY always return zero, and MAY not be able to store a value.

## Special-Register Selector Encoding

`LSR` and `SSR` use the low 16 bits of `Rs1` as a special-register selector.

| Selector bits | Meaning |
|---|---|
| `14:0` | bank-local index |
| `15` | bank selector |

Selector normalization masks off all bits above bit 15.

Bank meanings:

- bank `0`: supervisor-visible system register bank
- bank `1`: user-visible bank

## Special-Register Map

### Supervisor bank

| Selector | Name | Meaning |
|---|---|---|
| `0` | `cpu_control` | CPU mode/control state |
| `1..10` | reserved | return 0 when read; ignored when written |
| `11` | `page_table_root_physical` | physical address of paging root |
| `12` | `boot_info_frame_physical` | platform-defined boot payload pointer |
| `13` | `boot_source_page_size` | platform-defined boot-source granularity |
| `14` | `boot_source_page_count` | platform-defined boot-source count |
| `15` | `hypercall_caps` | platform-defined capability/control register |
| `16` | `interrupt_table_base` | vector table base |
| `17` | `interrupt_mask` | mask bits for vectors `0..63` |
| `18` | `interrupt_mask_high` | mask bits for vectors `64..127` |
| `19` | `interrupt_states` | pending state bits for vectors `0..63` |
| `20` | `interrupt_states_high` | pending state bits for vectors `64..127` |
| `21` | `interrupt_epc` | saved return PC |
| `22` | `interrupt_eflags` | saved flag register |
| `23` | `interrupt_cpu_control` | saved `cpu_control` |
| `24` | `trap_cause` | current trap cause |
| `25` | `trap_fault_addr` | faulting VA if relevant |
| `26` | `trap_access` | `0=read`, `1=write`, `2=execute` |
| `27` | `trap_pc` | PC associated with faulting operation |
| `28` | `trap_aux` | auxiliary trap metadata |

### User bank

| Selector | Name | Meaning |
|---|---|---|
| `0x8000` | `thread_pointer` | current user-visible thread pointer |

No other user-bank selectors are currently assigned.

## User-Mode Access Rules For `LSR` And `SSR`

In user mode:

- selector `0x8000` is accessible,
- supervisor-bank selectors are privileged,
- an illegal access raises vector `2` (`TRAP_PRIVILEGED_INSTRUCTION`).

In supervisor mode, both banks are accessible.

## `cpu_control` Bit Layout

`cpu_control` is special-register selector `0`.

| Bit(s) | Name | Meaning |
|---|---|---|
| 0 | `IntEnable` | maskable hardware IRQ delivery enabled |
| 1 | `InInterrupt` | CPU is executing an interrupt/exception handler |
| `8:2` | `CurIntNum` | current vector number |
| 16 | `PagingEnable` | paging enabled |
| 17 | `UserMode` | user mode when set |

Unused bits are currently reserved. They SHOULD return zero on read, and SHOULD ignore all writes.

## Exception And IRQ Vector Layout

| Vector | Meaning |
|---|---|
| 0 | no trap pending / sentinel |
| 1 | `TRAP_EXEC_ALIGN` |
| 2 | `TRAP_PRIVILEGED_INSTRUCTION` |
| 3 | `TRAP_SYSCALL` |
| 4 | `TRAP_SYSCALL_FROM_SUPERVISOR` |
| 5 | `TRAP_PAGE_FAULT_NOT_PRESENT` |
| 6 | `TRAP_PAGE_FAULT_PERMISSION` |
| 7 | `TRAP_PAGE_FAULT_RESERVED` |
| 8 | `TRAP_PAGE_FAULT_CANONICAL` |
| 64 | reserved |
| `65..127` | platform-defined hardware IRQ space |

The low-bank and high-bank mask/state registers are both architecturally visible. Specific device assignments are platform-defined. If the CPU fails to look up the vector address for any reason, it MUST enter a lockup state.

## Interrupt Banking And Priority

The CPU stores pending and mask bits in two 64-bit banks:

- low bank: vectors `0..63`
- high bank: vectors `64..127`

Only maskable hardware IRQs use these banks. Exceptions do not alias into `interrupt_states`/`interrupt_states_high` and are not blocked by the interrupt mask registers.

### Hardware IRQ delivery

A hardware IRQ is eligible for delivery only when:

- the vector is a valid IRQ vector,
- the corresponding mask bit is set in `interrupt_mask` or `interrupt_mask_high` (unmasked), and
- `IntEnable` is set in `cpu_control`.

If the mask bit is unset, the IRQ is masked. If `IntEnable` is clear, interrupts are globally disabled.

Hardware IRQs stay latched in `interrupt_states`/`interrupt_states_high` while interrupts are disabled or masked. Delivery is deferred until the CPU can accept a maskable interrupt, at which point the highest-priority pending IRQ is delivered.

The only architected way to disable an IRQ is by clearing its mask bit. A zero-valued handler entry is not a valid disable mechanism; if the CPU takes an IRQ or exception and finds a handler address of zero, it enters lockup.

### Exception delivery

Exceptions are not subject to IRQ masking or `IntEnable`. Exception delivery is always attempted, and failure to handle an exception is fatal because forward progress is ambiguous.

### Priority rule

1. lower vector number wins,
2. exceptions outrank all device IRQs because they occupy vectors `1..8`,
3. if already inside a handler, a strictly lower-numbered vector MUST preempt the current one,
4. if an exception cannot preempt an already active exception, the CPU MUST enter a lockup state.

## Interrupt And Exception Entry Sequence

The CPU uses a shared entry protocol for both IRQs and exceptions, with a few vector-specific checks.

Shared entry behavior:

```text
1. save current cpu_control into interrupt_cpu_control
2. force supervisor mode
3. set InInterrupt = 1
4. clear IntEnable
5. set CurIntNum to the incoming vector
6. fetch handler address from interrupt_table_base + vector * 8
7. if handler fetch faults during entry, enter lockup
8. if handler address is zero, enter lockup
9. save interrupt_epc and interrupt_eflags
10. jump to the handler
```

IRQ-specific behavior:

- validate that the vector is a valid IRQ vector,
- reject the IRQ if it is masked or if `IntEnable` is clear,
- preserve the pending state bit when the IRQ is taken,
- a zero handler address enters lockup.

Exception-specific behavior:

- exceptions are not required to be unmasked or enabled,
- if no handler exists, the CPU enters lockup,
- if `trap_cause` is not already set, it is set to the exception vector,
- nested exceptions preserve an existing `trap_cause`.

Important architectural consequences:

- handler fetch runs after supervisor mode is forced,
- device IRQ pending bits are not automatically cleared on entry,
- exceptions do not use the IRQ pending banks,
- a valid handler entry is REQUIRED for exception handling,
- nested exceptions preserve the original `trap_cause` and do not overwrite it.
- A IRQ that can not be delivered (either due to being outranked or due to interrupts being disabled) MAY keep its IRQ line high until either acknowledged or until the interrupt is successfully taken. This MAY be specific to the device controlling the IRQ line; the CPU MAY expose a IRQ acknowledge signal for devices to use to lower their IRQ line.

## `IRET` Semantics

`IRET` is privileged.

If executed in supervisor mode:

```text
PC          = interrupt_epc
flags       = interrupt_eflags
cpu_control = interrupt_cpu_control
```

If executed in user mode, it raises `TRAP_PRIVILEGED_INSTRUCTION`.

## Trap Reporting Registers

| Register | Meaning |
|---|---|
| `trap_cause` | vector number associated with the exception |
| `trap_fault_addr` | faulting virtual address, when relevant |
| `trap_access` | `0=read`, `1=write`, `2=execute` |
| `trap_pc` | PC of the faulting or trapping instruction |
| `trap_aux` | auxiliary subtype/level encoding for translation faults |

## Syscall Contract

`SYSCALL` is a synchronous exception instruction.

| Current mode | Vector raised |
|---|---|
| user | `3` |
| supervisor | `4` |

The handler MAY advance execution past the trapping instruction by setting:

`interrupt_epc = saved_epc + 2`

before executing `IRET`.

### Current Linux userspace syscall ABI

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

This is a current software convention used by the Linux port and is part of the current privileged software contract.

## Standard Supervisor To User Transition Pattern

The normal transition sequence is:

1. populate `interrupt_epc` with the user entry PC,
2. populate `interrupt_eflags` with the initial user flags,
3. write the desired user `cpu_control` value into `interrupt_cpu_control` with `UserMode = 1`,
4. execute `IRET`.

## Drift Checklist

Update this chapter when any of the following change:

1. `cpu_control` bit assignments,
2. special-register selectors,
3. privilege checks for `LSR` / `SSR` / `IRET` / `STOP`,
4. exception or IRQ numbering,
5. interrupt-entry preemption rules,
6. the Linux syscall ABI.
