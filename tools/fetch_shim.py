#!/usr/bin/env python3
"""Télécharge le shim signé Microsoft (Ubuntu shim-signed) + MokManager.
Le shim est le 1er étage signé par la clé Microsoft (db) ; il charge ensuite
notre grubx64.efi signé avec notre propre clé MOK.
Sortie : work/shim/shimx64.efi et work/shim/mmx64.efi (MokManager).
"""
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import netutil as _net  # HTTP avec retry+backoff (transitoires 5xx vus en CI)
REPO = os.path.dirname(HERE)
POOL = "https://archive.ubuntu.com/ubuntu/pool/main/s/shim-signed/"


def fetch(url, dest, timeout=300):
    _net.http_get(url, dest=dest, timeout=timeout)   # retry+backoff, .part atomique, echec franc




def extract_deb(path):
    """Parse un .deb (ar) en pur Python -> {nom: bytes}."""
    out = {}
    with open(path, "rb") as f:
        magic = f.read(8)
        assert magic == b"!<arch>\n", "pas un .deb ar"
        while True:
            hdr = f.read(60)
            if len(hdr) < 60:
                break
            name = hdr[0:16].decode().strip()
            size = int(hdr[48:58].decode().strip())
            data = f.read(size)
            if size % 2:
                f.read(1)
            out[name.rstrip("/")] = data
    return out


def decompress(data):
    import io
    if data[:4] == b"\xfd7zXZ":  # xz
        import lzma
        return lzma.decompress(data)
    if data[:4] == b"\x28\xb5\x2f\xfd":  # zstd
        try:
            import zstandard
            return zstandard.ZstdDecompressor().decompress(data)
        except ImportError:
            # repli : outil zstd système
            import subprocess, tempfile
            with tempfile.NamedTemporaryFile(delete=False) as tf:
                tf.write(data)
                tmp = tf.name
            r = subprocess.run(["zstd", "-d", "-c", tmp], capture_output=True, check=True)
            os.unlink(tmp)
            return r.stdout
    if data[:2] == b"\x1f\x8b":  # gzip
        import gzip
        return gzip.decompress(data)
    return data


def pe_signed(blob):
    """True si le PE/COFF a une table de certificats non vide (signature embarquee).
    Un shim NON signe est rejete par le firmware sous Secure Boot (Access Denied)."""
    try:
        peoff = int.from_bytes(blob[0x3C:0x40], "little")
        opt = peoff + 24
        magic = int.from_bytes(blob[opt:opt + 2], "little")  # 0x20b = PE32+
        ddoff = opt + (112 if magic == 0x20b else 96)
        cert_size = int.from_bytes(blob[ddoff + 4 * 8 + 4:ddoff + 4 * 8 + 8], "little")
        return cert_size > 0
    except Exception:
        return False


# variantes du paquet shim-signed, de la plus preferee a la moins :
# shimx64.efi (non signe) existe AUSSI dans le paquet et ne doit JAMAIS etre choisi
PREF = {
    "shimx64.efi": ["shimx64.efi.signed.latest", "shimx64.efi.dualsigned",
                    "shimx64.efi.signed", "shimx64.efi"],
    "mmx64.efi":   ["mmx64.efi.signed.latest", "mmx64.efi.signed", "mmx64.efi"],
}


def main():
    dest_dir = os.path.join(REPO, "work", "shim")
    os.makedirs(dest_dir, exist_ok=True)
    marker = os.path.join(dest_dir, "shimx64.efi")
    if os.path.exists(marker) and os.path.exists(os.path.join(dest_dir, "mmx64.efi")):
        print("[shim] déjà présent, skip")
        return
    print("[shim] liste du pool Ubuntu...", flush=True)
    html = _net.http_get(POOL, timeout=60).decode()
    debs = re.findall(r'href="(shim-signed_[^"]+_amd64\.deb)"', html)
    if not debs:
        raise RuntimeError("aucun .deb shim-signed trouvé dans le pool")
    def vkey(name):
        m = re.match(r"shim-signed_([0-9][0-9.+~+-]*)", name)
        return [int(x) if x.isdigit() else x for x in re.split(r"[.+~-]", m.group(1))] if m else [0]
    deb = sorted(debs, key=vkey)[-1]  # vraie version la plus haute (pas un tri alpha)
    print("[shim] dernier paquet :", deb, flush=True)
    with tempfile.TemporaryDirectory() as td:
        dpath = os.path.join(td, deb)
        fetch(POOL + deb, dpath)
        members = extract_deb(dpath)  # dict nom -> bytes, sans outil externe
        import tarfile, io
        data = members.get("data.tar.zst") or members.get("data.tar.xz") or members.get("data.tar.gz")
        if data is None:
            raise RuntimeError("data.tar.* introuvable dans le .deb")
        tf = tarfile.open(fileobj=io.BytesIO(decompress(data)), mode="r|*")
        cand = {k: {} for k in PREF}
        for m in tf:
            base = os.path.basename(m.name)
            for key in PREF:
                if base in PREF[key]:
                    cand[key][base] = tf.extractfile(m).read()
        got = {}
        for key, prefs in PREF.items():
            for pref in prefs:
                if pref in cand[key] and pe_signed(cand[key][pref]):
                    got[key] = cand[key][pref]
                    break
            if key not in got:
                raise RuntimeError("%s: aucune variante SIGNEE trouvee dans shim-signed "
                                   "(un shim non signe est rejete sous Secure Boot)" % key)
        for name, blob in got.items():
            open(os.path.join(dest_dir, name), "wb").write(blob)
    print("[shim] OK (variantes signees verifiees) ->", dest_dir, flush=True)


if __name__ == "__main__":
    sys.exit(main())
