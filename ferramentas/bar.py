"""Container BAR do KH2: header de 16 bytes + entradas de 16 bytes (tipo, dup, nome, offset, tamanho)."""
import struct
from dataclasses import dataclass


@dataclass
class BarEntry:
    type: int
    dup: int
    name: str
    data: bytes


def is_bar(d):
    return d[:4] == b"BAR\x01"


def parse(d):
    count, = struct.unpack_from("<i", d, 4)
    out = []
    for i in range(count):
        t, dup, nm, off, size = struct.unpack_from("<HH4sII", d, 16 + i * 16)
        out.append(BarEntry(t, dup, nm.rstrip(b"\0").decode("latin1"), d[off:off + size]))
    return out, d[8:16]


def build(entries, extra):
    """Reconstroi o BAR; cada subarquivo alinhado a 16 bytes e entradas dup apontando pro mesmo dado."""
    head = bytearray(b"BAR\x01" + struct.pack("<i", len(entries)) + extra)
    body = bytearray()
    base = 16 + 16 * len(entries)
    seen = {}
    rows = []
    for e in entries:
        key = (e.name, e.data) if e.dup else None
        if key and key in seen:
            off = seen[key]
        else:
            off = base + len(body)
            body += e.data
            body += b"\0" * ((-len(body)) % 16)
            seen[(e.name, e.data)] = off
        rows.append(struct.pack("<HH4sII", e.type, e.dup, e.name.encode("latin1").ljust(4, b"\0"), off, len(e.data)))
    return bytes(head + b"".join(rows) + body)
