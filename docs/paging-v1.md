# Little-64 Paging + Boot Interface (v1)

This document defines the v1 contract for:

- minimal BIOS boot-source hypercalls,
- a 3-level radix-tree MMU,
- a realistic but fast `direct` kernel boot mode,
- stable interfaces so MMU internals can still be swapped later.

This document is the source of truth for the current paging/boot contract.

## Goals

1. Keep BIOS services minimal and hardware-realistic.
2. Keep kernel development fast (`direct` boot path).
3. Keep implementation modular so translation internals can still change later.

## Boot Modes

### `bios` mode

- CPU starts in physical mode.
- BIOS uses hypercalls to read a kernel image source.
- BIOS parses ELF, loads segments, builds initial page tables, enables paging, and jumps to kernel VA entry.

### `direct` mode

- Emulator loads a kernel ELF directly.
- Kernel image is physically loaded in low memory.
- Runtime creates a valid temporary page-table hierarchy (in RAM), enables paging, and transfers control to higher-half VA entry.
- Runtime synthesizes the same boot-info contract expected after BIOS handoff.

`direct` exists only for dev iteration speed and should match `bios` handoff semantics as closely as possible.

## BIOS Hypercalls

Exactly three services in v1:

1. `MEMINFO`
2. `GET_BOOT_SOURCE_INFO`
3. `READ_BOOT_SOURCE_PAGES`

BIOS performs all ELF logic; hypercalls only expose environment facts and page reads.

## Calling Convention

- `R1` = service ID
- `R2..R5` = inputs
- `R1` (on return) = status code
  - `0` success
  - non-zero error
- `R2..R5` (on return) = outputs

If trap-based entry is used, the trap vector/cause is platform-defined; service ABI remains register-based.

## Service Contracts

### `MEMINFO`

Inputs:

- none

Outputs:

- `R2` = physical memory base
- `R3` = physical memory size bytes
- `R4` = MMIO base hint (optional, may be 0)
- `R5` = flags/capabilities bitfield

### `GET_BOOT_SOURCE_INFO`

Inputs:

- `R2` = source selector (0 = default boot source)

Outputs:

- `R2` = source type
  - `1` block-like paged source
- `R3` = page size bytes (must be power of two)
- `R4` = total pages
- `R5` = source flags

### `READ_BOOT_SOURCE_PAGES`

Inputs:

- `R2` = start page index
- `R3` = page count
- `R4` = destination physical address
- `R5` = source selector (0 = default)

Outputs:

- `R2` = pages actually read

Errors:

- out-of-range page read,
- destination write fault/alignment issue,
- unsupported selector.

## Kernel ELF Contract

- ELF64, little-endian, `EM_LITTLE64`.
- BIOS/direct loader must honor PT_LOAD mappings and zero-fill `.bss`.
- Loader must not require identity VA=PA at runtime.
- Kernel entry is transferred in virtual space with paging already enabled.

## Paging Contract: 3-Level Radix Tree

v1 uses a fixed 3-level radix-tree design.

### Page size and indexing

- Page size: 4 KiB.
- PTE size: 8 bytes.
- Entries per table: 512.
- VA split (39-bit canonical):
   - `L2 index` = bits `[38:30]`
   - `L1 index` = bits `[29:21]`
   - `L0 index` = bits `[20:12]`
   - `page offset` = bits `[11:0]`

Canonical rule:

- bit `38` is sign-extended into bits `[63:39]`.

### Root pointer and enable state

- Paging has an explicit enable bit (control register field, platform-defined).
- Root table physical base is 4 KiB aligned.
- On enable, instruction fetch and data access must use translation.

### PTE format

PTE bits:

- bit `0`: `V` (valid)
- bit `1`: `R` (read)
- bit `2`: `W` (write)
- bit `3`: `X` (execute)
- bit `4`: `U` (user; optional policy in v1 kernel mode)
- bit `5`: `G` (global; optional in v1)
- bit `6`: `A` (accessed)
- bit `7`: `D` (dirty)
- bits `[9:8]`: software-defined (ignored by hardware)
- bits `[53:10]`: physical page number (PPN)
- bits `[63:54]`: reserved (must be zero in v1)

Interpretation:

- Non-leaf PTE: `V=1` and `R=W=X=0`; points to next-level page table.
- Leaf PTE: `V=1` and at least one of `R/W/X` set; maps a 4 KiB page.

