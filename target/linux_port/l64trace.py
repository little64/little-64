#!/usr/bin/env python3
"""Decode and analyze Little-64 binary trace files (.l64t).

Binary trace format v1:
  Header (64 bytes):
    [0..3]   magic "L64T"
    [4..7]   version (uint32 LE)
    [8..11]  flags (uint32 LE)
    [12..15] tag_count (uint32 LE)
    [16..23] event_count (uint64 LE)
    [24..31] total_events_written (uint64 LE)
    [32..39] tag_table_offset (uint64 LE)
    [40..47] events_offset (uint64 LE)
    [48..63] reserved

  Event records (41 bytes each, starting at events_offset):
    [0]      tag_id (uint8)
    [1..8]   cycle (uint64 LE)
    [9..16]  pc (uint64 LE)
    [17..24] a (uint64 LE)
    [25..32] b (uint64 LE)
    [33..40] c (uint64 LE)

  Tag table (at tag_table_offset):
    For each tag: 1-byte length + name bytes (no NUL terminator)

Usage:
  l64trace.py decode <file>           Convert binary to text
  l64trace.py stats <file>            Print trace statistics
  l64trace.py tail <file> [-n N]      Print last N events (default 100)
  l64trace.py search <file> [opts]    Search/filter events
  l64trace.py watch <file>            Live-tail (like tail -f), survives file recreation
"""
import argparse
import mmap
import struct
import sys
from dataclasses import dataclass
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple

MAGIC = b"L64T"
HEADER_SIZE = 64
RECORD_SIZE = 41
HEADER_FMT = "<4sIIIQQQQ16x"  # magic, version, flags, tag_count, event_count, total_events, tag_table_off, events_off
RECORD_FMT = "<BQQQQQ"        # tag_id, cycle, pc, a, b, c


@dataclass
class TraceHeader:
    magic: bytes
    version: int
    flags: int
    tag_count: int
    event_count: int
    total_events_written: int
    tag_table_offset: int
    events_offset: int


@dataclass
class TraceEvent:
    tag_id: int
    cycle: int
    pc: int
    a: int
    b: int
    c: int


def read_header(f: BinaryIO) -> TraceHeader:
    data = f.read(HEADER_SIZE)
    if len(data) < HEADER_SIZE:
        raise ValueError("File too small for header")
    fields = struct.unpack(HEADER_FMT, data)
    return TraceHeader(*fields)


def read_tag_table(f: BinaryIO, header: TraceHeader) -> Dict[int, str]:
    f.seek(header.tag_table_offset)
    tags: Dict[int, str] = {}
    for i in range(header.tag_count):
        len_byte = f.read(1)
        if not len_byte:
            break
        name_len = len_byte[0]
        name = f.read(name_len).decode("utf-8", errors="replace")
        tags[i] = name
    return tags


def iter_events(f: BinaryIO, header: TraceHeader) -> Iterator[TraceEvent]:
    """Iterate events with batched I/O for performance."""
    f.seek(header.events_offset)
    remaining = header.event_count
    # Read in ~64 KB chunks (~1600 records)
    batch = 1600
    while remaining > 0:
        n = min(batch, remaining)
        data = f.read(n * RECORD_SIZE)
        if len(data) < RECORD_SIZE:
            break
        # Use iter_unpack for the full chunk
        for fields in struct.iter_unpack(RECORD_FMT, data[:n * RECORD_SIZE]):
            yield TraceEvent(*fields)
        remaining -= n


