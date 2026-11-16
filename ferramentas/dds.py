"""Decodificacao dos DDS do patch de PC (nivel 0) para RGBA."""
import struct

import numpy as np
import texture2ddecoder


def _rgb565(c):
    r = ((c >> 11) & 31) * 255 // 31
    g = ((c >> 5) & 63) * 255 // 63
    b = (c & 31) * 255 // 31
    return np.stack([r, g, b], -1).astype(np.int32)


def _decode_dxt3(data, w, h):
    bw, bh = (w + 3) // 4, (h + 3) // 4
    blk = np.frombuffer(data, np.uint8, bw * bh * 16).reshape(bh, bw, 16)
    alpha = blk[..., :8]
    a = np.empty((bh, bw, 16), np.uint8)
    a[..., 0::2] = (alpha & 0x0F) * 17
    a[..., 1::2] = (alpha >> 4) * 17
    col = blk[..., 8:].copy()
    c0 = col[..., 0].astype(np.int32) | (col[..., 1].astype(np.int32) << 8)
    c1 = col[..., 2].astype(np.int32) | (col[..., 3].astype(np.int32) << 8)
    p0, p1 = _rgb565(c0), _rgb565(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) // 3, (p0 + 2 * p1) // 3], 2)  # bh,bw,4,3
    bits = col[..., 4:8].astype(np.uint32)
    idx = bits[..., 0] | (bits[..., 1] << 8) | (bits[..., 2] << 16) | (bits[..., 3] << 24)
    sel = np.stack([(idx >> (2 * i)) & 3 for i in range(16)], -1)  # bh,bw,16
    rgb = np.take_along_axis(pal, sel[..., None].astype(np.int64).repeat(3, -1), 2)
    out = np.concatenate([rgb.astype(np.uint8), a[..., None]], -1)  # bh,bw,16,4
    out = out.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return out[:h, :w]


def _dxt1_alpha(data, w, h):
    """texture2ddecoder ignora o alpha de 1 bit do DXT1: indice 3 em bloco com c0 <= c1 e transparente."""
    bw, bh = (w + 3) // 4, (h + 3) // 4
    blk = np.frombuffer(data, np.uint8, bw * bh * 8).reshape(bh, bw, 8)
    c0 = blk[..., 0].astype(np.int32) | (blk[..., 1].astype(np.int32) << 8)
    c1 = blk[..., 2].astype(np.int32) | (blk[..., 3].astype(np.int32) << 8)
    b = blk[..., 4:8].astype(np.uint32)
    idx = b[..., 0] | (b[..., 1] << 8) | (b[..., 2] << 16) | (b[..., 3] << 24)
    sel = np.stack([(idx >> (2 * i)) & 3 for i in range(16)], -1)
    clear = (sel == 3) & (c0 <= c1)[..., None]
    a = np.where(clear, 0, 255).astype(np.uint8)
    return a.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)


def decode(d):
    """DDS (bytes) -> (array RGBA uint8, descricao do formato)."""
    if d[:8] == b"\x89PNG\r\n\x1a\n":
        import io
        from PIL import Image
        return np.asarray(Image.open(io.BytesIO(d)).convert("RGBA")).copy(), "PNG"
    assert d[:4] == b"DDS ", "nao e DDS"
    h, w = struct.unpack_from("<II", d, 12)
    pf_flags, = struct.unpack_from("<I", d, 80)
    four = d[84:88]
    off = 128
    if pf_flags & 4:
        if four == b"DX10":
            raise ValueError("DDS DX10 nao suportado")
        pw, ph = (w + 3) // 4 * 4, (h + 3) // 4 * 4
        if four == b"DXT1":
            bgra = texture2ddecoder.decode_bc1(d[off:], pw, ph)
        elif four == b"DXT5":
            bgra = texture2ddecoder.decode_bc3(d[off:], pw, ph)
        elif four == b"DXT3":
            return _decode_dxt3(d[off:], w, h), "DXT3"
        else:
            raise ValueError("fourCC nao suportado: %r" % four)
        a = np.frombuffer(bgra, np.uint8).reshape(ph, pw, 4)[:ph, :pw][..., [2, 1, 0, 3]].copy()
        if four == b"DXT1":
            a[..., 3] = _dxt1_alpha(d[off:], pw, ph)
            a[a[..., 3] == 0, :3] = 0
        return a[:h, :w], four.decode()
    bits, rm, gm, bm, am = struct.unpack_from("<IIIII", d, 88)
    if bits != 32:
        raise ValueError("DDS de %d bits nao suportado" % bits)
    px = np.frombuffer(d, np.uint32, w * h, off).reshape(h, w)
    def ch(mask):
        if not mask:
            return np.full((h, w), 255, np.uint8)
        shift = (mask & -mask).bit_length() - 1
        return ((px & mask) >> shift).astype(np.uint8)
    alpha = ch(am) if pf_flags & 1 else np.full((h, w), 255, np.uint8)
    return np.stack([ch(rm), ch(gm), ch(bm), alpha], -1), "RGBA32"
