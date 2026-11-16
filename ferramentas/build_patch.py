"""Gera o KH2_PS5_PTBR.patch a partir do backup vanilla e dos arquivos traduzidos.

    python build_patch.py ..\\KH2_PS5_PTBR.patch
"""
import hashlib
import json
import os
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aplicar_traducao import CHUNK, MAGIC, probe_hashes, sha1  # noqa: E402

import port  # noqa: E402

PACKAGES = ["kh2_first", "kh2_fourth", "kh2_fifth", "kh2_sixth"]
VANILLA = os.path.join(port.ROOT, "backup_ps5_original")
PATCHED = port.DT


def write_header(f, header):
    raw = json.dumps(header, indent=1).encode()
    f.write(MAGIC)
    f.write(struct.pack("<I", len(raw)))
    f.write(raw)


def compress_into(out, src, start, end):
    comp = zlib.compressobj(6)
    h = hashlib.sha1()
    written = 0
    src.seek(start)
    left = end - start
    while left:
        buf = src.read(min(CHUNK, left))
        left -= len(buf)
        h.update(buf)
        c = comp.compress(buf)
        out.write(c)
        written += len(c)
    c = comp.flush()
    out.write(c)
    return written + len(c), h.hexdigest()


def main(dest):
    header = {"packages": []}
    with tempfile.TemporaryFile() as body:
        for name in PACKAGES:
            v_hed = open(os.path.join(VANILLA, name + ".hed"), "rb").read()
            p_hed = open(os.path.join(PATCHED, name + ".hed"), "rb").read()
            v_size = os.path.getsize(os.path.join(VANILLA, name + ".pkg"))
            p_size = os.path.getsize(os.path.join(PATCHED, name + ".pkg"))
            if v_hed == p_hed and v_size == p_size:
                continue
            with open(os.path.join(PATCHED, name + ".pkg"), "rb") as pkg:
                probe_head, probe_tail = probe_hashes(pkg, v_size)
                entry = {
                    "name": name,
                    "orig_size": v_size,
                    "new_size": p_size,
                    "orig_hed_sha1": sha1(v_hed),
                    "new_hed_sha1": sha1(p_hed),
                    "probe_head": probe_head,
                    "probe_tail": probe_tail,
                }
                for key, data in (("new_hed", p_hed), ("orig_hed", v_hed)):
                    c = zlib.compress(data, 9)
                    entry[key] = [body.tell(), len(c)]
                    body.write(c)
                off = body.tell()
                clen, tail_sha1 = compress_into(body, pkg, v_size, p_size)
                entry["tail"] = [off, clen]
                entry["tail_sha1"] = tail_sha1
            header["packages"].append(entry)
            print(f"{name}: +{p_size - v_size:,} bytes -> {clen:,} comprimido")
        with open(dest, "wb") as out:
            write_header(out, header)
            body.seek(0)
            while buf := body.read(CHUNK):
                out.write(buf)
    print("patch:", dest, f"{os.path.getsize(dest):,} bytes")


if __name__ == "__main__":
    main(sys.argv[1])