def is_binary_trace(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == MAGIC
    except (IOError, OSError):
        return False


def format_event(ev: TraceEvent, tags: Dict[int, str]) -> str:
    tag = tags.get(ev.tag_id, f"tag_{ev.tag_id}")
    return f"  [{ev.cycle}] {tag} pc=0x{ev.pc:x} a=0x{ev.a:x} b=0x{ev.b:x} c=0x{ev.c:x}"


def cmd_decode(args: argparse.Namespace) -> int:
    with open(args.file, "rb") as f:
        header = read_header(f)
        if header.magic != MAGIC:
            print(f"Error: not a L64T binary trace file", file=sys.stderr)
            return 1
        tags = read_tag_table(f, header)

        # Print text header for compatibility with existing tools
        sys.stdout.write("[little64] boot-debug: full event stream\n")
        sys.stdout.write("[little64] boot-debug: events (oldest to newest by cycle)\n")

        start = args.start_cycle if args.start_cycle else 0
        end = args.end_cycle if args.end_cycle else 2**64 - 1
        tag_filter = set(args.tags.split(",")) if args.tags else None
        has_cycle_filter = start > 0 or end < 2**64 - 1

        # Batch decode: read chunks, unpack, format, write
        f.seek(header.events_offset)
        remaining = header.event_count
        batch = 4096
        write = sys.stdout.write
        while remaining > 0:
            n = min(batch, remaining)
            data = f.read(n * RECORD_SIZE)
            if len(data) < RECORD_SIZE:
                break
            lines: list[str] = []
            append = lines.append
            for tid, cyc, pc, a, b, c in struct.iter_unpack(RECORD_FMT, data):
                if has_cycle_filter and (cyc < start or cyc > end):
                    continue
                tag = tags.get(tid, f"tag_{tid}")
                if tag_filter and tag not in tag_filter:
                    continue
                append(f"  [{cyc}] {tag} pc=0x{pc:x} a=0x{a:x} b=0x{b:x} c=0x{c:x}\n")
            if lines:
                write("".join(lines))
            remaining -= n

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with open(args.file, "rb") as f:
        header = read_header(f)
        if header.magic != MAGIC:
            print(f"Error: not a L64T binary trace file", file=sys.stderr)
            return 1
        tags = read_tag_table(f, header)

    import os
    file_size = os.path.getsize(args.file)
    data_size = header.event_count * RECORD_SIZE
    overhead = file_size - data_size

    print(f"Format:         L64T binary v{header.version}")
    print(f"File size:      {file_size:,} bytes ({file_size / 1024 / 1024:.1f} MB)")
    print(f"Events:         {header.event_count:,}")
    print(f"Total written:  {header.total_events_written:,}")
    if header.total_events_written > header.event_count:
        dropped = header.total_events_written - header.event_count
        print(f"Dropped:        {dropped:,}")
    print(f"Data size:      {data_size:,} bytes ({data_size / 1024 / 1024:.1f} MB)")
    print(f"Overhead:       {overhead:,} bytes")
    print(f"Record size:    {RECORD_SIZE} bytes")
    print(f"Tags ({header.tag_count}):")

    # Count events per tag — batch read for speed
    tag_counts: Dict[int, int] = {}
    with open(args.file, "rb") as f:
        f.seek(header.events_offset)
        remaining = header.event_count
        batch = 8192
        while remaining > 0:
            n = min(batch, remaining)
            data = f.read(n * RECORD_SIZE)
            if len(data) < RECORD_SIZE:
                break
            for fields in struct.iter_unpack(RECORD_FMT, data):
                tag_counts[fields[0]] = tag_counts.get(fields[0], 0) + 1
            remaining -= n

    for tag_id, name in sorted(tags.items()):
        count = tag_counts.get(tag_id, 0)
        pct = (count / header.event_count * 100) if header.event_count > 0 else 0
        print(f"  [{tag_id:3d}] {name:30s} {count:>12,} ({pct:5.1f}%)")

    # Cycle range
    if header.event_count > 0:
        with open(args.file, "rb") as f:
            f.seek(header.events_offset)
            first_data = f.read(RECORD_SIZE)
            first = struct.unpack(RECORD_FMT, first_data)

            f.seek(header.events_offset + (header.event_count - 1) * RECORD_SIZE)
            last_data = f.read(RECORD_SIZE)
            last = struct.unpack(RECORD_FMT, last_data)

            print(f"Cycle range:    {first[1]:,} .. {last[1]:,}")
            print(f"PC range:       0x{first[2]:x} .. 0x{last[2]:x}")

    # Equivalent text size estimate
    est_text = header.event_count * 100  # ~100 bytes per text line
    ratio = est_text / file_size if file_size > 0 else 0
    print(f"Est. text size: {est_text / 1024 / 1024:.1f} MB (binary is {ratio:.1f}x smaller)")

    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    with open(args.file, "rb") as f:
        header = read_header(f)
        if header.magic != MAGIC:
            print(f"Error: not a L64T binary trace file", file=sys.stderr)
            return 1
        tags = read_tag_table(f, header)

        n = min(args.n, header.event_count)
        skip = header.event_count - n
        f.seek(header.events_offset + skip * RECORD_SIZE)

        data = f.read(n * RECORD_SIZE)
        lines: list[str] = []
        for tid, cyc, pc, a, b, c in struct.iter_unpack(RECORD_FMT, data):
            lines.append(f"  [{cyc}] {tags.get(tid, f'tag_{tid}')} pc=0x{pc:x} a=0x{a:x} b=0x{b:x} c=0x{c:x}\n")
        sys.stdout.write("".join(lines))

    return 0


def cmd_search(args: argparse.Namespace) -> int:
    with open(args.file, "rb") as f:
        header = read_header(f)
        if header.magic != MAGIC:
            print(f"Error: not a L64T binary trace file", file=sys.stderr)
            return 1
        tags = read_tag_table(f, header)

        tag_filter = set(args.tags.split(",")) if args.tags else None
        pc_filter = int(args.pc, 0) if args.pc else None
        count = 0
        max_results = args.max_results

        for ev in iter_events(f, header):
            if args.start_cycle and ev.cycle < args.start_cycle:
                continue
            if args.end_cycle and ev.cycle > args.end_cycle:
                continue
            if pc_filter is not None and ev.pc != pc_filter and ev.a != pc_filter:
                continue
            tag_name = tags.get(ev.tag_id, f"tag_{ev.tag_id}")
            if tag_filter and tag_name not in tag_filter:
                continue
            print(format_event(ev, tags))
            count += 1
            if max_results and count >= max_results:
                break

    print(f"\n({count} events matched)", file=sys.stderr)
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Live-tail a binary trace file, decoding and printing events as they appear.

    Handles:
    - File not yet existing (waits for creation)
    - File truncated/recreated between emulator runs (restarts from beginning)
    - Shows last N existing events on startup (like tail -f)
    - Tag names resolved via live-updated header written by TraceWriter
    """
    import os
    import time

    path = args.file
    poll_interval = args.interval
    initial_n = args.n
    tag_filter = set(args.tags.split(",")) if args.tags else None

    def _wait_for_file(p: str) -> None:
        printed = False
        while not os.path.exists(p):
            if not printed:
                print(f"[l64trace] waiting for {p} ...", file=sys.stderr)
                printed = True
            time.sleep(poll_interval)

    def _try_read_tags(f, header) -> Dict[int, str]:
        """Attempt to read the tag table. Returns empty dict if not yet available.

        Validates that tag names contain only printable characters.  If the
        tag table was overwritten by event data (stale header), the decoded
        names will contain binary garbage and are rejected.
        """
        if header.tag_table_offset == 0 or header.tag_count == 0:
            return {}
        try:
            pos = f.tell()
            tags = read_tag_table(f, header)
            f.seek(pos)
            for name in tags.values():
                if not name or not name.isprintable():
                    return {}
            return tags
        except Exception:
            return {}

    def _refresh_header(f) -> Optional[TraceHeader]:
        """Re-read the header from a live file."""
        try:
            pos = f.tell()
            f.seek(0)
            h = read_header(f)
            f.seek(pos)
            if h.magic != MAGIC:
                return None
            return h
        except Exception:
            return None

    while True:
        _wait_for_file(path)

        try:
            inode = os.stat(path).st_ino
        except OSError:
            continue

        try:
            f = open(path, "rb")
        except OSError:
            time.sleep(poll_interval)
            continue

        try:
            # Wait until file has at least a complete header
            while True:
                try:
                    sz = os.fstat(f.fileno()).st_size
                except OSError:
                    break
                if sz >= HEADER_SIZE:
                    break
                time.sleep(poll_interval)

            header = read_header(f)
            if header.magic != MAGIC:
                print(f"[l64trace] not a L64T file, retrying...", file=sys.stderr)
                f.close()
                time.sleep(poll_interval)
                continue

            tags: Dict[int, str] = _try_read_tags(f, header)

            # Show initial tail of existing events (like tail -f)
            n_existing = header.event_count
            if n_existing > 0 and initial_n > 0:
                show = min(initial_n, n_existing)
                skip = n_existing - show
                f.seek(header.events_offset + skip * RECORD_SIZE)
                data = f.read(show * RECORD_SIZE)
                if data:
                    lines: list[str] = []
                    for tid, cyc, pc, a, b, c in struct.iter_unpack(RECORD_FMT, data):
                        tag = tags.get(tid, f"tag_{tid}")
                        if tag_filter and tag not in tag_filter:
                            continue
                        lines.append(f"  [{cyc}] {tag} pc=0x{pc:x} a=0x{a:x} b=0x{b:x} c=0x{c:x}\n")
                    if lines:
                        sys.stdout.write("".join(lines))
                        sys.stdout.flush()

            # Position at end of known events for live tailing
            event_pos = header.events_offset + n_existing * RECORD_SIZE
            f.seek(event_pos)
            events_shown = 0
            size_hwm = os.fstat(f.fileno()).st_size

            print(f"[l64trace] watching {path} (poll {poll_interval}s)", file=sys.stderr)

            while True:
                # Check for file replacement (inode change or size shrink)
                try:
                    st = os.stat(path)
                except OSError:
                    print(f"\n[l64trace] file removed, waiting...", file=sys.stderr)
                    break

                if st.st_ino != inode or st.st_size < size_hwm:
                    print(f"\n[l64trace] file recreated, restarting...", file=sys.stderr)
                    break
                size_hwm = max(size_hwm, st.st_size)

                # Compute events end from file size, rounded down to a
                # complete-record boundary.  This is robust against stale
                # headers where tag_table_offset hasn't been refreshed.
                events_end = header.events_offset + (
                    (st.st_size - header.events_offset) // RECORD_SIZE
                ) * RECORD_SIZE

                # Read available complete records in one batch
                available = events_end - event_pos
                n_records = max(0, available // RECORD_SIZE)

                if n_records > 0:
                    data = f.read(n_records * RECORD_SIZE)
                    actual = len(data) // RECORD_SIZE
                    if actual > 0:
                        lines: list[str] = []
                        append = lines.append
                        for tid, cyc, pc, a, b, c in struct.iter_unpack(
                                RECORD_FMT, data[:actual * RECORD_SIZE]):
                            tag = tags.get(tid, f"tag_{tid}")
                            if tag_filter and tag not in tag_filter:
                                continue
                            append(f"  [{cyc}] {tag} pc=0x{pc:x} a=0x{a:x} b=0x{b:x} c=0x{c:x}\n")
                        event_pos += actual * RECORD_SIZE
                        events_shown += actual
                        if lines:
                            sys.stdout.write("".join(lines))
                            sys.stdout.flush()

                # Refresh header periodically to pick up new tag names and
                # the updated tag_table_offset (event data boundary).
                new_header = _refresh_header(f)
                if new_header:
                    header = new_header
                    if not tags or header.tag_count > len(tags):
                        new_tags = _try_read_tags(f, header)
                        if new_tags:
                            tags = new_tags
                    f.seek(event_pos)

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            print(f"\n[l64trace] {events_shown} events shown", file=sys.stderr)
            f.close()
            return 0
        finally:
            if not f.closed:
                f.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decode and analyze Little-64 binary trace files (.l64t)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # decode
    p_decode = subparsers.add_parser("decode", help="Convert binary trace to text")
    p_decode.add_argument("file", help="Binary trace file (.l64t)")
    p_decode.add_argument("--start-cycle", type=int, default=None, help="First cycle to include")
    p_decode.add_argument("--end-cycle", type=int, default=None, help="Last cycle to include")
    p_decode.add_argument("--tags", default=None, help="Comma-separated tag filter")

    # stats
    p_stats = subparsers.add_parser("stats", help="Print trace statistics")
    p_stats.add_argument("file", help="Binary trace file (.l64t)")

    # tail
    p_tail = subparsers.add_parser("tail", help="Print last N events")
    p_tail.add_argument("file", help="Binary trace file (.l64t)")
    p_tail.add_argument("-n", type=int, default=100, help="Number of events (default 100)")

    # search
    p_search = subparsers.add_parser("search", help="Search/filter events")
    p_search.add_argument("file", help="Binary trace file (.l64t)")
    p_search.add_argument("--tags", default=None, help="Comma-separated tag filter")
    p_search.add_argument("--pc", default=None, help="Filter by PC value (hex)")
    p_search.add_argument("--start-cycle", type=int, default=None)
    p_search.add_argument("--end-cycle", type=int, default=None)
    p_search.add_argument("--max-results", type=int, default=None, help="Max events to show")

    # watch
    p_watch = subparsers.add_parser("watch", help="Live-tail a trace file (like tail -f)")
    p_watch.add_argument("file", help="Binary trace file (.l64t)")
    p_watch.add_argument("-n", type=int, default=20, help="Initial events to show (default 20)")
    p_watch.add_argument("--interval", type=float, default=0.25, help="Poll interval in seconds (default 0.25)")
    p_watch.add_argument("--tags", default=None, help="Comma-separated tag filter")

    args = parser.parse_args()

    handlers = {
        "decode": cmd_decode,
        "stats": cmd_stats,
        "tail": cmd_tail,
        "search": cmd_search,
        "watch": cmd_watch,
    }

    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
