# Foundations

This chapter defines the baseline terms and invariants used by the rest of the hardware reference.

## Scope

Little-64 is a 64-bit ISA with a fixed 16-bit instruction width, 16 architectural general registers, a small three-flag status register, two privilege levels, and a paged virtual-memory model.

This chapter covers only the cross-cutting rules every later chapter depends on. Instruction semantics, privilege machinery, paging, and devices are defined in later chapters.

## Baseline Architectural Facts

| Property | Value |
|---|---|
| Integer register width | 64 bits |
| Instruction width | 16 bits |
| Byte order | little-endian |
| Addressing model | byte-addressed |
| Architectural GPR count | 16 |
| Architectural PC | `R15` |
| Architectural SP | `R13` |
| Architectural LR | `R14` |
| Privilege levels | supervisor, user |

## Register Naming And Numbering

| Register | Role | Type |
|---|---|---|
| `R0` | hard-wired zero | architectural contract |
| `R1` | general-purpose, primary integer return in current software ABI | architectural register / software convention |
| `R2` | general-purpose | architectural register |
| `R3` | general-purpose | architectural register |
| `R4` | general-purpose, Linux syscall number in current software ABI | architectural register / software convention |
| `R5` | general-purpose, Linux syscall arg5 in current software ABI | architectural register / software convention |
| `R6` | general-purpose, Linux syscall arg4 in current software ABI | architectural register / software convention |
| `R7` | general-purpose, Linux syscall arg3 in current software ABI | architectural register / software convention |
| `R8` | general-purpose, Linux syscall arg2 in current software ABI | architectural register / software convention |
| `R9` | general-purpose, Linux syscall arg1 in current software ABI | architectural register / software convention |
| `R10` | general-purpose, Linux syscall arg0 in current software ABI | architectural register / software convention |
| `R11` | general-purpose, current frame-pointer convention | architectural register / software convention |
| `R12` | general-purpose, current scratch convention | architectural register / software convention |
| `R13` | stack pointer | architectural register / software convention |
| `R14` | link register | architectural register / software convention |
| `R15` | program counter | architectural register |

`R0` is enforced as zero after execution. Software MAY encode writes to `R0`, but the architectural result is still zero.

## Flags Register

The architecturally visible flag bits are:

| Bit | Name | Meaning |
|---|---|---|
| 0 | `Z` | result is zero |
| 1 | `C` | carry for addition, borrow for subtraction and subtraction-derived tests |
| 2 | `S` | result sign bit is set |

There is no overflow flag.

## Notation Rules

The later chapters use the following notation consistently:

| Notation | Meaning |
|---|---|
| `bits[a:b]` | inclusive bit slice from `a` down to `b` |
| `VA` | virtual address |
| `PA` | physical address |
| `PC` | architectural program counter (`R15`) |
| `post_increment_pc` | PC value after instruction fetch has already advanced by 2 bytes |
| `vector` | interrupt or exception number stored in `cpu_control[8:2]` |
| `selector` | low 16-bit special-register selector used by `LSR` / `SSR` |

All addresses in this documentation are byte addresses unless a section says otherwise.

## Architectural Invariants

These rules are relied on by software across the current tree:

1. Instruction fetch width is always 16 bits.
2. `R0` always reads as zero.
3. Memory is little-endian.
4. Conditional branches consume the current flag register; they do not perform a hidden comparison.
5. There are only two architectural privilege states: supervisor and user.
6. The current interrupt number is encoded in `cpu_control[8:2]` as a 7-bit field.

## Architectural Reset Expectations

The following CPU-visible reset properties are REQUIRED:

| State | Value |
|---|---|
| `flags` | `0` |
| `cpu_control` | `0` |
| interrupt mask/state registers | `0` |
| trap registers | `0` |
| user thread pointer | `0` |
| page-table root | `0` |

The initial `PC`, initial `SP`, boot payload, and other platform environment details are platform-defined. All other registers may take any value, software MUST NOT assume they are cleared to zero on reset.

## High-Level Architectural Execution Model

```text
          +-------------------+
          |  fetch 16-bit op  |
          +---------+---------+
                    |
                    v
          +-------------------+
          | execute semantics |
          +---------+---------+
                    |
                    v
          +-------------------+
          | update architected|
          | CPU state         |
          +-------------------+
```

## Lockup state

There can be cases in which it is impossible for the CPU to continue executing. In such cases, as defined by this specification, the CPU MUST enter lockup state. The CPU MUST NOT enter a lockup state for a reason not specified here. If there is a logical pathway for such a lockup state that is missing from this specification, the specification has a bug, and it should be corrected.

The exact manner of lockup is not defined, but SHOULD follow one of these patterns:

- If the CPU contains detection hardware for a lockup state, it SHOULD clock-gate itself until reset.
- If the CPU does not contain detection hardware for a specific lockup state, it may enter a state in which it takes an exception every cycle. In such a case, the CPU SHOULD minimize its own affect on the memory bus, and SHOULD NOT affect other CPU cores, if the system has several processors on the same memory bus.
- If the CPU is emulated, it MUST cause a emulation exit, or similar suitable procedure.

The CPU MAY choose to do any of the above for any lockup reason, but SHOULD aim to minimize power consumption and bus traffic if it is in lockup. The CPU MUST be able to recover from lockup from a hardware reset.

## Drift Checklist

Update this chapter when any of the following change:

1. register numbering or naming,
2. flag bits or flag meanings,
3. reset-state defaults,
4. baseline architectural notation used by later chapters.