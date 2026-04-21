#!/usr/bin/env python3
"""Reusable Arty ILA insertion + capture helper.

This script replaces hand-written, per-experiment Tcl files with a small
registry of probe presets and a Vivado batch driver. It inserts an ILA into an
already routed checkpoint (ECO flow), so iterating on probe sets does not
require re-running synthesis.

Typical usage::

    # Insert the default internal-bus ILA (no resynthesis):
    little64 hdl arty-ila insert --preset internal-bus

    # Program the board and run a capture with a simple trigger:
    little64 hdl arty-ila capture --preset internal-bus \
        --trigger 'lsu_bus_watchdog_timeout=1'

    # Discover candidate net names when building a new preset:
    little64 hdl arty-ila list-nets --filter '*watchdog*' --filter '*i_bus*cyc*'

Assumptions:
    - A previous ``build_litex_arty_bitstream.py`` run left a routed checkpoint
      under ``builddir/hdl-litex-arty/gateware/<name>_route.dcp``. Use the
      ``--build-dir`` / ``--build-name`` flags to target other experiments.
    - ``vivado`` is on ``PATH`` (source your ``settings64.sh`` first) or use
      ``--vivado-settings``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from little64.paths import repo_root
from little64.vivado_support import run_command_with_optional_source

REPO_ROOT = repo_root()
DEFAULT_BUILD_DIR = REPO_ROOT / 'builddir' / 'hdl-litex-arty'
DEFAULT_BUILD_NAME = 'little64_arty_a7_35'
DEFAULT_CLOCK_NET = 'sys_clk'


# ---------------------------------------------------------------------------
# Probe preset registry.
#
# Each preset is a name -> {depth, probes}. Probes are resolved in Vivado by
# matching against routed net names via ``get_nets -hier -filter {NAME =~ ...}``.
# Patterns use Vivado glob syntax (``*`` is the wildcard). Multiple patterns
# in a single probe are concatenated into one bus-valued probe port, so
# related signals (e.g. ``cyc``, ``stb``, ``ack``) can share a capture slot.
#
# IMPORTANT: Net names can drift between synthesis runs. Use ``list-nets``
# to discover current names before blaming a preset for returning no matches.
# ---------------------------------------------------------------------------

PRESETS: dict[str, dict] = {
    # Minimal "is the CPU waiting on a bus request?" preset. Focuses on
    # signals that survive Vivado's synthesis on the LiteX/Arty build:
    # top-level CPU bus address/write-enable, plus internal LSU/frontend
    # state + watchdog indicators. Deliberately small so ECO placement on
    # an Arty A7-35T succeeds.
    'cpu-hang': {
        'depth': 1024,
        'clock_net': DEFAULT_CLOCK_NET,
        'probes': [
            # Architectural halt / lockup.
            {'name': 'halted',    'nets': ['*core/halted_reg_n_0']},
            {'name': 'locked_up', 'nets': ['*core/locked_up_reg_n_0']},
            # Frontend state machine (4-bit pipeline FSM) and request-in-
            # flight. We match the flip-flop output nets directly; regex
            # mode in Vivado makes bracket indices literal.
            {'name': 'frontend_state',  'nets': ['*core/frontend/state_reg[0]',
                                                  '*core/frontend/state_reg[1]',
                                                  '*core/frontend/state_reg[2]',
                                                  '*core/frontend/state_reg[3]']},
            {'name': 'frontend_req_valid',  'nets': ['*core/frontend/request_valid_reg_0']},
            {'name': 'frontend_line_valid', 'nets': ['*core/frontend/line_valid']},
            {'name': 'frontend_watchdog',   'nets': ['*core/frontend/watchdog_fire']},
            # LSU state machine (2-bit FSM: IDLE/FIRST/SECOND) and beat
            # sequencing. Bare ``state[*]`` survives for the LSU; ``state_reg``
            # variants are fanout replicas of the same bit.
            {'name': 'lsu_state',        'nets': ['*core/lsu/state[0]',
                                                   '*core/lsu/state[1]']},
            {'name': 'lsu_beat_started', 'nets': ['*core/lsu/beat_started']},
            # Watchdog counter MSB is a 1-bit early-warning of imminent
            # timeout without probing the full counter.
            {'name': 'frontend_wd_msb', 'nets': ['*core/frontend/watchdog_counter_reg[10]']},
            {'name': 'lsu_wd_msb',      'nets': ['*core/lsu/watchdog_counter_reg[10]']},
            # Top-level CPU bus write-enable. The cyc/stb/ack handshake has
            # been absorbed into the LiteX bus wrapper and no longer exists
            # as a named net on the 50 MHz V3 build.
            {'name': 'd_bus_we',  'nets': ['little64_litex_cpu_top/d_bus_we']},
            # A few low MMIO address bits distinguish CSR offsets (e.g. UART
            # rxtx vs txfull) without consuming the full 61-bit address.
            {'name': 'd_bus_adr_lo', 'nets': ['little64_litex_cpu_top/d_bus_adr[2]',
                                               'little64_litex_cpu_top/d_bus_adr[3]',
                                               'little64_litex_cpu_top/d_bus_adr[4]',
                                               'little64_litex_cpu_top/d_bus_adr[5]',
                                               'little64_litex_cpu_top/d_bus_adr[6]',
                                               'little64_litex_cpu_top/d_bus_adr[7]']},
        ],
    },
    # Legacy names preserved so earlier `--preset` values keep working;
    # both map to the same target signals after the synthesis-survival audit.
    'internal-bus': {
        'depth': 1024,
        'clock_net': DEFAULT_CLOCK_NET,
        'probes': [
            {'name': 'halted',              'nets': ['*core/halted_reg_n_0']},
            {'name': 'locked_up',           'nets': ['*core/locked_up_reg_n_0']},
            {'name': 'frontend_watchdog',   'nets': ['*core/frontend/watchdog_fire']},
            {'name': 'frontend_req_valid',  'nets': ['*core/frontend/request_valid_reg_0']},
            {'name': 'frontend_line_valid', 'nets': ['*core/frontend/line_valid']},
            {'name': 'lsu_state',           'nets': ['*core/lsu/state[0]', '*core/lsu/state[1]']},
            {'name': 'lsu_beat_started',    'nets': ['*core/lsu/beat_started']},
            {'name': 'lsu_wd_msb',          'nets': ['*core/lsu/watchdog_counter_reg[10]']},
            {'name': 'd_bus_we',            'nets': ['little64_litex_cpu_top/d_bus_we']},
        ],
    },
    # "Show me the failing bus transaction" preset. Trades off the detailed
    # pipeline FSM bits that we already characterised in the first capture
    # for the full d_bus transaction payload (address, write data, byte
    # enables). Use this to identify WHICH store is hanging and WHAT the
    # slave should have ack'd. The cyc/stb/ack/err handshake nets do not
    # survive synthesis on the LiteX wrapper, so we use lsu/state +
    # lsu/beat_started + lsu/watchdog_counter_reg[10] as indirect handshake
    # evidence (same nets that were useful in the cpu-hang capture).
    #
    # Address bits on d_bus are word-indexed (8-byte words), so the physical
    # byte address of a captured transaction is (d_bus_adr << 3).
    'cpu-hang-bus': {
        'depth': 1024,
        'clock_net': DEFAULT_CLOCK_NET,
        'probes': [
            {'name': 'halted',           'nets': ['*core/halted_reg_n_0']},
            {'name': 'locked_up',        'nets': ['*core/locked_up_reg_n_0']},
            {'name': 'lsu_state',        'nets': ['*core/lsu/state[0]',
                                                   '*core/lsu/state[1]']},
            {'name': 'lsu_beat_started', 'nets': ['*core/lsu/beat_started']},
            {'name': 'lsu_wd_msb',       'nets': ['*core/lsu/watchdog_counter_reg[10]']},
            {'name': 'd_bus_we',         'nets': ['little64_litex_cpu_top/d_bus_we']},
            {'name': 'd_bus_sel',        'nets': [
                f'little64_litex_cpu_top/d_bus_sel[{i}]' for i in range(8)
            ]},
            {'name': 'd_bus_adr',        'nets': [
                f'little64_litex_cpu_top/d_bus_adr[{i}]' for i in range(61)
            ]},
            {'name': 'd_bus_dat_w',      'nets': [
                f'little64_litex_cpu_top/d_bus_dat_w[{i}]' for i in range(64)
            ]},
        ],
    },
    # "Who issued the hanging store?" preset. Same bus-watchdog trigger
    # surface as cpu-hang-bus, but spends the probe budget on the commit
    # PC instead of the store payload and byte-enables. Useful after
    # cpu-hang-bus has already identified the failing transaction (d_bus_we,
    # d_bus_adr) and we only need the program counter that produced it.
    #
    # commit_pc is sampled at the core (V3) boundary and freezes at the PC
    # of the last committed instruction while the LSU is stuck, so the
    # failing store is at a small (ISA-dependent) positive offset from the
    # captured value when the hang starts.
    'cpu-hang-pc': {
        'depth': 1024,
        'clock_net': DEFAULT_CLOCK_NET,
        'probes': [
            {'name': 'halted',           'nets': ['*core/halted_reg_n_0']},
            {'name': 'locked_up',        'nets': ['*core/locked_up_reg_n_0']},
            {'name': 'lsu_state',        'nets': ['*core/lsu/state[0]',
                                                   '*core/lsu/state[1]']},
            {'name': 'lsu_beat_started', 'nets': ['*core/lsu/beat_started']},
            {'name': 'lsu_wd_msb',       'nets': ['*core/lsu/watchdog_counter_reg[10]']},
            {'name': 'd_bus_we',         'nets': ['little64_litex_cpu_top/d_bus_we']},
            {'name': 'd_bus_adr',        'nets': [
                f'little64_litex_cpu_top/d_bus_adr[{i}]' for i in range(61)
            ]},
            {'name': 'commit_pc',        'nets': [
                f'*core/commit_pc[{i}]' for i in range(64)
            ]},
        ],
    },
}


# ---------------------------------------------------------------------------
# Probe specification dataclasses.
# ---------------------------------------------------------------------------

@dataclass
class ProbeSpec:
    name: str
    nets: list[str]


@dataclass
class IlaSpec:
    depth: int
    clock_net: str
    probes: list[ProbeSpec] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> 'IlaSpec':
        if 'probes' not in data or not data['probes']:
            raise ValueError('ILA spec must contain at least one probe')
        probes = [
            ProbeSpec(name=p['name'], nets=list(p['nets']))
            for p in data['probes']
        ]
        return cls(
            depth=int(data.get('depth', 1024)),
            clock_net=str(data.get('clock_net', DEFAULT_CLOCK_NET)),
            probes=probes,
        )


def _load_spec(preset: str | None, probes_file: Path | None) -> IlaSpec:
    if probes_file is not None:
        data = json.loads(probes_file.read_text())
    elif preset is not None:
        if preset not in PRESETS:
            raise SystemExit(
                f'Unknown preset {preset!r}. Known presets: {sorted(PRESETS)}'
            )
        data = PRESETS[preset]
    else:
        raise SystemExit('Either --preset or --probes-file is required')
    return IlaSpec.from_dict(data)


# ---------------------------------------------------------------------------
# Vivado invocation plumbing.
# ---------------------------------------------------------------------------

def _source_and_run(vivado_settings: Path | None, command: list[str], *, cwd: Path) -> int:
    """Run ``command`` under ``vivado_settings`` sourcing if provided."""

    return run_command_with_optional_source(command, cwd=cwd, source_script=vivado_settings)


def _resolve_checkpoint(build_dir: Path, build_name: str,
                         explicit: Path | None, from_stage: str) -> Path:
    if explicit is not None:
        path = explicit.expanduser().resolve()
        if not path.exists():
            raise SystemExit(f'Checkpoint not found: {path}')
        return path
    stage_map = {
        'synth': f'{build_name}_synth.dcp',
        'place': f'{build_name}_place.dcp',
        'route': f'{build_name}_route.dcp',
    }
    filename = stage_map.get(from_stage)
    if filename is None:
        raise SystemExit(f'Unknown stage {from_stage!r}; expected one of {sorted(stage_map)}')
    guess = build_dir / 'gateware' / filename
    if not guess.exists():
        raise SystemExit(
            f'Expected checkpoint at {guess} does not exist. Run '
            'build_litex_arty_bitstream.py first or pass --checkpoint explicitly.'
        )
    return guess


# ---------------------------------------------------------------------------
# Tcl generation.
# ---------------------------------------------------------------------------

_HEADER = """# Auto-generated by `little64 hdl arty-ila`. Do not edit by hand.
# Regenerate with ``arty_ila.py insert`` to modify probes.
set ::errorInfo ""
"""


def _glob_to_regex(pattern: str) -> str:
    """Convert a shell-like glob pattern to a Vivado-compatible anchored regex.

    Vivado's ``get_nets -hier -filter {NAME =~ <pat>}`` defaults to Tcl
    ``string match`` glob semantics, where ``[...]`` is a character class.
    That breaks on Verilog bit-index names like ``d_bus_adr[0]``. Adding
    ``-regexp`` to ``get_nets`` switches the filter to regex mode, where
    brackets need to be escaped instead. This helper translates presets that
    were written in a natural glob style so both ``*`` wildcards and literal
    ``[index]`` subscripts behave as expected.
    """

    out: list[str] = ['^']
    for ch in pattern:
        if ch == '*':
            out.append('.*')
        elif ch == '?':
            out.append('.')
        elif ch in r'\.^$+(){}|':
            out.append('\\' + ch)
        elif ch == '[':
            out.append(r'\[')
        elif ch == ']':
            out.append(r'\]')
        else:
            out.append(ch)
    out.append('$')
    return ''.join(out)


def _tcl_insert(spec: IlaSpec, checkpoint: Path, bit_path: Path,
                ltx_path: Path, eco_dcp: Path) -> str:
    probe_tcl_lines: list[str] = []
    # Probe 0 is implicitly created by create_debug_core. We reuse it for the
    # first probe and create additional debug ports for the rest. Empty-match
    # patterns fail loudly rather than silently producing a zero-width probe.
    for index, probe in enumerate(spec.probes):
        probe_port = f'probe{index}'
        per_pattern_resolution: list[str] = []
        pattern_var_names: list[str] = []
        for pat_index, pat in enumerate(probe.nets):
            var = f'matched_{index}_{pat_index}'
            pattern_var_names.append(f'${var}')
            regex = _glob_to_regex(pat)
            per_pattern_resolution.append(
                f'set {var} [get_nets -hier -regexp -filter {{NAME =~ {{{regex}}}}}]\n'
                f'if {{[llength ${var}] == 0}} {{\n'
                f'    error "Probe {probe.name!r}: no nets matched pattern {pat!r}"\n'
                f'}}'
            )
        resolutions = '\n'.join(per_pattern_resolution)
        if index == 0:
            port_setup = (
                f'set_property port_width $probe_width_{index} '
                f'[get_debug_ports u_ila_0/{probe_port}]'
            )
        else:
            port_setup = (
                f'create_debug_port u_ila_0 probe\n'
                f'set_property port_width $probe_width_{index} '
                f'[get_debug_ports u_ila_0/{probe_port}]'
            )
        probe_tcl_lines.append(
            f'# --- probe {index}: {probe.name} ---\n'
            f'{resolutions}\n'
            f'set probe_nets_{index} [concat {" ".join(pattern_var_names)}]\n'
            f'set probe_width_{index} [llength $probe_nets_{index}]\n'
            f'puts "probe {probe.name} (index {index}): width=$probe_width_{index}"\n'
            f'{port_setup}\n'
            f'connect_debug_port u_ila_0/{probe_port} $probe_nets_{index}\n'
        )

    probes_block = '\n'.join(probe_tcl_lines)

    return (
        _HEADER
        + textwrap.dedent(f"""
        open_checkpoint {{{checkpoint}}}

        # Run opt_design first so Vivado has a consistent logic-optimized
        # netlist (and any IP libraries loaded) before we splice in the ILA.
        # This is required when starting from a synth.dcp where dbg_hub has
        # not yet been materialized.
        opt_design

        create_debug_core u_ila_0 ila
        set_property C_DATA_DEPTH {spec.depth} [get_debug_cores u_ila_0]
        set_property C_TRIGIN_EN false [get_debug_cores u_ila_0]

        set clock_nets [get_nets -hier -filter {{NAME =~ {spec.clock_net}}}]
        if {{[llength $clock_nets] == 0}} {{
            error "ILA clock net not found: {spec.clock_net}"
        }}
        set_property port_width 1 [get_debug_ports u_ila_0/clk]
        connect_debug_port u_ila_0/clk [lindex $clock_nets 0]
        """)
        + probes_block
        + textwrap.dedent(f"""

        implement_debug_core [get_debug_cores u_ila_0]
        # Re-run opt_design AFTER the debug core has been implemented so the
        # dbg_hub's generated netlist is integrated into the optimized design
        # before placement. Without this second opt_design, place_design
        # errors out with "Found one or more debug core instances that needs
        # to be (re)generated" on Vivado 2020+.
        opt_design
        place_design
        route_design

        report_route_status
        report_timing_summary -file {{{bit_path.with_suffix('.timing.rpt')}}}

        write_debug_probes -force {{{ltx_path}}}
        write_checkpoint -force {{{eco_dcp}}}
        write_bitstream -force {{{bit_path}}}
        """)
    )


def _tcl_list_nets(checkpoint: Path, patterns: list[str], limit: int) -> str:
    regexes = [_glob_to_regex(p) for p in patterns]
    return (
        _HEADER
        + textwrap.dedent(f"""
        open_checkpoint {{{checkpoint}}}
        set matched [list]
        foreach pat [list {' '.join('{' + r + '}' for r in regexes)}] {{
            foreach net [get_nets -hier -regexp -filter "NAME =~ $pat"] {{
                lappend matched [get_property NAME $net]
            }}
        }}
        set matched [lsort -unique $matched]
        puts "Matched [llength $matched] nets (showing up to {limit}):"
        set count 0
        foreach name $matched {{
            if {{$count >= {limit}}} {{ break }}
            puts "  $name"
            incr count
        }}
        """)
    )


def _tcl_capture(bit: Path, ltx: Path, output_csv: Path,
                 trigger_exprs: list[str], window: int,
                 hw_server_url: str) -> str:
    # Each expression is "probe_name=value" where value is 0, 1, or a hex
    # integer. We attach a basic compare to each referenced probe. Since the
    # ILA is instantiated without advanced trigger/capture control units, the
    # hw_ila-level CAPTURE_MODE / TRIGGER_MODE properties are read-only and
    # fixed to ALWAYS / BASIC_ONLY respectively, so we must not try to set
    # them. We only drive the properties that are actually writable:
    # CONTROL.DATA_DEPTH, CONTROL.TRIGGER_POSITION, and per-probe
    # TRIGGER_COMPARE_VALUE.
    trigger_setup: list[str] = []
    for expr in trigger_exprs:
        if '=' not in expr:
            raise SystemExit(f'Invalid trigger expression (want name=value): {expr}')
        name, value = expr.split('=', 1)
        name = name.strip()
        value = value.strip()
        if value in ('0', '1'):
            compare = f"eq 1'b{value}"
        else:
            # Accept 0x... / decimal; pass through as a hex compare. The probe
            # width is discovered at runtime from the probe object.
            ival = int(value, 0)
            compare = f"eq 32'h{ival:x}"
        trigger_setup.append(
            f'set _probe [get_hw_probes {name} -of_objects $hw_ila]\n'
            f'        if {{[llength $_probe] == 0}} {{\n'
            f'            error "trigger probe {name} not found on ILA"\n'
            f'        }}\n'
            f'        set_property TRIGGER_COMPARE_VALUE {{{compare}}} $_probe'
        )
    trigger_block = '\n        '.join(trigger_setup) if trigger_setup else '# no triggers -> immediate capture'

    return (
        _HEADER
        + textwrap.dedent(f"""
        open_hw_manager
        connect_hw_server -url {hw_server_url}
        open_hw_target
        set hw_device [lindex [get_hw_devices] 0]
        current_hw_device $hw_device
        set_property PROGRAM.FILE {{{bit}}} $hw_device
        set_property PROBES.FILE {{{ltx}}} $hw_device
        set_property FULL_PROBES.FILE {{{ltx}}} $hw_device
        program_hw_devices $hw_device
        refresh_hw_device $hw_device

        set hw_ila [lindex [get_hw_ilas -of_objects $hw_device] 0]
        set_property CONTROL.TRIGGER_POSITION {int(window // 2)} $hw_ila
        set_property CONTROL.DATA_DEPTH {window} $hw_ila
        {trigger_block}
        run_hw_ila $hw_ila
        wait_on_hw_ila -timeout 60 $hw_ila
        display_hw_ila_data [upload_hw_ila_data $hw_ila]
        write_hw_ila_data -csv_file -force {{{output_csv}}} [current_hw_ila_data $hw_ila]

        close_hw_manager
        """)
    )


# ---------------------------------------------------------------------------
# Subcommands.
# ---------------------------------------------------------------------------

def cmd_insert(args: argparse.Namespace) -> int:
    spec = _load_spec(args.preset, args.probes_file)
    build_dir: Path = args.build_dir
    build_name: str = args.build_name
    checkpoint = _resolve_checkpoint(build_dir, build_name, args.checkpoint, args.from_stage)

    tag = args.tag or (args.preset or 'custom').replace('_', '-')
    gateware_dir = checkpoint.parent
    bit_path = gateware_dir / f'{build_name}_{tag}_ila.bit'
    ltx_path = gateware_dir / f'{build_name}_{tag}_ila.ltx'
    eco_dcp = gateware_dir / f'{build_name}_{tag}_ila_route.dcp'
    tcl_path = gateware_dir / f'{build_name}_{tag}_ila_insert.tcl'

    tcl_path.write_text(_tcl_insert(spec, checkpoint, bit_path, ltx_path, eco_dcp))
    print(f'[arty_ila] Wrote Tcl: {tcl_path}')
    print(f'[arty_ila] Target bitstream: {bit_path}')
    print(f'[arty_ila] Target probes:    {ltx_path}')

    if args.dry_run:
        return 0

    rc = _source_and_run(
        args.vivado_settings,
        ['vivado', '-mode', 'batch', '-source', str(tcl_path)],
        cwd=gateware_dir,
    )
    if rc != 0:
        raise SystemExit(f'Vivado ILA insertion failed (rc={rc})')
    return 0


def cmd_list_nets(args: argparse.Namespace) -> int:
    checkpoint = _resolve_checkpoint(args.build_dir, args.build_name, args.checkpoint, args.from_stage)
    gateware_dir = checkpoint.parent
    tcl_path = gateware_dir / f'{args.build_name}_list_nets.tcl'
    tcl_path.write_text(_tcl_list_nets(checkpoint, args.filter or ['*'], args.limit))
    print(f'[arty_ila] Wrote Tcl: {tcl_path}')
    if args.dry_run:
        return 0
    rc = _source_and_run(
        args.vivado_settings,
        ['vivado', '-mode', 'batch', '-source', str(tcl_path)],
        cwd=gateware_dir,
    )
    return rc


def cmd_capture(args: argparse.Namespace) -> int:
    spec_name = args.preset or 'custom'
    tag = args.tag or spec_name
    gateware_dir = (args.build_dir / 'gateware').resolve()
    bit = args.bit or (gateware_dir / f'{args.build_name}_{tag}_ila.bit')
    ltx = args.ltx or (gateware_dir / f'{args.build_name}_{tag}_ila.ltx')
    if not bit.exists() or not ltx.exists():
        raise SystemExit(
            f'Missing ILA artifacts: {bit}, {ltx}. Run ``arty_ila.py insert`` first.'
        )
    output_csv = args.output or (gateware_dir / f'{args.build_name}_{tag}_capture.csv')
    tcl_path = gateware_dir / f'{args.build_name}_{tag}_capture.tcl'
    tcl_path.write_text(
        _tcl_capture(bit, ltx, output_csv, args.trigger or [], args.window, args.hw_server_url)
    )
    print(f'[arty_ila] Wrote Tcl: {tcl_path}')
    print(f'[arty_ila] Output CSV: {output_csv}')
    if args.dry_run:
        return 0
    rc = _source_and_run(
        args.vivado_settings,
        ['vivado', '-mode', 'batch', '-source', str(tcl_path)],
        cwd=gateware_dir,
    )
    return rc


def cmd_presets(_: argparse.Namespace) -> int:
    for name, data in PRESETS.items():
        probe_names = ', '.join(p['name'] for p in data['probes'])
        print(f'{name}: depth={data["depth"]} probes=[{probe_names}]')
    return 0


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--build-dir', type=Path, default=DEFAULT_BUILD_DIR,
                        help='Arty build directory (default: %(default)s)')
    parser.add_argument('--build-name', default=DEFAULT_BUILD_NAME,
                        help='Build name prefix (default: %(default)s)')
    parser.add_argument('--checkpoint', type=Path, default=None,
                        help='Explicit checkpoint (overrides build-dir/name/stage)')
    parser.add_argument('--from-stage', choices=('synth', 'place', 'route'),
                        default='synth',
                        help='Checkpoint stage to start from (default: synth). '
                             'Use synth when the design lacks a pre-instantiated '
                             'dbg_hub IP (typical LiteX build); place/route are '
                             'faster ECO paths if the design already contains one.')
    parser.add_argument('--vivado-settings', type=Path, default=None,
                        help='Optional settings64.sh to source before invoking vivado')
    parser.add_argument('--dry-run', action='store_true',
                        help='Emit the generated Tcl only, do not invoke Vivado')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Reusable Arty post-route ILA insertion + capture helper.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            '''\
            Presets are defined in this file. Run ``arty_ila.py presets`` to list them,
            or pass ``--probes-file path/to/spec.json`` with a JSON document matching
            the in-tree preset schema.
            '''
        ),
    )
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_ins = sub.add_parser('insert', help='Insert an ILA via ECO flow and write bit/ltx.')
    _add_common(p_ins)
    p_ins.add_argument('--preset', choices=sorted(PRESETS),
                       help='Named probe preset')
    p_ins.add_argument('--probes-file', type=Path, default=None,
                       help='JSON probe spec (alternative to --preset)')
    p_ins.add_argument('--tag', default=None,
                       help='Artifact tag suffix (default: preset name)')
    p_ins.set_defaults(func=cmd_insert)

    p_list = sub.add_parser('list-nets', help='Dump nets matching glob patterns from the checkpoint.')
    _add_common(p_list)
    p_list.add_argument('--filter', action='append', default=None,
                        help='Glob pattern (may be repeated). Default: all nets.')
    p_list.add_argument('--limit', type=int, default=200,
                        help='Maximum number of nets to print (default: 200)')
    p_list.set_defaults(func=cmd_list_nets)

    p_cap = sub.add_parser('capture', help='Program FPGA and capture ILA waveform to CSV.')
    _add_common(p_cap)
    p_cap.add_argument('--preset', choices=sorted(PRESETS), default=None,
                       help='Preset name (used to locate bit/ltx by convention)')
    p_cap.add_argument('--tag', default=None,
                       help='Artifact tag suffix (default: preset name)')
    p_cap.add_argument('--bit', type=Path, default=None,
                       help='Explicit ILA bitstream path')
    p_cap.add_argument('--ltx', type=Path, default=None,
                       help='Explicit debug-probes file path')
    p_cap.add_argument('--output', type=Path, default=None,
                       help='CSV output path (default: alongside artifacts)')
    p_cap.add_argument('--trigger', action='append', default=None,
                       help='Trigger expression, e.g. lsu_watchdog=1 (repeatable, AND)')
    p_cap.add_argument('--window', type=int, default=1024,
                       help='Capture window depth (default: 1024)')
    p_cap.add_argument('--hw-server-url', default='localhost:3121',
                       help='Vivado hw_server URL (default: %(default)s)')
    p_cap.set_defaults(func=cmd_capture)

    p_pre = sub.add_parser('presets', help='List the built-in probe presets.')
    p_pre.set_defaults(func=cmd_presets)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


def run(argv: list[str]) -> int:
    return main(argv) or 0


if __name__ == '__main__':
    raise SystemExit(main())
