"""``little64 kernel analyze-lockup`` — analyze Little64 boot lockup traces.

Summarizes the control-flow chain from a ``.l64t`` binary trace, identifies
the suspect transfer that dropped into lockup, and optionally symbolizes
addresses with ``llvm-addr2line``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union, cast

from little64 import paths


LS_OP_NAMES: Dict[int, str] = {
    0: "LOAD",
    1: "STORE",
    2: "PUSH",
    3: "POP",
    4: "MOVE",
    5: "BYTE_LOAD",
    6: "BYTE_STORE",
    7: "SHORT_LOAD",
    8: "SHORT_STORE",
    9: "WORD_LOAD",
    10: "WORD_STORE",
    11: "JUMP_Z",
    12: "JUMP_C",
    13: "JUMP_S",
    14: "JUMP_GT",
    15: "JUMP_LT",
}

TRAP_CAUSE_NAMES: Dict[int, str] = {
    0x3E: "TRAP_EXEC_ALIGN",
    0x3F: "TRAP_PRIVILEGED_INSTRUCTION",
    0x40: "TRAP_SYSCALL",
    0x41: "TRAP_SYSCALL_FROM_SUPERVISOR",
    0x51: "TRAP_PAGE_FAULT_NOT_PRESENT",
    0x52: "TRAP_PAGE_FAULT_PERMISSION",
    0x53: "TRAP_PAGE_FAULT_RESERVED",
    0x54: "TRAP_PAGE_FAULT_CANONICAL",
}

AUX_SUBTYPES: Dict[int, str] = {
    0: "none",
    1: "no-valid-pte",
    2: "invalid-nonleaf",
    3: "permission",
    4: "reserved-bit",
    5: "canonical",
}

RELEVANT_TAGS = {"pc-flow", "pc-odd", "pc-below-ram", "mmu-fault-detail"}
CACHE_FORMAT_VERSION = 1

_HEADER_SIZE = 64
_RECORD_SIZE = 41
_HEADER_FMT = "<4sIIIQQQQ16x"
_RECORD_FMT = "<BQQQQQ"


@dataclass
class Event:
    cycle: int
    tag: str
    pc: int
    a: int
    b: int
    c: int


@dataclass
class AddrSymbol:
    function: str
    location: str


@dataclass
class SingleFlowBlock:
    event: Event


@dataclass
class LoopFlowBlock:
    pattern: List[Event]
    repeats: int
    start_cycle: int
    end_cycle: int


FlowBlock = Union[SingleFlowBlock, LoopFlowBlock]


def _fmt_hex(v: int) -> str:
    return f"0x{v:x}"


def _sign_extend(value: int, bits: int) -> int:
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)


def _decode_instr(word: int) -> str:
    word &= 0xFFFF
    fmt = (word >> 14) & 0x3

    if fmt == 0:
        op = (word >> 10) & 0xF
        rs1 = (word >> 4) & 0xF
        rd = word & 0xF
        off2 = (word >> 8) & 0x3
        opn = LS_OP_NAMES.get(op, f"LS_OP_{op}")
        if op >= 11:
            return f"LS.REG {opn} R{rd}, R{rs1}, +{off2 * 2}"
        if opn == "MOVE":
            return f"LS.REG MOVE R{rd} <- R{rs1}+{off2 * 2}"
        return f"LS.REG {opn} rd=R{rd} rs1=R{rs1} off={off2 * 2}"

    if fmt == 1:
        op = (word >> 10) & 0xF
        opn = LS_OP_NAMES.get(op, f"LS_OP_{op}")
        if 11 <= op <= 15:
            rel10 = _sign_extend(word & 0x3FF, 10)
            return f"LS.PCREL {opn} R15, rel={rel10} ({rel10 * 2} bytes)"
        rd = word & 0xF
        rel6 = _sign_extend((word >> 4) & 0x3F, 6)
        return f"LS.PCREL {opn} rd=R{rd} rel={rel6} ({rel6 * 2} bytes)"

    if fmt == 2:
        shift = (word >> 12) & 0x3
        imm8 = (word >> 4) & 0xFF
        rd = word & 0xF
        return f"LDI shift={shift} imm=0x{imm8:x} rd=R{rd}"

    is_ujmp = ((word >> 13) & 0x1) == 1
    if is_ujmp:
        rel13 = _sign_extend(word & 0x1FFF, 13)
        return f"UJMP rel={rel13} ({rel13 * 2} bytes)"

    gp = (word >> 8) & 0x1F
    rs1 = (word >> 4) & 0xF
    rd = word & 0xF
    return f"GP opcode={gp} rd=R{rd} rs1=R{rs1}"


def _classify_transfer(instr_word: int, frm: int, to: int) -> str:
    decoded = _decode_instr(instr_word)
    if instr_word == 0x10EF:
        return "likely return/jump via LR (MOVE R15 <- R14)"
    if instr_word == 0x101F:
        return "likely jump via R1 (MOVE R15 <- R1)"
    if instr_word == 0x103F:
        return "likely jump via R3 (MOVE R15 <- R3)"
    if instr_word == 0xE004:
        return "conditional pc-relative branch"
    delta = to - frm
    return f"{decoded}; delta={delta:+d}"


def _parse_prefixed_hex(token: str, prefix: str) -> int:
    if not token.startswith(prefix):
        raise ValueError(token)
    return int(token[len(prefix) :], 16)


def _parse_relevant_events(
    lines: List[str],
) -> Tuple[List[Event], Optional[Event], Optional[Event], Optional[Event]]:
    pc_flows: List[Event] = []
    odd_ev: Optional[Event] = None
    low_ev: Optional[Event] = None
    mmu_detail: Optional[Event] = None

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("["):
            continue
        close_idx = stripped.find("]")
        if close_idx <= 1:
            continue
        cycle_text = stripped[1:close_idx]
        if not cycle_text.isdigit():
            continue
        fields = stripped[close_idx + 1 :].split()
        if len(fields) != 5:
            continue
        tag = fields[0]
        if tag not in RELEVANT_TAGS:
            continue
        try:
            ev = Event(
                cycle=int(cycle_text),
                tag=tag,
                pc=_parse_prefixed_hex(fields[1], "pc="),
                a=_parse_prefixed_hex(fields[2], "a="),
                b=_parse_prefixed_hex(fields[3], "b="),
                c=_parse_prefixed_hex(fields[4], "c="),
            )
        except ValueError:
            continue

        if tag == "pc-flow":
            pc_flows.append(ev)
        elif tag == "pc-odd":
            odd_ev = ev
        elif tag == "pc-below-ram":
            low_ev = ev
        elif tag == "mmu-fault-detail":
            mmu_detail = ev

    return pc_flows, odd_ev, low_ev, mmu_detail


def _parse_binary_trace_filtered(
    path: str,
    tail_records: int = 100_000,
) -> Tuple[List[Event], Optional[Event], Optional[Event], Optional[Event]]:
    with open(path, "rb") as f:
        hdr_data = f.read(_HEADER_SIZE)
        if len(hdr_data) < _HEADER_SIZE:
            return [], None, None, None
        (
            _magic,
            _version,
            _flags,
            tag_count,
            event_count,
            _total_written,
            tag_table_off,
            events_off,
        ) = struct.unpack(_HEADER_FMT, hdr_data)

        relevant_ids: Dict[int, str] = {}
        if tag_table_off > 0:
            f.seek(tag_table_off)
            for i in range(tag_count):
                len_byte = f.read(1)
                if not len_byte:
                    break
                name_len = len_byte[0]
                name = f.read(name_len).decode("utf-8", errors="replace")
                if name in RELEVANT_TAGS:
                    relevant_ids[i] = name

        if not relevant_ids:
            return [], None, None, None

        read_count = min(event_count, tail_records)
        start_record = event_count - read_count
        f.seek(events_off + start_record * _RECORD_SIZE)
        raw = f.read(read_count * _RECORD_SIZE)

    pc_flows: List[Event] = []
    odd_ev: Optional[Event] = None
    low_ev: Optional[Event] = None
    mmu_detail: Optional[Event] = None

    _get = relevant_ids.get
    for tag_id, cycle, pc, a, b, c in struct.iter_unpack(_RECORD_FMT, raw):
        tag_name = _get(tag_id)
        if tag_name is None:
            continue
        ev = Event(cycle=cycle, tag=tag_name, pc=pc, a=a, b=b, c=c)
        if tag_name == "pc-flow":
            pc_flows.append(ev)
        elif tag_name == "pc-odd":
            odd_ev = ev
        elif tag_name == "pc-below-ram":
            low_ev = ev
        elif tag_name == "mmu-fault-detail":
            mmu_detail = ev

    return pc_flows, odd_ev, low_ev, mmu_detail


def _find_llvm_addr2line() -> Optional[str]:
    preferred = paths.compiler_bin() / "llvm-addr2line"
    if preferred.is_file() and os.access(preferred, os.X_OK):
        return str(preferred)
    return shutil.which("llvm-addr2line") or shutil.which("addr2line")


def _resolve_addrs_bulk(addr2line_bin: str, elf: str, addresses: List[int]) -> Dict[int, AddrSymbol]:
    if not addresses:
        return {}

    cmd = [addr2line_bin, "-e", elf, "-f", "-C", *[_fmt_hex(addr) for addr in addresses]]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        return {addr: AddrSymbol(function="<addr2line unavailable>", location="??:0") for addr in addresses}

    rows = proc.stdout.splitlines()
    out: Dict[int, AddrSymbol] = {}
    row_idx = 0
    for addr in addresses:
        function = "??"
        location = "??:0"
        if row_idx < len(rows):
            function_row = rows[row_idx].strip()
            row_idx += 1
            if function_row:
                function = function_row
        if row_idx < len(rows):
            location_row = rows[row_idx].strip()
            row_idx += 1
            if location_row:
                location = location_row
        out[addr] = AddrSymbol(function=function, location=location)
    return out


def _file_fingerprint(path: str) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return "missing"
    return f"{st.st_size}:{st.st_mtime_ns}"


def _symbol_cache_namespace(addr2line_bin: str, elf: str) -> str:
    return "|".join(
        [
            os.path.realpath(addr2line_bin),
            _file_fingerprint(addr2line_bin),
            os.path.realpath(elf),
            _file_fingerprint(elf),
        ]
    )


def _load_symbol_cache(cache_path: str) -> Dict[str, List[str]]:
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            payload_obj = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload_obj, dict):
        return {}
    payload = cast(Dict[str, object], payload_obj)

    if payload.get("version") != CACHE_FORMAT_VERSION:
        return {}

    entries_obj = payload.get("entries")
    if not isinstance(entries_obj, dict):
        return {}
    entries = cast(Dict[str, object], entries_obj)

    out: Dict[str, List[str]] = {}
    for key, value in entries.items():
        if not isinstance(value, list):
            continue
        value_list = cast(List[object], value)
        if len(value_list) != 2:
            continue
        if not isinstance(value_list[0], str) or not isinstance(value_list[1], str):
            continue
        out[key] = [value_list[0], value_list[1]]
    return out


def _save_symbol_cache(cache_path: str, entries: Dict[str, List[str]]) -> None:
    cache_dir = os.path.dirname(cache_path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    tmp_path = f"{cache_path}.tmp"
    payload: Dict[str, object] = {"version": CACHE_FORMAT_VERSION, "entries": entries}
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, sort_keys=True)
    os.replace(tmp_path, cache_path)


def _symbolize_addresses(
    addr2line_bin: str,
    elf: str,
    addresses: List[int],
    cache_path: Optional[str],
) -> Tuple[Dict[int, AddrSymbol], int, int]:
    if not addresses:
        return {}, 0, 0

    cache_entries: Dict[str, List[str]] = {}
    cache_namespace = ""
    if cache_path is not None:
        cache_entries = _load_symbol_cache(cache_path)
        cache_namespace = _symbol_cache_namespace(addr2line_bin, elf)

    resolved: Dict[int, AddrSymbol] = {}
    misses: List[int] = []
    hits = 0

    for addr in addresses:
        if cache_path is None:
            misses.append(addr)
            continue
        cache_key = f"{cache_namespace}|{_fmt_hex(addr)}"
        cached = cache_entries.get(cache_key)
        if cached is None:
            misses.append(addr)
            continue
        resolved[addr] = AddrSymbol(function=cached[0], location=cached[1])
        hits += 1

    if misses:
        fresh = _resolve_addrs_bulk(addr2line_bin, elf, misses)
        resolved.update(fresh)
        if cache_path is not None:
            for addr, sym in fresh.items():
                cache_key = f"{cache_namespace}|{_fmt_hex(addr)}"
                cache_entries[cache_key] = [sym.function, sym.location]
            try:
                _save_symbol_cache(cache_path, cache_entries)
            except OSError:
                pass

    return resolved, hits, len(misses)


def _find_matching_pc_flow(pc_flows: List[Event], target_event: Event) -> Optional[Event]:
    for ev in reversed(pc_flows):
        if ev.cycle == target_event.cycle and ev.b == target_event.b:
            return ev
    return None


def _find_first_transition_below_ram(pc_flows: List[Event], mem_base: int) -> Optional[Event]:
    for ev in pc_flows:
        if ev.b < mem_base and ev.a >= mem_base:
            return ev
    return None


def _select_recent_blocks_from_end(
    pc_flows: List[Event],
    tail: int,
    no_loop_compress: bool,
    loop_max_pattern: int,
) -> Tuple[List[FlowBlock], int]:
    if not pc_flows:
        return [], 0

    if no_loop_compress:
        recent = pc_flows[-tail:]
        return [SingleFlowBlock(event=ev) for ev in recent], len(recent)

    keys = [(ev.a, ev.b, ev.c) for ev in pc_flows]
    i = len(pc_flows) - 1
    covered = 0
    blocks_rev: List[FlowBlock] = []

    while i >= 0 and len(blocks_rev) < tail:
        best_len = 0
        best_repeats = 1
        best_span = 0
        max_plen = min(loop_max_pattern, i + 1)

        for plen in range(1, max_plen + 1):
            end = i + 1
            start = end - plen
            pattern = keys[start:end]

            repeats = 1
            j_end = start
            while j_end - plen >= 0 and keys[j_end - plen : j_end] == pattern:
                repeats += 1
                j_end -= plen

            span = repeats * plen
            if repeats >= 2 and (span > best_span or (span == best_span and plen < best_len)):
                best_len = plen
                best_repeats = repeats
                best_span = span

        if best_span > 0:
            end_idx = i
            start_idx = i - best_span + 1
            pattern_start = end_idx - best_len + 1
            pattern_events = pc_flows[pattern_start : end_idx + 1]
            blocks_rev.append(
                LoopFlowBlock(
                    pattern=pattern_events,
                    repeats=best_repeats,
                    start_cycle=pc_flows[start_idx].cycle,
                    end_cycle=pc_flows[end_idx].cycle,
                )
            )
            covered += best_span
            i = start_idx - 1
            continue

        blocks_rev.append(SingleFlowBlock(event=pc_flows[i]))
        covered += 1
        i -= 1

    blocks_rev.reverse()
    return blocks_rev, covered


def _flatten_display_events(blocks: List[FlowBlock]) -> List[Event]:
    out: List[Event] = []
    for block in blocks:
        if isinstance(block, SingleFlowBlock):
            out.append(block.event)
            continue
        out.extend(block.pattern)
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="little64 kernel analyze-lockup",
        description=(
            "Analyze Little64 boot lockup traces: summarize control-flow chain, "
            "identify suspect transfer, and optionally symbolize addresses."
        ),
    )
    parser.add_argument("--log", help="Path to binary trace (.l64t) (default: parse text on stdin)")
    parser.add_argument(
        "--defconfig",
        help="Little64 Linux defconfig used for profile-aware default ELF/cache lookup",
    )
    parser.add_argument(
        "--elf",
        help="ELF for symbolization (default: selected profile vmlinux.unstripped, then vmlinux)",
    )
    parser.add_argument("--tail", type=int, default=24, help="Number of recent pc-flow events to print")
    parser.add_argument("--no-loop-compress", action="store_true")
    parser.add_argument("--loop-max-pattern", type=int, default=8)
    parser.add_argument("--no-symbolize", action="store_true")
    parser.add_argument(
        "--symbol-cache",
        default=None,
        help=(
            "Path to symbol cache JSON "
            "(default: selected profile build dir/.analyze_lockup_flow_addr2line_cache.json)"
        ),
    )
    parser.add_argument("--no-symbol-cache", action="store_true")
    return parser


def run(argv: List[str]) -> int:
    args = _build_parser().parse_args(argv)

    if args.tail < 1:
        print("error: --tail must be >= 1", file=sys.stderr)
        return 2
    if args.loop_max_pattern < 1:
        print("error: --loop-max-pattern must be >= 1", file=sys.stderr)
        return 2

    if args.log:
        if not os.path.isfile(args.log):
            print(f"error: log file not found: {args.log}", file=sys.stderr)
            return 2
        pc_flows, odd_ev, low_ev, mmu_detail = _parse_binary_trace_filtered(args.log)
    else:
        lines = sys.stdin.read().splitlines()
        pc_flows, odd_ev, low_ev, mmu_detail = _parse_relevant_events(lines)
    if not pc_flows:
        print("[little64] no pc-flow events found", file=sys.stderr)
        return 1

    suspect: Event
    suspect_reason: str
    if low_ev is not None:
        first_low = _find_first_transition_below_ram(pc_flows, low_ev.c)
        suspect = first_low or _find_matching_pc_flow(pc_flows, low_ev) or low_ev
        if first_low is not None:
            suspect_reason = f"first transition below RAM base {_fmt_hex(low_ev.c)}"
        else:
            suspect_reason = f"target below RAM base {_fmt_hex(low_ev.c)}"
    elif odd_ev is not None:
        suspect = _find_matching_pc_flow(pc_flows, odd_ev) or odd_ev
        suspect_reason = "odd PC target"
    else:
        suspect = pc_flows[-1]
        suspect_reason = "last pc-flow"

    print("[little64] control-flow summary")
    print(f"  total analyzed pc-flow events: {len(pc_flows)}")
    if low_ev is not None:
        print(f"  memory base: {_fmt_hex(low_ev.c)}")
    if mmu_detail is not None:
        cause_name = TRAP_CAUSE_NAMES.get(mmu_detail.a, "unknown")
        aux_subtype = AUX_SUBTYPES.get(mmu_detail.b & 0xF, "unknown")
        aux_level = (mmu_detail.b >> 8) & 0xFF
        print(
            "  final mmu-fault-detail: "
            f"cycle={mmu_detail.cycle} pc={_fmt_hex(mmu_detail.pc)} "
            f"cause={_fmt_hex(mmu_detail.a)}({cause_name}) "
            f"aux={_fmt_hex(mmu_detail.b)}(subtype={aux_subtype}, level={aux_level}) "
            f"root={_fmt_hex(mmu_detail.c)}"
        )

    loop_blocks, covered_raw = _select_recent_blocks_from_end(
        pc_flows, args.tail, args.no_loop_compress, args.loop_max_pattern,
    )
    loop_count = sum(1 for b in loop_blocks if isinstance(b, LoopFlowBlock))
    shown_chain_events = _flatten_display_events(loop_blocks)

    suspect_symbol_labels: List[Tuple[str, int]] = [
        ("suspect-from", suspect.a),
        ("suspect-to", suspect.b),
    ]
    if mmu_detail is not None:
        suspect_symbol_labels.append(("fault-pc", mmu_detail.pc))

    symbol_ready = False
    symbol_status_message: Optional[str] = None
    resolved: Dict[int, AddrSymbol] = {}
    cache_hits = 0
    cache_misses = 0
    cache_path: Optional[str] = None
    if not args.no_symbol_cache:
        cache_path = args.symbol_cache or str(paths.symbol_cache_path(args.defconfig))
    addr2line_bin: Optional[str] = None
    elf: Optional[str] = None

    if not args.no_symbolize:
        if args.elf:
            elf = args.elf
        else:
            existing = paths.existing_kernel_path(args.defconfig)
            elf = str(existing) if existing else None

        if not elf:
            symbol_status_message = "[little64] symbolization skipped: no ELF found"
        elif not os.path.isfile(elf):
            symbol_status_message = f"[little64] symbolization skipped: ELF not found: {elf}"
        else:
            addr2line_bin = _find_llvm_addr2line()
            if not addr2line_bin:
                symbol_status_message = "[little64] symbolization skipped: llvm-addr2line/addr2line not found"
            else:
                all_symbol_addrs: List[int] = []
                for ev in shown_chain_events:
                    all_symbol_addrs.append(ev.a)
                    all_symbol_addrs.append(ev.b)
                for _, addr in suspect_symbol_labels:
                    all_symbol_addrs.append(addr)

                dedup_addrs: List[int] = []
                seen_addrs: set[int] = set()
                for addr in all_symbol_addrs:
                    if addr in seen_addrs:
                        continue
                    seen_addrs.add(addr)
                    dedup_addrs.append(addr)

                resolved, cache_hits, cache_misses = _symbolize_addresses(
                    addr2line_bin, elf, dedup_addrs, cache_path,
                )
                symbol_ready = True

    print("\n== recent pc-flow chain ==")
    if not args.no_loop_compress:
        print(f"  loop compression: {'enabled' if loop_count > 0 else 'enabled (no loops found)'}")
        if covered_raw != args.tail:
            print(f"  covered raw tail events: {covered_raw} (requested {args.tail})")
    print(f"{'cycle':<10} {'from(a)':<20} {'to(b)':<20} {'instr(c)':<12} decode")
    for block in loop_blocks:
        if isinstance(block, SingleFlowBlock):
            ev = block.event
            decoded = _decode_instr(ev.c)
            print(f"{ev.cycle:<10} {_fmt_hex(ev.a):<20} {_fmt_hex(ev.b):<20} {_fmt_hex(ev.c):<12} {decoded}")
            if symbol_ready:
                from_sym = resolved.get(ev.a, AddrSymbol(function="??", location="??:0"))
                to_sym = resolved.get(ev.b, AddrSymbol(function="??", location="??:0"))
                print(f"{'':<10} {'':<20} {'':<20} {'':<12} from: {from_sym.function} @ {from_sym.location}")
                print(f"{'':<10} {'':<20} {'':<20} {'':<12} to  : {to_sym.function} @ {to_sym.location}")
            continue

        print(
            f"{'loop':<10} {'':<20} {'':<20} {'':<12} "
            f"repeat x{block.repeats}, pattern_len={len(block.pattern)}, "
            f"cycles={block.start_cycle}..{block.end_cycle}"
        )
        for pev in block.pattern:
            decoded = _decode_instr(pev.c)
            cycle_field = f"{pev.cycle}*"
            print(f"{cycle_field:<10} {_fmt_hex(pev.a):<20} {_fmt_hex(pev.b):<20} {_fmt_hex(pev.c):<12} {decoded}")
            if symbol_ready:
                from_sym = resolved.get(pev.a, AddrSymbol(function="??", location="??:0"))
                to_sym = resolved.get(pev.b, AddrSymbol(function="??", location="??:0"))
                print(f"{'':<10} {'':<20} {'':<20} {'':<12} from: {from_sym.function} @ {from_sym.location}")
                print(f"{'':<10} {'':<20} {'':<20} {'':<12} to  : {to_sym.function} @ {to_sym.location}")

    print("\n== suspect transfer ==")
    print(f"  reason: {suspect_reason}")
    print(f"  cycle : {suspect.cycle}")
    print(f"  from  : {_fmt_hex(suspect.a)}")
    print(f"  to    : {_fmt_hex(suspect.b)}")
    print(f"  instr : {_fmt_hex(suspect.c)}")
    print(f"  decode: {_decode_instr(suspect.c)}")
    print(f"  class : {_classify_transfer(suspect.c, suspect.a, suspect.b)}")

    if args.no_symbolize:
        return 0

    if not symbol_ready:
        if symbol_status_message is not None:
            print(f"\n{symbol_status_message}")
        return 0

    print("\n== symbolization (suspect/fault) ==")
    print(f"  tool: {addr2line_bin}")
    print(f"  elf : {elf}")
    if cache_path is None:
        print("  cache: disabled")
    else:
        print(f"  cache: {cache_path} (hits={cache_hits}, misses={cache_misses})")
    for label, addr in suspect_symbol_labels:
        sym = resolved.get(addr, AddrSymbol(function="??", location="??:0"))
        print(f"  {label:<18} {_fmt_hex(addr):<20} {sym.function} @ {sym.location}")

    return 0
