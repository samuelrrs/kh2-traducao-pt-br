"""Valida os pacotes modificados contra o backup: estrutura, integridade e prefixo intacto."""
import hashlib
import io
import os
import struct

from PIL import Image

import bar
import gnf
import msg
import port
from ps5pkg import Package

BACKUP = os.path.join(port.ROOT, "backup_ps5_original")
NAMES = ["kh2_first", "kh2_fourth", "kh2_fifth", "kh2_sixth"]


def same_prefix(a, b, n):
    ha, hb = hashlib.sha1(), hashlib.sha1()
    with open(a, "rb") as fa, open(b, "rb") as fb:
        left = n
        while left:
            k = min(left, 64 << 20)
            ha.update(fa.read(k))
            hb.update(fb.read(k))
            left -= k
    return ha.digest() == hb.digest()


def main():
    problems = []
    total_changed = 0
    for name in NAMES:
        new, old = Package(port.DT, name), Package(BACKUP, name)
        old_size = os.path.getsize(old.pkg_path)
        prefix_ok = same_prefix(new.pkg_path, old.pkg_path, old_size)
        changed = [i for i in range(0, len(new.hed), 32) if new.hed[i:i + 32] != old.hed[i:i + 32]]
        assert all(new.hed[i:i + 16] == old.hed[i:i + 16] for i in changed), "hash de nome alterado"
        by_index = {}
        for i in changed:
            off, = struct.unpack_from("<Q", new.hed, i + 16)
            if off < old_size:
                problems.append("%s: entrada %d aponta para dentro da area original" % (name, i // 32))
            by_index[i // 32] = True
        for idx in by_index:
            e_new = new.read_index(idx)
            e_old = old.read_index(idx)
            if [r.name for r in e_new.remastered] != [r.name for r in e_old.remastered]:
                problems.append("%s: lista de assets mudou na entrada %d" % (name, idx))
            if bar.is_bar(e_old.original):
                assert bar.is_bar(e_new.original)
                for be in bar.parse(e_new.original)[0]:
                    if be.type == 2 and be.data[:4] == b"\x01\0\0\0":
                        msg.parse(be.data)
            for rn, ro in zip(e_new.remastered, e_old.remastered):
                if rn.name.endswith(".gnf"):
                    if rn.data[:0x100] != ro.data[:0x100] or len(rn.data) != len(ro.data):
                        problems.append("%s: GNF %s com header/tamanho diferente" % (name, rn.name))
                    gnf.decode(rn.data)
                elif rn.name.endswith(".png"):
                    a, b = Image.open(io.BytesIO(rn.data)), Image.open(io.BytesIO(ro.data))
                    a.load()
                    if (a.size, a.mode) != (b.size, b.mode):
                        problems.append("%s: PNG %s com dimensao/modo diferente" % (name, rn.name))
                elif rn.data[:4] == b"BAR\x01":
                    bar.parse(rn.data)
                if (rn.unk & 0xFFFFFFFF) != (ro.unk & 0xFFFFFFFF) and not (rn.unk & port.IMG_FLAG):
                    problems.append("%s: ponteiro de %s alterado sem flag de imagem" % (name, rn.name))
        total_changed += len(changed)
        print("%-10s entradas alteradas %4d | prefixo original intacto: %s | pkg %d -> %d bytes"
              % (name, len(changed), prefix_ok, old_size, os.path.getsize(new.pkg_path)))
        if not prefix_ok:
            problems.append("%s: dados originais do pkg foram alterados" % name)
    print("total de entradas alteradas:", total_changed)
    print("PROBLEMAS:" if problems else "nenhum problema encontrado")
    for p in problems:
        print("  ", p)


if __name__ == "__main__":
    main()
