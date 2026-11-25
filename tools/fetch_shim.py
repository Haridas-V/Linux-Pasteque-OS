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
REPO = os.path.dirname(HERE)
POOL = "https://archive.ubuntu.com/ubuntu/pool/main/s/shim-signed/"


def fetch(url, dest, timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": "pasteque-build/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            c = r.read(1 << 20)
            if not c:
                break
            f.write(c)




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


def main():
    dest_dir = os.path.join(REPO, "work", "shim")
    os.makedirs(dest_dir, exist_ok=True)
    marker = os.path.join(dest_dir, "shimx64.efi")
    if os.path.exists(marker) and os.path.exists(os.path.join(dest_dir, "mmx64.efi")):
        print("[shim] déjà présent, skip")
        return
    print("[shim] liste du pool Ubuntu...", flush=True)
    html = urllib.request.urlopen(urllib.request.Request(POOL, headers={"User-Agent": "pasteque-build/1.0"}), timeout=60).read().decode()
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
        got = {}
        for m in tf:
            base = os.path.basename(m.name)
            if base in ("shimx64.efi.signed", "shimx64.efi"):
                got["shimx64.efi"] = tf.extractfile(m).read()
            elif base in ("mmx64.efi.signed", "mmx64.efi"):
                got["mmx64.efi"] = tf.extractfile(m).read()
        if "shimx64.efi" not in got:
            raise RuntimeError("shimx64.efi.signed absent du paquet")
        for name, blob in got.items():
            open(os.path.join(dest_dir, name), "wb").write(blob)
    print("[shim] OK ->", dest_dir, flush=True)


if __name__ == "__main__":
    sys.exit(main())
