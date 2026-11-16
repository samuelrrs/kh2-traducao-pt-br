"""Varre todas as texturas do patch e grava as regioes de diferenca em work/regioes.json (+ mosaicos para revisao)."""
import io
import json
import os
import zipfile

import numpy as np
from PIL import Image

import dds
import gnf
import port
import regions
from ps5pkg import Package


def load_pair(entry, zp, sub, z):
    if sub.endswith(".png"):
        van = np.asarray(Image.open(io.BytesIO(entry.rem(sub).data)).convert("RGBA"))
        pat = np.asarray(Image.open(io.BytesIO(z.read(zp))).convert("RGBA"))
    else:
        van = gnf.decode(entry.rem(sub[:-4] + ".gnf").data)[1][0]
        pat = dds.decode(z.read(zp))[0]
    return van, pat


def main():
    z = zipfile.ZipFile(port.PATCH)
    pkgs, cur = {}, {}
    out = {}
    names = [n for n in z.namelist() if "/remastered/" in n and not n.endswith("/")]
    for k, zp in enumerate(names):
        pk, _, rest = zp.split("/", 2)
        asset, sub = rest.rsplit("/", 1)
        if asset in port.SKIP_REMASTERED_ASSETS:
            continue
        P = pkgs.setdefault(pk, Package(port.DT, pk))
        if cur.get("key") != (pk, asset):
            cur = {"key": (pk, asset), "e": P.read(asset)}
        van, pat = load_pair(cur["e"], zp, sub, z)
        if not port.aspect_ok(pat.shape[1], pat.shape[0], van.shape[1], van.shape[0]):
            out[zp] = {"aspect": False}
            continue
        regs, _ = regions.find(van, pat)
        out[zp] = {"aspect": True, "van": list(van.shape[:2]), "pat": list(pat.shape[:2]),
                   "regions": [r.__dict__ for r in regs]}
        print("\r%d/%d" % (k + 1, len(names)), end="")
    print()
    json.dump(out, open(os.path.join(port.WORK, "regioes.json"), "w"), indent=0)


if __name__ == "__main__":
    main()
