"""Porta o patch PT-BR do KH2 PC (traducao.kh2pcpatch) para os pacotes do dump PS5.

    python port.py --dry-run   # converte tudo em memoria, gera previews e relatorio
    python port.py --apply     # idem + grava nos kh2_*.pkg/.hed do dump
"""
import argparse
import collections
import io
import json
import os
import struct
import sys
import zipfile

import numpy as np
from PIL import Image

import bar
import dds
import gnf
import msg
from ps5pkg import Package

ROOT = os.environ.get("KH2_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH = os.path.join(ROOT, "traducao.kh2pcpatch")
DT = os.path.join(ROOT, "PPSA35901-app", "Image", "dt")
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work")

IMG_FLAG = 0x20000000

# Conteudo de mod de gameplay do patch de PC (scripts/eventos/baus/modelos novos), nao e traducao.
SKIP_ORIGINAL = {
    "libretto-hb.bar": "diario: adiciona entrada nova (mod), sem texto",
    "ard/us/tt32.ard": "scripts de area novos (mod)",
    "ard/us/tt23.ard": "scripts/eventos de area novos (mod)",
    "ard/fr/hb01.ard": "scripts/eventos de area novos (mod)",
    "ard/gr/hb01.ard": "scripts/eventos de area novos (mod)",
    "ard/it/hb01.ard": "scripts/eventos de area novos (mod)",
    "ard/us/hb01.ard": "scripts/eventos de area novos (mod)",
    "00objentry.bin": "tabela de objetos com entradas novas (mod)",
    "03system.bin": "tabelas de item/bau alteradas (mod)",
    "07localset.bin": "tabela de locais alterada (mod)",
    "obj/W_EX010_Y0.a.us": "troca de modelo (mod)",
    "obj/W_EX010_Y0.mdlx": "troca de modelo (mod)",
    "obj/W_EX010_Z0.mdlx": "troca de modelo (mod)",
    "field2d/us/po0command.2dd": "imagem de baixa resolucao; a versao HD vem pelas texturas remastered",
    "field2d/us/wi0command.2dd": "imagem de baixa resolucao; a versao HD vem pelas texturas remastered",
    "msg/us/fontimage.bar": "fonte de baixa resolucao (apaga glifos de botao do PS5); a versao HD vem pelos PNG remastered",
}
SKIP_REMASTERED_ASSETS = {
    "obj/W_EX010_Y0.a.us", "obj/W_EX010_Y0.mdlx", "obj/W_EX010_Z0.a.us", "obj/W_EX010_Z0.mdlx",
}
SAME_SIZE_SPLICE = {"msg/us/fontinfo.bar"}
# Atlas de icones de botao: as diferencas sao so PlayStation vs Xbox/PC, nada traduzido.
SKIP_TEXTURES = {
    "kh2_first/remastered/msg/us/fontimage.bar/US_fontimage_bar2.png": "atlas de icones de botao (so diferencas de plataforma)",
    "kh2_first/remastered/menu/us/title.2ld/US_title_2ld1.png": "logo da Disney substituida pela logo do grupo de traducao",
}
REGION_MIN = 2e-4  # fracao minima de pixels fortemente diferentes para a regiao contar como alteracao do patch
FULL_REPLACE_AREA = 0.25  # acima disso a textura inteira vem do patch (evita retalhos de texto antigo)
# Atlas de fonte: o PC apaga glifos que no PS5 sao icones de botao; so entram glifos alterados/novos.
NO_REMOVAL = {
    "kh2_first/remastered/msg/us/fontimage.bar/US_fontimage_bar0.png",
    "kh2_first/remastered/msg/us/fontimage.bar/US_fontimage_bar1.png",
}
TOOLS = os.path.dirname(os.path.abspath(__file__))

PS_TOKEN = {"ps": bytes.fromhex("3da59ab240ad9aada2a8a78826")}  # "PlayStation(R)5" como o jogo grava
SAVE_CHECK = "Verificando dados salvos no\nconsole {ps}."
SAVE_DELETE = "Apagando os dados selecionados\ndo console {ps}."
SAVE_LOAD = "Carregando dados salvos do\nconsole {ps}."
SAVE_OVERWRITE = "Sobrescrevendo dados salvos do\nconsole {ps}."
NO_POWER_OFF = "\nNão desligue o sistema!"
# Mensagens de save que no PS5 falam do console (no PC falavam do PC).
# first=None mantem a traducao do patch; tails sao as caixas extras que so existem no US_sys.bar do PS5.
SYS_OVERRIDES = {
    2696: (None, [SAVE_CHECK]),
    2697: (SAVE_CHECK, []),
    2699: ("Falha ao salvar os dados.", []),
    2702: (None, [SAVE_DELETE]),
    2703: (SAVE_DELETE, [SAVE_LOAD, SAVE_OVERWRITE]),
    2704: ("Salvando dados no console {ps}.", [SAVE_LOAD, SAVE_OVERWRITE]),
    2705: (SAVE_LOAD, []),
    2706: (SAVE_OVERWRITE, []),
    2707: (SAVE_DELETE, []),
    22061: (None, [SAVE_CHECK]),
}
INFO_PREFIX = bytes.fromhex("090a07ff000080")


class Report:
    def __init__(self):
        self.rows = []
        self.count = collections.Counter()

    def add(self, status, path, detail=""):
        self.rows.append((status, path, detail))
        self.count[status] += 1


def info_box(header, text, power_note=True):
    return header + msg.encode(text + (NO_POWER_OFF if power_note else ""), PS_TOKEN) + b"\0"


def sys_override(mid, patch_msgs, ps5_text, base_text):
    """base_text: a mesma mensagem no sys.bar original do PS5 (None = montar sem as caixas extras)."""
    first, tails = SYS_OVERRIDES[mid]
    hdr_src = patch_msgs[2697]
    header = hdr_src[:hdr_src.index(b"\x02\x02") + 2]
    if first is None:
        out = patch_msgs[mid]
    else:
        out = info_box(header, first, mid != 2699)
    if base_text is not None:
        segs = ps5_text.count(INFO_PREFIX) - base_text.count(INFO_PREFIX)
        assert segs == len(tails), (mid, segs, len(tails))
        for t in tails:
            out += info_box(header, t)
    return out


def text_of(bar_data):
    return msg.parse([e for e in bar.parse(bar_data)[0] if e.type == 2][0].data)[1]


def merge_msg_bar(vanilla_bar, patch_bar, sys_mode=None, base_msgs=None):
    """Substitui o texto (subarquivo tipo 2) do BAR do PS5 pelo do patch, por ID."""
    ents, extra = bar.parse(vanilla_bar)
    pents, _ = bar.parse(patch_bar)
    ptext = [e for e in pents if e.type == 2]
    assert len([e for e in ents if e.type == 2]) == 1 and len(ptext) == 1
    out = []
    changed = 0
    for e in ents:
        if e.type == 2:
            magic, merged, changed, _ = msg.merge(e.data, ptext[0].data)
            if sys_mode:
                _, pmsgs = msg.parse(ptext[0].data)
                _, vmsgs = msg.parse(e.data)
                for mid in SYS_OVERRIDES:
                    base = base_msgs[mid] if base_msgs else None
                    merged[mid] = sys_override(mid, pmsgs, vmsgs[mid], base)
            e = bar.BarEntry(e.type, e.dup, e.name, msg.build(magic, merged))
        out.append(e)
    return bar.build(out, extra), changed


def bar_offsets(d):
    cnt, = struct.unpack_from("<i", d, 4)
    return [struct.unpack_from("<II", d, 16 + i * 16 + 8) for i in range(cnt)]


def remap_image_pointers(entry, old, new):
    """Os assets remastered guardam 0x20000000|offset da imagem dentro do original; segue o subarquivo."""
    oo, no = bar_offsets(old), bar_offsets(new)
    for r in entry.remastered:
        u = r.unk & 0xFFFFFFFF
        if u == 0xFFFFFFFF or not (u & IMG_FLAG):
            continue
        rel = u & ~IMG_FLAG
        for (o, s), (n, ns) in zip(oo, no):
            if o <= rel < o + s:
                assert ns == s, "subarquivo de imagem mudou de tamanho"
                r.unk = IMG_FLAG | (n + rel - o)
                break
        else:
            raise AssertionError("ponteiro de imagem fora dos subarquivos: %s %x" % (r.name, u))


def splice_same_size(vanilla, patched):
    ve, _ = bar.parse(vanilla)
    pe, _ = bar.parse(patched)
    out = bytearray(vanilla)
    n = 0
    for (o, s), a, b in zip(bar_offsets(vanilla), ve, pe):
        assert (a.type, a.name, len(a.data)) == (b.type, b.name, len(b.data))
        if a.data != b.data:
            out[o:o + s] = b.data
            n += 1
    return bytes(out), n


def fit(rgba, w, h):
    if rgba.shape[:2] == (h, w):
        return rgba
    return np.asarray(Image.fromarray(rgba, "RGBA").resize((w, h), Image.LANCZOS))


def aspect_ok(src_w, src_h, w, h):
    return abs((src_w / src_h) / (w / h) - 1) < 0.02


def preview(path, before, after):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    h = max(before.shape[0], after.shape[0])
    def bg(a):
        a = a.astype(np.float32)
        al = a[..., 3:4] / 255
        chk = np.full(a.shape[:2] + (1,), 64, np.float32)
        return (a[..., :3] * al + chk * (1 - al)).astype(np.uint8)
    canvas = np.full((h, before.shape[1] + after.shape[1] + 8, 3), 128, np.uint8)
    canvas[:before.shape[0], :before.shape[1]] = bg(before)
    canvas[:after.shape[0], before.shape[1] + 8:] = bg(after)
    img = Image.fromarray(canvas)
    if img.width > 1600:
        img = img.resize((1600, int(img.height * 1600 / img.width)))
    img.save(path)


def load_regions():
    data = json.load(open(os.path.join(WORK, "regioes.json")))
    excluded = {tuple(x) for x in json.load(open(os.path.join(TOOLS, "excluir_regioes.json")))}
    return data, excluded


def accepted_regions(zpath, regions_db):
    data, excluded = regions_db
    info = data[zpath]
    h = min(info["van"][0], info["pat"][0])
    w = min(info["van"][1], info["pat"][1])
    out, dropped = [], 0
    for i, g in enumerate(info["regions"]):
        if g["strong"] / (w * h) < REGION_MIN:
            continue
        if (zpath, i) in excluded:
            dropped += 1
            continue
        out.append(g)
    return out, dropped


def region_box(g, W, H):
    x0, y0 = max(0, int(g["x0"] * W) - 1), max(0, int(g["y0"] * H) - 1)
    x1, y1 = min(W, int(np.ceil(g["x1"] * W)) + 1), min(H, int(np.ceil(g["y1"] * H)) + 1)
    return x0, y0, x1, y1


def compose(van, pat, regs):
    """Vanilla do PS5 com as regioes alteradas pelo patch coladas por cima (patch ja na resolucao do PS5)."""
    out = van.copy()
    H, W = van.shape[:2]
    for g in regs:
        x0, y0, x1, y1 = region_box(g, W, H)
        out[y0:y1, x0:x1] = pat[y0:y1, x0:x1]
    return out


def coverage(regs, W, H):
    m = np.zeros((H, W), bool)
    for g in regs:
        x0, y0, x1, y1 = region_box(g, W, H)
        m[y0:y1, x0:x1] = True
    return m.mean()


def restore_removed_glyphs(van, new):
    """Restaura todo glifo do PS5 que sumiu no resultado (o patch do PC apaga os icones de botao da fonte)."""
    from scipy import ndimage
    lab, _ = ndimage.label(ndimage.binary_dilation(van[..., 3] > 32, iterations=2))
    out = new.copy()
    restored = 0
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        m = lab[sl] == i
        a = van[sl][..., 3][m].astype(np.float64).sum()
        b = new[sl][..., 3][m].astype(np.float64).sum()
        if a > 0 and b < 0.2 * a:
            out[sl][m] = van[sl][m]
            restored += 1
    return out, restored


def port_texture(zpath, data, entry, sub, report, previews, regions_db):
    if zpath in SKIP_TEXTURES:
        report.add("pulado", zpath, SKIP_TEXTURES[zpath])
        return False
    is_png = sub.lower().endswith(".png")
    if is_png:
        r = entry.rem(sub)
        van_img = Image.open(io.BytesIO(r.data))
        van = np.asarray(van_img.convert("RGBA"))
        pat, fmt = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA")), "PNG"
    else:
        r = entry.rem(sub[:-4] + ".gnf")
        info = gnf.parse(r.data)
        van = gnf.decode(r.data)[1][0]
        pat, fmt = dds.decode(data)
    H, W = van.shape[:2]
    sh, sw = pat.shape[:2]
    if not aspect_ok(sw, sh, W, H):
        report.add("pulado", zpath, "proporcao %dx%d vs PS5 %dx%d (atlas redesenhado no PC)" % (sw, sh, W, H))
        return False
    regs, dropped = accepted_regions(zpath, regions_db)
    patf = fit(pat, W, H)
    if not regs:
        report.add("sem-traducao", zpath, "igual a vanilla do PS5" + (" (so icones de botao)" if dropped else ""))
        return False
    full = not dropped and zpath not in NO_REMOVAL and coverage(regs, W, H) > FULL_REPLACE_AREA
    new = patf.copy() if full else compose(van, patf, regs)
    if zpath in NO_REMOVAL:
        new, restored = restore_removed_glyphs(van, new)
        dropped += restored
    if is_png:
        buf = io.BytesIO()
        Image.fromarray(new, "RGBA").convert(van_img.mode).save(buf, "PNG")
        r.data = buf.getvalue()
    else:
        r.data = gnf.encode(r.data, new)
    detail = "%s %dx%d -> %dx%d, %s" % (fmt, sw, sh, W, H, "textura inteira" if full else "%d regioes" % len(regs))
    if dropped:
        detail += ", %d icones/glifos de botao mantidos do PS5" % dropped
    report.add("png" if is_png else "gnf", zpath, detail)
    if previews:
        after = np.asarray(Image.open(io.BytesIO(r.data)).convert("RGBA")) if is_png else gnf.decode(r.data)[1][0]
        preview(os.path.join(WORK, "preview", zpath.replace("/", "__") + ".png"), van, after)
    return True


def run(apply):
    z = zipfile.ZipFile(PATCH)
    groups = collections.defaultdict(lambda: {"original": None, "remastered": []})
    for n in z.namelist():
        if not n.startswith("kh2_") or n.endswith("/"):
            continue
        pk, kind, rest = n.split("/", 2)
        if kind == "original":
            groups[(pk, rest)]["original"] = n
        else:
            asset, sub = rest.rsplit("/", 1)
            groups[(pk, asset)]["remastered"].append((n, sub))

    report = Report()
    packages = {}
    regions_db = load_regions()
    for (pk, asset), g in sorted(groups.items()):
        P = packages.setdefault(pk, Package(DT, pk))
        entry = P.read(asset)
        dirty = False
        if g["original"]:
            zp = g["original"]
            patched = z.read(zp)
            if asset in SKIP_ORIGINAL:
                report.add("pulado", zp, SKIP_ORIGINAL[asset])
            elif patched == entry.original:
                report.add("igual", zp)
            elif asset in SAME_SIZE_SPLICE:
                entry.original, n = splice_same_size(entry.original, patched)
                report.add("original", zp, "%d subarquivos substituidos no lugar" % n)
                dirty = True
            elif asset.startswith("msg/us/"):
                old = entry.original
                sys_mode = "original" if asset == "msg/us/sys.bar" else None
                entry.original, changed = merge_msg_bar(old, patched, sys_mode)
                remap_image_pointers(entry, old, entry.original)
                report.add("texto", zp, "%d mensagens traduzidas" % changed)
                dirty = True
                if asset == "msg/us/sys.bar":
                    r = entry.rem("US_sys.bar")
                    r.data, changed = merge_msg_bar(r.data, patched, "remastered", text_of(old))
                    report.add("texto", zp + " -> US_sys.bar (remastered)", "%d mensagens traduzidas" % changed)
            else:
                report.add("pulado", zp, "sem regra de conversao")
        if asset not in SKIP_REMASTERED_ASSETS:
            for zp, sub in g["remastered"]:
                if port_texture(zp, z.read(zp), entry, sub, report, not apply, regions_db):
                    dirty = True
        else:
            for zp, _ in g["remastered"]:
                report.add("pulado", zp, "textura do modelo trocado pelo mod (mantida a do PS5)")
        if dirty:
            check_entry(entry, Package.build(entry)[0])
            if apply:
                P.write(entry)
        sys.stdout.write("\r%-5d %s" % (len(report.rows), asset[:60].ljust(60)))
        sys.stdout.flush()
    print()
    if apply:
        for P in packages.values():
            P.save_hed()
    write_report(report, apply)


def check_entry(entry, blob):
    """Relê o blob serializado e confere que tudo descomprime e bate com o que foi montado."""
    import zlib
    dec, rc, cmp, _ = struct.unpack_from("<iiii", blob, 0)
    assert rc == len(entry.remastered) and dec == len(entry.original)
    pos = 16 + 0x30 * rc
    n = cmp if cmp > 0 else dec
    orig = zlib.decompress(blob[pos:pos + n]) if cmp > 0 else blob[pos:pos + n]
    assert orig == entry.original
    pos = (pos + n + 15) & ~15
    for i, r in enumerate(entry.remastered):
        _, _, rdec, rcmp = struct.unpack_from("<iiii", blob, 16 + i * 0x30 + 0x20)
        n = rcmp if rcmp > 0 else rdec
        d = zlib.decompress(blob[pos:pos + n]) if rcmp > 0 else blob[pos:pos + n]
        assert d == r.data and rdec == len(r.data)
        if r.name.endswith(".gnf"):
            gnf.decode(d)
        pos = (pos + n + 15) & ~15
    return True


def write_report(report, apply):
    os.makedirs(WORK, exist_ok=True)
    name = "relatorio_apply.txt" if apply else "relatorio_dryrun.txt"
    with open(os.path.join(WORK, name), "w", encoding="utf-8") as f:
        for k, v in sorted(report.count.items()):
            f.write("%-20s %d\n" % (k, v))
        f.write("\n")
        for s, p, d in report.rows:
            f.write("%-20s %s  %s\n" % (s, p, d))
    print(json.dumps(report.count, indent=1, ensure_ascii=False))
    for s, p, d in report.rows:
        if s == "pulado":
            print("  pulado:", p, "-", d)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    run(ap.parse_args().apply)
