"""Desenha vanilla PS5 | patch com as regioes de diferenca marcadas (para revisao visual)."""
import json
import os
import sys
import zipfile

import numpy as np
from PIL import Image, ImageDraw

import port
from ps5pkg import Package
from scan_regions import load_pair


def render(zp, out_path, z=None, info=None):
    z = z or zipfile.ZipFile(port.PATCH)
    pk, _, rest = zp.split("/", 2)
    asset, sub = rest.rsplit("/", 1)
    van, pat = load_pair(Package(port.DT, pk).read(asset), zp, sub, z)
    pat = port.fit(pat, van.shape[1], van.shape[0])
    port.preview(out_path, van, pat)
    img = Image.open(out_path).convert("RGB")
    scale = img.width / (2 * van.shape[1] + 8)
    d = ImageDraw.Draw(img)
    for g in (info or {}).get("regions", []):
        for off in (0, van.shape[1] + 8):
            box = [(off + g["x0"] * van.shape[1]) * scale, g["y0"] * van.shape[0] * scale,
                   (off + g["x1"] * van.shape[1]) * scale, g["y1"] * van.shape[0] * scale]
            d.rectangle(box, outline=(255, 0, 255))
    img.save(out_path)


if __name__ == "__main__":
    data = json.load(open(os.path.join(port.WORK, "regioes.json")))
    z = zipfile.ZipFile(port.PATCH)
    for i, zp in enumerate(sys.argv[1:]):
        render(zp, os.path.join(port.WORK, "rev%d.png" % i), z, data.get(zp))
        print(i, zp, len(data.get(zp, {}).get("regions", [])))
