#!/usr/bin/env python3
"""Patch the Little64 Arty bitstream's integrated boot ROM in place.

This script recompiles the stage-0 bootrom C source and splices the new
contents into an already-routed Vivado bitstream without re-running
synthesis, implementation, or place-and-route. Iteration on stage-0 C
code takes tens of seconds instead of the full Arty build time.

The flow is:

1.  Recompile ``target/c_boot/litex_sd_boot.c`` against the register
    header generated during the previous full build (found under
    ``<output-dir>/boot/<build-name>_sd_bootrom.work/``). Only the
    stage-0 binary and the ``*_rom.init`` file are rewritten — the
    existing routed DCP, bitstream, and LiteX gateware/ directory are
    left untouched. (The standard ``build_litex_arty_bitstream.py``
    script clears ``gateware/``, which would destroy the artifacts we
    rely on here, so this helper deliberately avoids invoking it.)
2.  Open the routed checkpoint in Vivado batch mode, overwrite the
    ``INIT_xx`` properties on the 8 ROM ``RAMB36E1`` cells with values
    decoded from the new ``.init`` file, and call ``write_bitstream``.
    Changing INIT strings does not require re-placement or re-routing.
3.  Optionally program the patched bitstream onto the board in the same
    Vivado session.

If you edit anything in the RTL / SoC configuration, the routed DCP is
stale and this helper must not be used — run the full bitstream build
via ``hdl/tools/build_litex_arty_bitstream.py`` instead.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Reuse the shared stage-0 build pipeline so this helper stays in lockstep
# with the full build path in build_litex_arty_bitstream.py. Keeping the
# compilation flow centralised is essential now that stage-0 pulls in
# liblitedram's sdram.c/accessors.c, a compat header, and extra include
# paths; re-implementing it here silently drifts.
sys.path.insert(0, str(REPO_ROOT / 'target' / 'linux_port'))
import build_sd_boot_artifacts as bsa  # noqa: E402  (path setup above)

DEFAULT_OUTPUT_DIR = REPO_ROOT / 'builddir' / 'hdl-litex-arty'
DEFAULT_BUILD_NAME = 'little64_arty_a7_35'


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print('+ ' + ' '.join(str(arg) for arg in cmd))
    result = subprocess.run(cmd, cwd=None if cwd is None else str(cwd))
    if result.returncode != 0:
        raise SystemExit(f'Command failed with exit code {result.returncode}: {cmd}')


def _run_vivado(tcl_path: Path, *, cwd: Path, vivado_settings: Path | None) -> None:
    shell_lines = ['set -e']
    if vivado_settings is not None:
        shell_lines.append(f'source "{vivado_settings}"')
    shell_lines.append(f'vivado -mode batch -source "{tcl_path.name}"')
    _run(['bash', '-lc', '\n'.join(shell_lines)], cwd=cwd)


def _regenerate_rom_init(*, output_dir: Path, build_name: str) -> Path:
    """Rebuild stage-0 and re-emit only the ROM init file.

    This deliberately does NOT invoke build_litex_arty_bitstream.py, because
    that script wipes the gateware/ directory (removing the routed DCP and
    bitstream we are trying to patch). Instead we reuse the already-generated
    stage-0 work directory from the previous full build:

        <output-dir>/boot/<build-name>_sd_bootrom.work/

    which contains the LiteX-generated register header and support files.
    We only recompile the stage-0 C source against those headers, re-link,
    and then rewrite the ROM init file in place. Nothing else is touched.

    If the SoC configuration has changed since the last full build (for
    example new peripherals, different clock, different CSR layout), this
    shortcut is not safe and a full build_litex_arty_bitstream.py run is
    required.
    """
    gateware_dir = output_dir / 'gateware'
    init_path = gateware_dir / f'{build_name}_rom.init'
    if not init_path.is_file():
        raise SystemExit(
            f'Expected ROM init not found: {init_path}. '
            'Run build_litex_arty_bitstream.py at least once before patching.'
        )

    work_dir = output_dir / 'boot' / f'{build_name}_sd_bootrom.work'
    generated_header = work_dir / 'litex_sd_boot_regs.h'
    if not generated_header.is_file():
        raise SystemExit(
            f'Generated stage-0 header not found: {generated_header}. '
            'Run build_litex_arty_bitstream.py at least once before patching.'
        )
    # liblitedram support files (generated/csr.h, litedram_compat.h, …) must
    # also have been produced by the previous full build. We don't regenerate
    # them here, because doing so would require rebuilding the SoC object,
    # which is exactly the slow path this helper exists to avoid.
    if not (work_dir / 'generated' / 'sdram_phy.h').is_file():
        raise SystemExit(
            f'Stage-0 liblitedram headers not found under {work_dir}/generated/. '
            'Run build_litex_arty_bitstream.py at least once before patching.'
        )

    # Back-compat fix-up for trees produced before the Little64-specific NOP
    # fix landed in build_sd_boot_artifacts.py. LiteX emits the unusable
    # ``#define CONFIG_CPU_NOP "nop"`` in soc.h, but the Little64 assembler
    # has no such mnemonic. Rewrite it in place so this helper keeps working
    # against older work_dir snapshots without forcing a full rebuild.
    soc_header = work_dir / 'generated' / 'soc.h'
    if soc_header.is_file():
        text = soc_header.read_text(encoding='utf-8')
        patched = text.replace(
            '#define CONFIG_CPU_NOP "nop"',
            '#define CONFIG_CPU_NOP "move R0, R0"',
        )
        if patched != text:
            soc_header.write_text(patched, encoding='utf-8')

    stage0_source = REPO_ROOT / 'target' / 'c_boot' / 'litex_sd_boot.c'
    stage0_linker = REPO_ROOT / 'target' / 'c_boot' / 'linker_litex_bootrom.ld'

    stage0_bytes = bsa._build_stage0(stage0_source, stage0_linker, work_dir, work_dir)

    # Preserve the original ROM image size so the .init line count matches
    # the BRAM organization that updatemem expects.
    previous_lines = init_path.read_text(encoding='utf-8').splitlines()
    expected_word_count = len(previous_lines)
    if expected_word_count == 0:
        raise SystemExit(f'Existing ROM init is empty: {init_path}')

    words_per_byte = 0.125  # 64-bit words
    expected_size = expected_word_count * 8
    if len(stage0_bytes) > expected_size:
        raise SystemExit(
            f'stage-0 image ({len(stage0_bytes)} B) exceeds boot ROM capacity '
            f'({expected_size} B) — the full build set the ROM size, so patching '
            'with a larger image requires rerunning build_litex_arty_bitstream.py.'
        )
    image = bytearray(expected_size)
    image[:len(stage0_bytes)] = stage0_bytes

    # Pack little-endian 64-bit words, matching the fix we applied to
    # build_litex_arty_bitstream.py (previously it was wrongly 'big').
    packed_words: list[int] = []
    for offset in range(0, len(image), 8):
        packed_words.append(int.from_bytes(image[offset:offset + 8], 'little'))

    init_path.write_text(
        '\n'.join(f'{w:016x}' for w in packed_words) + '\n',
        encoding='utf-8',
    )
    print(f'Regenerated ROM init: {init_path} ({len(packed_words)} words)')
    return init_path


def _build_bram_init_strings(init_path: Path, *, bram_count: int = 8) -> list[list[str]]:
    """Return ``bram_count`` lists of 128 ``256'h...`` INIT_xx hex strings.

    The ROM is 4096 × 64-bit words stored across 8 RAMB36E1s named
    ``rom_dat0_reg_N``, where BRAM N holds byte N of each 64-bit word
    (little-endian). Each BRAM is configured as 4K × 9 (8 data + 1 parity),
    so ``INIT_00..INIT_7F`` together cover 128 × 32 = 4096 data entries of
    one byte each.
    """
    lines = [line.strip() for line in init_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if len(lines) != 4096:
        raise SystemExit(
            f'Expected 4096 words in {init_path}, found {len(lines)}. '
            'This helper only supports the standard 32 KiB Arty boot ROM layout.'
        )
    # Decode LE 64-bit words from the init file (Vivado .init is hex MSB-first).
    words = [int(line, 16) for line in lines]

    results: list[list[str]] = []
    for bram_idx in range(bram_count):
        init_strings: list[str] = []
        for init_block in range(128):
            # 32 bytes per INIT_xx, each from a different ROM word
            byte_vals = [
                (words[init_block * 32 + n] >> (bram_idx * 8)) & 0xFF
                for n in range(32)
            ]
            # Vivado expects MSB-first hex: the first byte (word index 0 of
            # this block) lives in the LSB of the 256-bit INIT, so we render
            # bytes reversed into a hex string.
            hex_str = ''.join(f'{b:02X}' for b in reversed(byte_vals))
            init_strings.append(f"256'h{hex_str}")
        results.append(init_strings)
    return results


def _patch_bitstream_via_dcp(
    *,
    gateware_dir: Path,
    build_name: str,
    init_path: Path,
    output_bit: Path,
    vivado_settings: Path | None,
    program_after: bool,
    hw_target: str,
) -> None:
    """Rewrite BRAM INIT strings on the routed DCP and emit a new bitstream.

    This avoids ``write_mem_info`` / ``updatemem`` entirely. LiteX-generated
    bitstreams don't have processor markers that Vivado's MMI generator can
    find, so we drive the patch directly via Tcl: open the routed checkpoint,
    set ``INIT_xx`` properties on the 8 ROM RAMB36E1 cells, and
    ``write_bitstream``. Changing INIT properties does not require
    re-placement or re-routing because INIT data lives in the configuration
    frames only.
    """
    route_dcp = gateware_dir / f'{build_name}_route.dcp'
    if not route_dcp.is_file():
        raise SystemExit(
            f'Routed checkpoint not found: {route_dcp}. '
            'Run build_litex_arty_bitstream.py at least once before patching.'
        )

    per_bram_strings = _build_bram_init_strings(init_path, bram_count=8)

    tcl_lines: list[str] = [
        f'open_checkpoint {route_dcp.name}',
    ]
    for bram_idx, init_strings in enumerate(per_bram_strings):
        cell_name = f'rom_dat0_reg_{bram_idx}'
        tcl_lines.append(f'set _cell [get_cells {cell_name}]')
        for init_idx, hex_value in enumerate(init_strings):
            prop = f'INIT_{init_idx:02X}'
            tcl_lines.append(f'set_property {prop} {hex_value} $_cell')
    tcl_lines.append(f'write_bitstream -force {output_bit.name}')

    if program_after:
        tcl_lines.extend([
            'open_hw_manager',
            'connect_hw_server',
            f'open_hw_target {{{hw_target}}}' if hw_target else 'open_hw_target',
            'current_hw_device [lindex [get_hw_devices] 0]',
            'refresh_hw_device -update_hw_probes false [current_hw_device]',
            f'set_property PROGRAM.FILE {{{output_bit.name}}} [current_hw_device]',
            'program_hw_devices [current_hw_device]',
            'close_hw_manager',
        ])

    tcl_lines.append('quit')

    tcl_path = gateware_dir / f'{build_name}_patch_bootrom.tcl'
    tcl_path.write_text('\n'.join(tcl_lines) + '\n', encoding='utf-8')
    _run_vivado(tcl_path, cwd=gateware_dir, vivado_settings=vivado_settings)
    if not output_bit.is_file():
        raise SystemExit(f'Vivado did not produce the expected bitstream: {output_bit}')


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            'Patch the integrated boot ROM in an already-routed Little64 Arty '
            'bitstream by rewriting BRAM INIT properties and regenerating the '
            'bitstream from the routed DCP. Much faster than a full rebuild.'
        ),
    )
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR,
        help='Root of an existing build_litex_arty_bitstream.py output directory.')
    parser.add_argument('--build-name', default=DEFAULT_BUILD_NAME,
        help='LiteX/Vivado build name used when the original bitstream was built.')
    parser.add_argument('--vivado-settings', type=Path, default=None,
        help='Optional path to Vivado settings64.sh. Required when Vivado is not on PATH.')
    parser.add_argument('--output-bit', type=Path, default=None,
        help='Destination bitstream. Defaults to gateware/<build-name>_patched.bit.')
    parser.add_argument('--skip-rebuild', action='store_true',
        help='Skip regenerating the ROM init and reuse the existing <build-name>_rom.init.')
    parser.add_argument('--program', action='store_true',
        help='Program the patched bitstream onto the board via Vivado JTAG (volatile).')
    parser.add_argument('--vivado-hw-target', default='',
        help='Optional Vivado hw_target selector used for volatile programming.')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    output_dir = args.output_dir.resolve()
    gateware_dir = output_dir / 'gateware'
    if not gateware_dir.is_dir():
        raise SystemExit(f'Gateware directory not found: {gateware_dir}')

    if args.vivado_settings is not None:
        settings_path = args.vivado_settings.resolve()
        if not settings_path.is_file():
            raise SystemExit(f'Vivado settings script not found: {settings_path}')
        vivado_settings: Path | None = settings_path
        # Export LITEX_ENV_VIVADO so the build_litex_arty_bitstream.py child
        # process can find Vivado tooling for any incidental needs even
        # though --generate-only does not invoke Vivado itself.
        os.environ['LITEX_ENV_VIVADO'] = str(settings_path.parent)
    else:
        vivado_settings = None

    if args.skip_rebuild:
        init_path = gateware_dir / f'{args.build_name}_rom.init'
        if not init_path.is_file():
            raise SystemExit(f'Existing ROM init not found: {init_path}')
    else:
        init_path = _regenerate_rom_init(
            output_dir=output_dir,
            build_name=args.build_name,
        )

    if args.output_bit is not None:
        output_bit = args.output_bit.resolve()
    else:
        output_bit = gateware_dir / f'{args.build_name}_patched.bit'

    _patch_bitstream_via_dcp(
        gateware_dir=gateware_dir,
        build_name=args.build_name,
        init_path=init_path,
        output_bit=output_bit,
        vivado_settings=vivado_settings,
        program_after=args.program,
        hw_target=args.vivado_hw_target,
    )
    print(f'Patched bitstream written to {output_bit}')


if __name__ == '__main__':
    main()
