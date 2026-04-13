# Hardware Documentation Migration Map

This file records how the removed monolithic hardware docs were split into the chapter set under `docs/hardware/`.

## Removed Files

| Removed file | Reason |
|---|---|
| `CPU_ARCH.md` | Mixed ISA, privilege, MMU, boot, device, and platform details in one file |
| `docs/paging-v1.md` | Paging and boot details now belong inside the hardware chapter set |
| `docs/sphinx/pages/cpu_arch.md` | Wrapper for removed file |
| `docs/sphinx/pages/paging_v1.md` | Wrapper for removed file |

## Section Mapping

| Old source | New home |
|---|---|
| Register file, flags, bit conventions | `foundations.md` |
| Instruction formats and opcode overview | `instruction-set.md` |
| LS / GP / `LDI` / branch semantics | `instruction-set.md` |
| `LLR` / `SCR` rules | `instruction-set.md` |
| Special registers and `cpu_control` | `privileged-architecture.md` |
| Exceptions, IRQs, `IRET`, user mode | `privileged-architecture.md` |
| Syscall ABI notes | `privileged-architecture.md` |
| Memory-access semantics | `memory-translation-and-boot.md` |
| Paging model and translation-fault semantics | `memory-translation-and-boot.md` |
| Software TLB behavior | `../emulator/runtime-model.md` |
| Trap metadata and page-fault causes | `memory-translation-and-boot.md` |
| BIOS and direct boot contracts | `../emulator/boot-and-loader.md` |
| Platform memory map | `../emulator/virtual-platform.md` |
| UART, timer, PV block, DTB contract | `../emulator/virtual-platform.md` |
| Update checklist and change control | `compliance-and-change-control.md` |

## Files Not Replaced By This Hardware Plan

These docs remain separate because they are not pure hardware-reference docs:

- `docs/assembly-syntax.md`
- `docs/architecture-boundaries.md`
- `docs/device-framework.md`
- `docs/tracing.md`
- `docs/vscode-integration.md`
- `GUI_DEBUGGER.md`

## Migration Rule

Migration is complete when new hardware-facing work MUST update the chapter named in the mapping table rather than reintroducing a new monolithic architecture file.
