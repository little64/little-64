#!/usr/bin/env python3
import pathlib
import socket
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
BIN = ROOT / "compilers" / "bin"
MC = BIN / "llvm-mc"
LD = BIN / "ld.lld"
DBG = ROOT / "builddir" / "little-64-debug"

PORT = 9012


def pkt(cmd: str) -> bytes:
    checksum = sum(cmd.encode("utf-8")) & 0xFF
    return f"${cmd}#{checksum:02x}".encode("ascii")


def recv_packet(sock: socket.socket) -> str:
    start = sock.recv(1)
    if start != b"$":
        raise RuntimeError(f"missing packet start, got {start!r}")
    data = bytearray()
    while True:
        b = sock.recv(1)
        if b == b"#":
            break
        data.extend(b)
    _ = sock.recv(2)
    sock.sendall(b"+")
    return data.decode("ascii")


def send_cmd(sock: socket.socket, cmd: str) -> str:
    sock.sendall(pkt(cmd))
    ack = sock.recv(1)
    if ack != b"+":
        raise RuntimeError(f"expected ack '+', got {ack!r} for {cmd!r}")
    if cmd == "k":
        return ""
    return recv_packet(sock)


def build_test_elf(tmpdir: pathlib.Path) -> pathlib.Path:
    asm = tmpdir / "rsp_smoke.asm"
    obj = tmpdir / "rsp_smoke.o"
    elf = tmpdir / "rsp_smoke.elf"

    asm.write_text(
        ".global _start\n"
        "_start:\n"
        "  STOP\n",
        encoding="utf-8",
    )

    subprocess.run(
        [str(MC), "-triple=little64", "-filetype=obj", str(asm), "-o", str(obj)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [str(LD), str(obj), "-o", str(elf)],
        check=True,
        capture_output=True,
        text=True,
    )
    return elf


def connect_with_retry(host: str, port: int, attempts: int = 40, delay: float = 0.05) -> socket.socket:
    last_error = None
    for _ in range(attempts):
        try:
            return socket.create_connection((host, port), timeout=2)
        except OSError as exc:
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"failed to connect to {host}:{port}: {last_error}")


def is_stop_reply(reply: str, signal_hex: str) -> bool:
    return reply == f"S{signal_hex}" or reply.startswith(f"T{signal_hex}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="little64-rsp-") as td:
        tmpdir = pathlib.Path(td)
        elf = build_test_elf(tmpdir)

        server = subprocess.Popen(
            [str(DBG), str(PORT), str(elf)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            sock = connect_with_retry("127.0.0.1", PORT)
            with sock:
                sock.settimeout(3)

                supported = send_cmd(sock, "qSupported")
                assert "qXfer:features:read+" in supported

                stop = send_cmd(sock, "?")
                assert is_stop_reply(stop, "05"), stop

                regs = send_cmd(sock, "g")
                assert len(regs) == 272, len(regs)

                def read_reg_u64_le(payload: str, reg_index: int) -> int:
                    start = reg_index * 16
                    chunk = payload[start:start + 16]
                    b = bytes.fromhex(chunk)
                    return int.from_bytes(b, byteorder="little", signed=False)

                pc = read_reg_u64_le(regs, 15)
                bp_addr_hex = f"{pc:x}"

                mem = send_cmd(sock, "m0,2")
                assert mem == "ffff", mem

                bp_set = send_cmd(sock, f"Z0,{bp_addr_hex},2")
                assert bp_set == "OK", bp_set

                stop_bp = send_cmd(sock, "c")
                assert is_stop_reply(stop_bp, "05"), stop_bp

                bp_clear = send_cmd(sock, f"z0,{bp_addr_hex},2")
                assert bp_clear == "OK", bp_clear

                step_stop = send_cmd(sock, "s")
                assert is_stop_reply(step_stop, "05"), step_stop

                xml_chunk = send_cmd(sock, "qXfer:features:read:target.xml:0,40")
                assert xml_chunk.startswith("m") or xml_chunk.startswith("l")
                assert "<target" in xml_chunk or "<?xml" in xml_chunk

                xml_full_parts = []
                xml_offset = 0
                while True:
                    xml_part = send_cmd(sock, f"qXfer:features:read:target.xml:{xml_offset:x},400")
                    assert xml_part.startswith("m") or xml_part.startswith("l"), xml_part
                    xml_data = xml_part[1:]
                    xml_full_parts.append(xml_data)
                    xml_offset += len(xml_data)
                    if xml_part.startswith("l"):
                        break

                xml_full = "".join(xml_full_parts)
                assert 'generic="fp"' in xml_full, xml_full
                assert 'generic="sp"' in xml_full, xml_full
                assert 'generic="ra"' in xml_full, xml_full
                assert 'generic="pc"' in xml_full, xml_full

                send_cmd(sock, "k")

            server.wait(timeout=5)
            return 0
        finally:
            if server.poll() is None:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
