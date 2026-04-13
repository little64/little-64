# Little-64 Hardware Reference

This directory is the primary hardware-facing architecture reference for Little-64.

It replaces the removed monolithic documents:

- `CPU_ARCH.md`
- `docs/paging-v1.md`

The replacement is intentionally split by concern boundary so hardware, kernel, and toolchain work can all reference the same architecture without growing another catch-all file.

## What This Set Covers

This hardware reference defines the current guest-visible contract for:

1. core architectural invariants,
2. instruction encoding and execution semantics,
3. privilege, traps, and interrupt delivery,
4. memory translation and architectural fault reporting,
5. the boundary between core ISA behavior and platform-defined behavior,
6. change-control rules for keeping the docs aligned with code and tests.

## Document Status Vocabulary

The chapters distinguish between the following statement types:

- **Architectural contract**: behavior that software MAY rely on and that a hardware implementation MUST reproduce.
- **Platform-defined behavior**: behavior intentionally left outside the core ISA and defined by a specific platform environment.
- **Software convention**: an ABI or tooling convention used by the current stack.

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this hardware specification are to be interpreted as described in [RFC 2119](https://datatracker.ietf.org/doc/html/rfc2119).

## Chapter Map

| File | Scope |
|---|---|
| `foundations.md` | Baseline architectural facts, terminology, register model, flags, and invariants |
| `instruction-set.md` | Instruction formats, opcode maps, arithmetic/dataflow semantics, jumps, atomics, and flag behavior |
| `privileged-architecture.md` | `cpu_control`, special registers, privilege checks, interrupt/exception delivery, trap metadata, and syscall ABI |
| `memory-translation-and-boot.md` | Memory-access rules, 3-level paging model, and architectural translation-fault semantics |
| `platform-and-devices.md` | Core ISA platform boundary and architecturally reserved platform-integration space |
| `compliance-and-change-control.md` | Source-of-truth hierarchy, update rules, and drift-prevention guidance |
| `migration.md` | Mapping from the removed monolithic docs into the new chapter set |

## Recommended Read Order

1. `../README.md`
2. `README.md`
3. `foundations.md`
4. `instruction-set.md`
5. `privileged-architecture.md`
6. `memory-translation-and-boot.md`
7. `platform-and-devices.md`
8. `compliance-and-change-control.md`
9. `migration.md`

## Quick Architecture Summary

| Topic | Current value |
|---|---|
| Integer width | 64-bit |
| Instruction width | 16-bit fixed-width |
| General registers | 16 (`R0..R15`) |
| Zero register | `R0` |
| Flags | `Z`, `C`, `S` |
| Privilege levels | supervisor, user |
| Paging model | 3-level radix tree, 4 KiB base page, 39-bit canonical VA |

Implementation-specific runtime and platform behavior is intentionally excluded from this hardware reference.

## Relationship To Other Docs

This hardware reference does not replace the tooling or workflow docs.

Still separate by design:

- `../assembly-syntax.md`
- `../architecture-boundaries.md`
- `../device-framework.md`
- `../tracing.md`
- `../vscode-integration.md`
- `../../GUI_DEBUGGER.md`

## Maintenance Rule

When behavior changes, contributors MUST update the affected chapter in this directory in the same change, and MUST update any supporting workflow docs if the behavior also affects tooling, tests, or contributor instructions.