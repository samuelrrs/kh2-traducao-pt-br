"""Instala ou remove a tradução PT-BR do Kingdom Hearts II (KH 1.5+2.5 PS5)."""
import hashlib
import json
import os
import struct
import sys
import zlib

MAGIC = b"KH2PS5PTBR\x00\x01"
PROBE = 16 * 1024 * 1024
CHUNK = 8 * 1024 * 1024
PATCH_NAME = "KH2_PS5_PTBR.patch"
TITLE = "Tradução PT-BR - Kingdom Hearts II (KH 1.5+2.5 PS5)"


def sha1(data):
    return hashlib.sha1(data).hexdigest()


def probe_hashes(f, size):
    """Hashes do início e do fim da região original do .pkg (checagem rápida)."""
    f.seek(0)
    head = sha1(f.read(min(PROBE, size)))
    f.seek(max(0, size - PROBE))
    tail = sha1(f.read(min(PROBE, size)))
    return head, tail


def read_header(f):
    if f.read(len(MAGIC)) != MAGIC:
        raise ValueError("arquivo de patch inválido")
    n, = struct.unpack("<I", f.read(4))
    return json.loads(f.read(n)), len(MAGIC) + 4 + n


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_dt(folder):
    folder = os.path.abspath(folder.strip().strip('"'))
    for cand in (folder,
                 os.path.join(folder, "Image", "dt"),
                 os.path.join(folder, "dt"),
                 os.path.join(folder, "PPSA35901-app", "Image", "dt")):
        if os.path.isfile(os.path.join(cand, "kh2_first.hed")):
            return cand
    for root, dirs, files in os.walk(folder):
        if "kh2_first.hed" in files and "kh2_first.pkg" in files:
            return root
        if root.count(os.sep) - folder.count(os.sep) >= 4:
            dirs[:] = []
    return None


def ask_folder():
    if len(sys.argv) > 1:
        return sys.argv[1]
    try:
        import tkinter
        from tkinter import filedialog
        tk = tkinter.Tk()
        tk.withdraw()
        tk.attributes("-topmost", True)
        path = filedialog.askdirectory(
            title="Selecione a pasta do jogo (ex.: PPSA35901-app)")
        tk.destroy()
        if path:
            return path
    except Exception:
        pass
    return input("Caminho da pasta do jogo (PPSA35901-app): ")


def state_of(dt, pkg_info):
    """Retorna 'vanilla', 'aplicado', 'interrompido' ou o motivo da incompatibilidade."""
    hed_path = os.path.join(dt, pkg_info["name"] + ".hed")
    pkg_path = os.path.join(dt, pkg_info["name"] + ".pkg")
    if not (os.path.isfile(hed_path) and os.path.isfile(pkg_path)):
        return "arquivo não encontrado"
    hed = sha1(open(hed_path, "rb").read())
    size = os.path.getsize(pkg_path)
    if size < pkg_info["orig_size"]:
        return "tamanho do .pkg não confere (versão diferente do jogo?)"
    with open(pkg_path, "rb") as f:
        if probe_hashes(f, pkg_info["orig_size"]) != (pkg_info["probe_head"], pkg_info["probe_tail"]):
            return "conteúdo do .pkg não confere (versão diferente do jogo?)"
    if hed == pkg_info["new_hed_sha1"] and size == pkg_info["new_size"]:
        return "aplicado"
    if hed == pkg_info["orig_hed_sha1"]:
        return "vanilla" if size == pkg_info["orig_size"] else "interrompido"
    return ".hed não confere (versão diferente do jogo ou outro mod aplicado)"


def read_blob(patch, base, blob):
    patch.seek(base + blob[0])
    return zlib.decompress(patch.read(blob[1]))


def write_hed(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def apply_package(dt, patch, base, info):
    pkg_path = os.path.join(dt, info["name"] + ".pkg")
    new_hed = read_blob(patch, base, info["new_hed"])
    total = info["new_size"] - info["orig_size"]
    dec = zlib.decompressobj()
    h = hashlib.sha1()
    done = 0
    patch.seek(base + info["tail"][0])
    left = info["tail"][1]
    with open(pkg_path, "r+b") as pkg:
        pkg.truncate(info["orig_size"])
        pkg.seek(info["orig_size"])
        try:
            while left or dec.unconsumed_tail:
                if left:
                    c = patch.read(min(CHUNK, left))
                    left -= len(c)
                else:
                    c = b""
                out = dec.decompress(dec.unconsumed_tail + c, CHUNK)
                h.update(out)
                pkg.write(out)
                done += len(out)
                print(f"\r  {info['name']}.pkg: {done * 100 // total:3d}%", end="", flush=True)
            out = dec.flush()
            h.update(out)
            pkg.write(out)
            done += len(out)
            if done != total or h.hexdigest() != info["tail_sha1"]:
                raise IOError("dados do patch corrompidos")
        except BaseException:
            pkg.truncate(info["orig_size"])
            raise
    print()
    write_hed(os.path.join(dt, info["name"] + ".hed"), new_hed)


def remove_package(dt, patch, base, info):
    write_hed(os.path.join(dt, info["name"] + ".hed"), read_blob(patch, base, info["orig_hed"]))
    with open(os.path.join(dt, info["name"] + ".pkg"), "r+b") as pkg:
        pkg.truncate(info["orig_size"])
    print(f"  {info['name']}: restaurado")


def main():
    print("=" * 60)
    print(TITLE)
    print("=" * 60)
    patch_path = os.path.join(base_dir(), PATCH_NAME)
    if not os.path.isfile(patch_path):
        print(f"Não encontrei {PATCH_NAME} ao lado do instalador.")
        return 1

    dt = find_dt(ask_folder())
    if not dt:
        print("Não encontrei os arquivos kh2_*.hed/.pkg nessa pasta.")
        return 1
    print("Pasta dos arquivos:", dt)

    with open(patch_path, "rb") as patch:
        header, base = read_header(patch)
        packages = header["packages"]
        print("Verificando arquivos...")
        states = {p["name"]: state_of(dt, p) for p in packages}
        for name, st in states.items():
            print(f"  {name}: {st}")
        bad = [n for n, s in states.items() if s not in ("vanilla", "aplicado", "interrompido")]
        if bad:
            print("\nArquivos incompatíveis. Nada foi alterado.")
            return 1

        if all(s == "aplicado" for s in states.values()):
            ans = input("\nA tradução já está instalada. Deseja REMOVER? (s/N): ")
            if ans.strip().lower() != "s":
                return 0
            for p in packages:
                remove_package(dt, patch, base, p)
            print("\nTradução removida. Arquivos voltaram ao original.")
            return 0

        ans = input("\nInstalar a tradução? (S/n): ")
        if ans.strip().lower() == "n":
            return 0
        for p in packages:
            if states[p["name"]] != "aplicado":
                apply_package(dt, patch, base, p)
        print("\nVerificando instalação...")
        for p in packages:
            st = state_of(dt, p)
            print(f"  {p['name']}: {st}")
            if st != "aplicado":
                print("Falha na verificação.")
                return 1
    print("\nTradução instalada com sucesso!")
    print("Para remover, execute o instalador de novo na mesma pasta.")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        code = 1
    except Exception as exc:
        print("\nErro:", exc)
        code = 1
    if not os.environ.get("KH2_FROM_BAT"):
        input("\nPressione Enter para sair...")
    sys.exit(code)
