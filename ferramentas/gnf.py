"""GNF v5 do port PS5: header de 256 bytes com descritor de imagem AMD GFX10 em 0x28."""
import struct
from dataclasses import dataclass

import etcpak
import numpy as np
import texture2ddecoder

HEADER = 0x100
FMT_RGBA8 = 56
FMT_BC1 = 169
FMT_BC2 = 171
FMT_BC3 = 173

BLOCK_BYTES = {FMT_BC1: 8, FMT_BC2: 16, FMT_BC3: 16}


@dataclass
class Info:
    fmt: int
    width: int
    height: int
    levels: int
    sw_mode: int
    dst_sel: int
    data_size: int


def parse(g):
    assert g[:4] == b"GNF ", "nao e GNF"
    d1, d2, d3 = struct.unpack_from("<III", g, 0x2C)
    fmt = (d1 >> 20) & 0x1FF
    width = (((d2 & 0xFFF) << 2) | (d1 >> 30)) + 1
    height = ((d2 >> 14) & 0x3FFF) + 1
    base_level = (d3 >> 12) & 0xF
    last_level = (d3 >> 16) & 0xF
    sw_mode = (d3 >> 20) & 0x1F
    data_size = struct.unpack_from("<I", g, 0x44)[0]
    return Info(fmt, width, height, last_level - base_level + 1, sw_mode, d3 & 0xFFF, data_size)


PITCH_ALIGN = 256


def _rows(fmt, w, h):
    """(bytes uteis por linha, numero de linhas) do nivel."""
    if fmt == FMT_RGBA8:
        return w * 4, h
    return max(1, (w + 3) // 4) * BLOCK_BYTES[fmt], max(1, (h + 3) // 4)


def level_size(fmt, w, h):
    row, rows = _rows(fmt, w, h)
    return align(row, PITCH_ALIGN) * rows


def align(n, a):
    return (n + a - 1) // a * a


def unpitch(fmt, data, w, h):
    row, rows = _rows(fmt, w, h)
    pitch = align(row, PITCH_ALIGN)
    if pitch == row:
        return bytes(data[:row * rows])
    return b"".join(data[r * pitch:r * pitch + row] for r in range(rows))


def pitch(fmt, data, w, h):
    row, rows = _rows(fmt, w, h)
    p = align(row, PITCH_ALIGN)
    if p == row:
        return data
    pad = b"\0" * (p - row)
    return b"".join(data[r * row:(r + 1) * row] + pad for r in range(rows))


def decode_level(fmt, data, w, h):
    """Devolve array RGBA uint8 (h, w, 4). `data` ja sem padding de pitch."""
    if fmt == FMT_RGBA8:
        a = np.frombuffer(data, np.uint8, w * h * 4).reshape(h, w, 4)
        return a[..., [2, 1, 0, 3]].copy()
    pw, ph = max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)
    if fmt == FMT_BC1:
        bgra = texture2ddecoder.decode_bc1(bytes(data), pw, ph)
    elif fmt == FMT_BC3:
        bgra = texture2ddecoder.decode_bc3(bytes(data), pw, ph)
    else:
        raise ValueError("formato GNF nao suportado: %d" % fmt)
    a = np.frombuffer(bgra, np.uint8).reshape(ph, pw, 4)[:h, :w]
    return a[..., [2, 1, 0, 3]].copy()


def decode(g):
    """Decodifica todos os niveis do GNF -> lista de arrays RGBA."""
    i = parse(g)
    pos, w, h, out = HEADER, i.width, i.height, []
    for _ in range(i.levels):
        n = level_size(i.fmt, w, h)
        out.append(decode_level(i.fmt, unpitch(i.fmt, g[pos:pos + n], w, h), w, h))
        pos += n
        w, h = max(1, w // 2), max(1, h // 2)
    return i, out


def encode(g_vanilla, rgba):
    """Gera um GNF com o mesmo header/formato/niveis da vanilla a partir do nivel 0 em RGBA."""
    i = parse(g_vanilla)
    assert rgba.shape[:2] == (i.height, i.width), (rgba.shape, i)
    assert i.sw_mode == 0, "tiling nao linear nao suportado"
    body = bytearray()
    w, h = i.width, i.height
    for lvl in mip_chain(rgba, i.levels):
        body += pitch(i.fmt, encode_level(i.fmt, lvl), w, h)
        w, h = max(1, w // 2), max(1, h // 2)
    assert len(body) == i.data_size, (len(body), i.data_size)
    out = bytes(g_vanilla[:HEADER]) + bytes(body)
    assert len(out) == len(g_vanilla)
    return out


def encode_level(fmt, rgba):
    h, w = rgba.shape[:2]
    if fmt == FMT_RGBA8:
        return np.ascontiguousarray(rgba[..., [2, 1, 0, 3]]).tobytes()
    pw, ph = max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)
    if (pw, ph) != (w, h):
        pad = np.zeros((ph, pw, 4), np.uint8)
        pad[:h, :w] = rgba
        pad[h:, :w] = rgba[h - 1:h]
        pad[:, w:] = pad[:, w - 1:w]
        rgba = pad
    src = np.ascontiguousarray(rgba).tobytes()
    if fmt == FMT_BC1:
        return etcpak.compress_bc1(src, pw, ph)
    if fmt == FMT_BC3:
        return etcpak.compress_bc3(src, pw, ph)
    raise ValueError("formato GNF nao suportado: %d" % fmt)


def mip_chain(rgba, levels):
    from PIL import Image
    out = [rgba]
    img = Image.fromarray(rgba, "RGBA")
    w, h = img.size
    for _ in range(1, levels):
        w, h = max(1, w // 2), max(1, h // 2)
        out.append(np.asarray(img.resize((w, h), Image.LANCZOS)))
    return out
