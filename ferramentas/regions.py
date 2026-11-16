"""Regioes em que a textura do patch difere da vanilla do PS5 (comparadas na menor resolucao comum)."""
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

THRESH = 48


@dataclass
class Region:
    x0: float  # coordenadas normalizadas 0..1
    y0: float
    x1: float
    y1: float
    strong: int  # pixels fortemente diferentes (na resolucao de trabalho)
    sat_van: float
    sat_pat: float


def _resize(a, w, h):
    if a.shape[:2] == (h, w):
        return a.astype(np.float32)
    return np.asarray(Image.fromarray(a, "RGBA").resize((w, h), Image.BOX)).astype(np.float32)


def _premul(a):
    return np.concatenate([a[..., :3] * a[..., 3:4] / 255, a[..., 3:4]], -1)


def _saturation(a, m):
    rgb = a[..., :3][m]
    if not len(rgb):
        return 0.0
    w = a[..., 3][m] / 255
    mx, mn = rgb.max(-1), rgb.min(-1)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    return float((s * w).sum() / max(w.sum(), 1e-6))


def find(van, pat):
    """Devolve (regioes, mascara forte na resolucao de trabalho)."""
    w = min(van.shape[1], pat.shape[1])
    h = min(van.shape[0], pat.shape[0])
    a = _resize(van, w, h)
    b = _resize(pat, w, h)
    pa = ndimage.gaussian_filter(_premul(a), (1, 1, 0))
    pb = ndimage.gaussian_filter(_premul(b), (1, 1, 0))
    d = np.abs(pa - pb).max(-1)
    strong = d > THRESH
    strong = ndimage.binary_opening(strong, np.ones((2, 2)))
    if not strong.any():
        return [], strong
    r = max(3, w // 96)
    grown = ndimage.binary_dilation(strong, iterations=r)
    lab, n = ndimage.label(grown)
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        m = (lab[sl] == i) & strong[sl]
        cnt = int(m.sum())
        if cnt < 4:
            continue
        ys, xs = sl
        out.append(Region(xs.start / w, ys.start / h, xs.stop / w, ys.stop / h, cnt,
                          _saturation(a[sl], m), _saturation(b[sl], m)))
    return out, strong