v1 requires 4 KiB leaves only. Large pages can be added later without changing boot or hypercall contracts.

### Translation and permissions

Required behavior:

- page-based VA→PA translation through 3 levels,
- permission checks for `read/write/execute`,
- deterministic fault on missing/invalid entry,
- deterministic fault on permission failure,
- no implicit identity fallback when paging is enabled.

### A/D bit policy

Current emulator behavior:

- `A/D` bits are not auto-updated by the walker,
- translation and permission checks are still enforced,
- no implicit identity fallback is allowed while paging is enabled.

## Trap/Fault Reporting

Use special registers already exposed in CPU state:

- `trap_cause`
- `trap_fault_addr`
- `trap_access` (`0=read`, `1=write`, `2=execute`)
- `trap_pc`
- `trap_aux`

Guidance:

- reserve a contiguous cause range for paging faults,
- keep non-paging causes separate,
- avoid overloading `trap_aux` until needed.

Recommended `trap_aux` encoding for paging faults:

- bits `[3:0]`: fault subtype
   - `1` no-valid-PTE
   - `2` invalid-nonleaf
   - `3` permission
   - `4` reserved-bit-violation
   - `5` canonical-address-violation
- bits `[15:8]`: level at fault (`2`, `1`, `0`)
- remaining bits: reserved

## Suggested VA Layout

- lower half: user / identity windows (policy-defined)
- upper half: kernel image + kernel heap + kernel direct map window

Recommended kernel base for development:

- `0xFFFFFFC000000000`

This keeps higher-half semantics stable for both `bios` and `direct` paths.

## Direct Boot Mode Sequence

`direct` mode must create and use a valid temporary page-table hierarchy before entering the kernel.

### Required sequence

1. Parse/load kernel ELF PT_LOAD segments to physical RAM.
2. Allocate temporary page tables in RAM:
    - one L2 root page,
    - required L1/L0 pages for kernel mappings,
    - optional temporary identity/trampoline mapping page tables.
3. Map kernel virtual range (higher-half) to loaded physical pages with `R/X` for text and `R/W` for data.
4. Map boot info frame into kernel-visible VA (or map a temporary identity alias and pass physical pointer by ABI contract).
5. Install root pointer + enable paging.
6. Transfer control to kernel virtual entry point.
7. Keep temporary identity mapping only as long as needed for safe transition.

### Temporary mapping policy

- Temporary identity/trampoline mappings are allowed in `direct` mode.
- They must be removed or clearly documented as temporary once kernel takes over its own tables.
- Kernel is expected to create/activate its own page tables early and then replace the temporary root.

### Consistency requirement

- `direct` handoff must match `bios` handoff ABI: same register contract, same boot info semantics, same initial privilege/interrupt state.

## Modularity Contract

Keep these interfaces stable even if MMU internals change:

1. CPU translation API boundary
   - `translate(va, access) -> {ok, pa, cause}`
2. Memory access intent boundary
   - memory bus accepts `read/write/execute` intent
3. Boot mode boundary
   - launcher/session selects `bios` vs `direct`
4. Boot source boundary
   - BIOS hypercall backend is abstracted from device details

Recommended module split:

- `PageTableBuilder` (boot-time table construction only)
- `AddressTranslator` (runtime walker/TLB interface)
- `BootModeOrchestrator` (`bios`/`direct` sequencing)
- `BootSourceProvider` (hypercalls / emulated media)

Do not couple instruction dispatch code to any concrete page-table or TLB layout.

The selected v1 format is 3-level radix. Future alternatives (for example software-loaded TLB/BTR) should preserve these external contracts.

## Validation Matrix

Minimum tests for both `bios` and `direct` paths:

1. valid ELF boots to higher-half entry,
2. direct mode creates a structurally valid temporary 3-level hierarchy,
3. unmapped access raises expected trap metadata,
4. execute permission fault sets `trap_access=2`,
5. write permission fault sets `trap_access=1`,
6. boot info visible and consistent across both paths.

## Change Control

If this contract changes, update in the same change:

- `CPU_ARCH.md` (architectural semantics),
- `docs/architecture-boundaries.md` (module boundaries),
- this file (`docs/paging-v1.md`),
- relevant boot/tests docs.
