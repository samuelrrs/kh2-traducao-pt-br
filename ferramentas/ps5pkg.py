"""Leitura/escrita dos pacotes kh2_*.hed/.pkg da versao PS5 (layout EGS sem criptografia)."""
import hashlib
import os
import struct
import zlib
from dataclasses import dataclass, field

PAD = b"\xcd"
HED_ENTRY = 32


def align16(n):
    return (n + 15) & ~15


@dataclass
class Remastered:
    name: str
    voffset: int
    unk: int
    dec: int
    cmp: int
    data: bytes = b""  # descomprimido


@dataclass
class Entry:
    package: str
    path: str
    hed_index: int
    offset: int
    stored: int
    real: int
    dec: int
    cmp: int
    date: int
    original: bytes = b""
    remastered: list = field(default_factory=list)

    def rem(self, name):
        for r in self.remastered:
            if r.name == name:
                return r
        return None


class Package:
    def __init__(self, folder, name):
        self.folder = folder
        self.name = name
        self.hed_path = os.path.join(folder, name + ".hed")
        self.pkg_path = os.path.join(folder, name + ".pkg")
        raw = open(self.hed_path, "rb").read()
        self.hed = bytearray(raw)
        self.index = {}
        for i in range(0, len(raw), HED_ENTRY):
            self.index[raw[i:i + 16]] = i // HED_ENTRY

    def has(self, path):
        return hashlib.md5(path.encode()).digest() in self.index

    def read(self, path):
        return self.read_index(self.index[hashlib.md5(path.encode()).digest()], path)

    def read_index(self, idx, path=""):
        off, stored, real = struct.unpack_from("<QII", self.hed, idx * HED_ENTRY + 16)
        with open(self.pkg_path, "rb") as f:
            f.seek(off)
            blob = f.read(stored)
        dec, rc, cmp, date = struct.unpack_from("<iiii", blob, 0)
        e = Entry(self.name, path, idx, off, stored, real, dec, cmp, date)
        pos = 16
        heads = []
        for _ in range(rc):
            h = blob[pos:pos + 0x30]
            nm = h[:0x20].split(b"\0")[0].decode()
            vo, unk, rdec, rcmp = struct.unpack_from("<iiii", h, 0x20)
            heads.append(Remastered(nm, vo, unk, rdec, rcmp))
            pos += 0x30
        n = cmp if cmp > 0 else dec
        d = blob[pos:pos + n]
        e.original = zlib.decompress(d) if cmp > 0 else d
        pos = align16(pos + n)
        for r in heads:
            n = r.cmp if r.cmp > 0 else r.dec
            d = blob[pos:pos + n]
            r.data = zlib.decompress(d) if r.cmp > 0 else d
            pos = align16(pos + n)
            e.remastered.append(r)
        return e

    @staticmethod
    def build(e):
        """Serializa a entrada mantendo, para cada bloco, a escolha comprimido/bruto da vanilla."""
        rc = len(e.remastered)
        if e.cmp > 0:
            od = zlib.compress(e.original)
            ocmp = align16(len(od))
        else:
            od = e.original
            ocmp = e.cmp
        out = bytearray(struct.pack("<iiii", len(e.original), rc, ocmp, e.date))
        blocks = []
        voff = 16 + 0x30 * rc + len(e.original)
        for r in e.remastered:
            if r.cmp > 0:
                rd = zlib.compress(r.data)
                rcmp = align16(len(rd))
            else:
                rd = r.data
                rcmp = r.cmp
            out += r.name.encode().ljust(0x20, b"\0")
            out += struct.pack("<iiii", voff, r.unk, len(r.data), rcmp)
            voff += len(r.data)
            blocks.append(rd)
        out += od
        out += PAD * (align16(len(out)) - len(out))
        for rd in blocks:
            out += rd
            out += PAD * (align16(len(out)) - len(out))
        return bytes(out), len(e.original)

    def write(self, e):
        """Anexa a entrada no fim do .pkg e atualiza a linha correspondente do .hed."""
        blob, real = self.build(e)
        with open(self.pkg_path, "r+b") as f:
            f.seek(0, 2)
            end = f.tell()
            start = align16(end)
            f.write(PAD * (start - end))
            f.write(blob)
        struct.pack_into("<QII", self.hed, e.hed_index * HED_ENTRY + 16, start, len(blob), real)
        return start, len(blob)

    def save_hed(self):
        with open(self.hed_path, "r+b") as f:
            f.write(self.hed)
