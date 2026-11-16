"""Tabela de mensagens do KH2 (subarquivo tipo 2 de msg/*.bar): magic, contagem, (id, offset)[], strings terminadas em 0."""
import struct


def parse(d):
    """Cada mensagem vai do seu offset ate o offset seguinte (inclui o terminador);
    parametros de codigos de controle podem conter 0x00, entao nao da pra cortar no primeiro zero."""
    magic, count = struct.unpack_from("<ii", d, 0)
    ents = [struct.unpack_from("<II", d, 8 + i * 8) for i in range(count)]
    bounds = sorted(set(o for _, o in ents)) + [len(d)]
    nxt = {bounds[i]: bounds[i + 1] for i in range(len(bounds) - 1)}
    return magic, {mid: d[off:nxt[off]] for mid, off in ents}


def build(magic, messages, tail_align=0):
    head = bytearray(struct.pack("<ii", magic, len(messages)))
    body = bytearray()
    base = 8 + 8 * len(messages)
    for mid, text in messages.items():
        head += struct.pack("<II", mid, base + len(body))
        body += text
    out = head + body
    if tail_align:
        out += b"\0" * ((-len(out)) % tail_align)
    return bytes(out)


def merge(vanilla, patch):
    """Textos do patch por ID, na ordem do PS5; IDs exclusivos de cada lado sao mantidos."""
    magic, van = parse(vanilla)
    _, pat = parse(patch)
    merged = {k: pat.get(k, v) for k, v in van.items()}
    extra = [k for k in pat if k not in van]
    for k in extra:
        merged[k] = pat[k]
    if extra:
        merged = dict(sorted(merged.items()))
    changed = sum(1 for k in van if merged[k] != van[k])
    return magic, merged, changed, extra


_UPPER = {0x2E + i: chr(65 + i) for i in range(26)}
_LOWER = {0x9A + i: chr(97 + i) for i in range(26)}

_ENC = {v: k for k, v in {**_UPPER, **_LOWER}.items()}
_ENC.update({" ": 0x01, "\n": 0x02, ".": 0x4F, "!": 0x48,
             "ã": 0xBA, "á": 0xB8, "í": 0xC0, "Ç": 0xE7, "Ã": 0xD3})


def encode(text, tokens=None):
    """Texto simples -> bytes KH2 (sem terminador). `{nome}` insere bytes crus de `tokens`."""
    out = bytearray()
    i = 0
    while i < len(text):
        if text[i] == "{":
            j = text.index("}", i)
            out += tokens[text[i + 1:j]]
            i = j + 1
            continue
        out.append(_ENC[text[i]])
        i += 1
    return bytes(out)


def preview(text):
    """Decodificacao aproximada (so letras/espaco) para relatorio."""
    out = []
    for b in text:
        if b == 0x01:
            out.append(" ")
        elif b == 0x02:
            out.append(" / ")
        elif b in _UPPER:
            out.append(_UPPER[b])
        elif b in _LOWER:
            out.append(_LOWER[b])
        else:
            out.append("·")
    return "".join(out)
