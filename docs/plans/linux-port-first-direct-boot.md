# Little64 Linux Port: First Direct-Boot Plan

Saved for first real boot-attempt execution.

## Goal

Reach the first observable Linux boot milestone in the emulator via direct ELF loading:

- kernel image loads as ELF,
- control transfers into kernel entry and early init,
- serial output appears (even if boot later panics due to missing runtime pieces).

The direct boot method is:

- `./builddir/little-64 --boot-mode=direct target/linux_port/build/vmlinux`

Or via helper script:

- `target/linux_port/boot_direct.sh`

## Current State Snapshot

- `vmlinux` links cleanly with no warnings/errors.
- Many architecture integration points are currently bring-up placeholders.
- Kallsyms PC-relative mode is disabled for Little64 in `scripts/link-vmlinux.sh` (required for higher-half layout).

## Missing Port Work (By Priority)

## P0: Required for stable first boot progress

1. Interrupt controller + timer path
- Implement `init_IRQ()` and wire a real interrupt source.
- Provide a working clockevent/clocksource path so scheduler tick and timekeeping progress reliably.

2. Real context switch and task state handling
- Replace `__switch_to()` bring-up shim with real save/restore logic.
- Validate stack, return path, and register preservation through first schedule event.

3. Page fault / trap accuracy in early boot
- Verify trap metadata and fault causes from the emulator MMU path match Linux expectations.
- Confirm execute/write/read faults map to expected kernel handlers.

4. Console reliability
- Ensure early serial output remains usable across paging transition and interrupt enable.
- Keep `console=ttyS0 earlycon ignore_loglevel` available for first-boot diagnostics.

## P1: Needed after first visible boot output

1. Ptrace and FP register state
- Replace ptrace placeholder functions and FP state stubs with correct implementations.

2. Delay/time calibration
- Replace fixed calibration fallback in delay/time stubs with measured values.

3. CPU feature reporting
- Replace static `cpuinfo` output with detected/declared architectural capabilities.

## P2: Hardening and parity

1. BIOS-mode parity
- Revalidate that `bios` and `direct` handoff contracts are equivalent.

2. Device tree and platform population robustness
- Expand DT-driven init checks; fail clearly for missing required nodes.

3. Bring-up stub retirement
- Remove stub warnings and this plan's placeholder list as each subsystem lands.

## First Direct-Boot Attempt Checklist

1. Build emulator
- `meson compile -C builddir`

2. Build kernel ELF (single-threaded for deterministic bring-up logs)
- `target/linux_port/build.sh vmlinux -j1`

3. Run direct boot
- `target/linux_port/boot_direct.sh`
 - This writes full boot events to `/tmp/little64_boot_events.log` by default.

4. Analyze control-flow failures
- `target/linux_port/analyze_lockup_flow.py --log /tmp/little64_boot_events.log`

5. Capture first-failure evidence
- record first serial lines,
- record whether panic is before/after `start_kernel`,
- record the first unresolved arch dependency.

## Recommended First-Boot Kernel Config Adjustments

If not already set in the active config, bias toward verbose early diagnostics:

- `CONFIG_CMDLINE_BOOL=y`
- `CONFIG_CMDLINE="console=ttyS0 earlycon ignore_loglevel"`
- Prefer periodic tick for bring-up simplicity over nohz while IRQ/timer is incomplete.

## Exit Criteria (Initial Milestone)

The first direct-boot milestone is complete when all are true:

1. The emulator reaches kernel entry via direct ELF load.
2. Linux prints early boot messages on serial.
3. Any panic/failure is attributable to a specific unimplemented arch subsystem (not loader/link corruption).
