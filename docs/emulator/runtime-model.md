# Emulator Runtime Model

This chapter documents the current Little-64 emulator runtime behavior that is
observable but not part of the ISA contract.

## Cycle Order

The current runtime performs work in this order each CPU cycle:

```text
1. fetch one 16-bit instruction
2. execute one instruction
3. force R0 = 0
4. if IRQ delivery is enabled, deliver at most one highest-priority pending IRQ
5. tick all attached devices
6. advance the virtual clock
```

This ordering matters for interrupt latency, timer behavior, and single-step
debugging.

## Post-Load CPU State

After a program load the emulator initializes CPU state as follows:

| State | Value |
|---|---|
| `flags` | `0` |
| `cpu_control` | `0` |
| interrupt mask/state registers | `0` |
| trap registers | `0` |
| user thread pointer | `0` |
| page-table root | `0` |
| boot-source page metadata | populated from the configured boot source |
| hypercall capability register | minimal boot capability bit set |
| `R13` | top of loaded RAM minus 8 |
| `R15` | loader-selected entry point |

The exact values for the boot payload and entry point depend on the selected
load path and are described in `boot-and-loader.md`.

## Self-Loop Lockup Detection

The runtime includes an implementation-specific lockup detector:

- if control returns to the same PC,
- and interrupts are disabled,
- and no forward progress is possible,

the emulator stops execution and records a self-loop lockup event.

This is a runtime safety feature, not an ISA rule.

## Software Translation Cache

The current emulator implements a software TLB in front of the page-table
walker.

| Property | Value |
|---|---|
| entries | 64 |
| organization | direct-mapped |
| granularity | 4 KiB pages |
| index | low 6 bits of `vpage = VA >> 12` |

Each entry caches:

- virtual page number,
- physical page base,
- accumulated access-permission bits,
- whether the translation was cached as user-accessible.

### Observable behavior

1. a successful translation populates the cache,
2. repeated accesses to the same page can accumulate permission bits,
3. aliasing virtual pages evict one another based on the direct-mapped index,
4. reset and program load flush the cache,
5. `SSR` to special-register selector `0` or `11` flushes the cache.

This structure is implementation-specific and must not be treated as a hardware
ISA requirement.

## Reservation Invalidation Behavior

The current implementation invalidates an `LLR` reservation when any successful
memory write overlaps the reserved 8-byte region, regardless of write width.

That behavior is architecturally visible to software, but the mechanism for
tracking the reservation remains an implementation detail.

## Sources And Proving Tests

Primary implementation sources:

- `host/emulator/cpu.cpp`
- `host/emulator/address_translator.cpp`

Primary proving tests:

- `tests/target/test_cpu_special.cpp`
- `tests/host/test_tlb.cpp`
- `tests/host/test_paging.cpp`