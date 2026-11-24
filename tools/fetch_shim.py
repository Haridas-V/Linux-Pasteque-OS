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


def main():
    dest_dir = os.path.join(REPO, "work", "shim")
    os.makedirs(dest_dir, exist_ok=True)
    marker = os.path.join(dest_dir, "shimx64.efi")
    if os.path.exists(marker) and os.path.exists(os.path.join(dest_dir, "mmx64.efi")):
        print("[shim] déjà présent, skip")
        return
    print("[shim] liste du pool Ubuntu...", flush=True)
    html = urllib.request.urlopen(urllib.request.Request(POOL, headers={"User-Agent": "pasteque-build/1.0"}), timeout=60).read().decode()
    debs = sorted(re.findall(r'href="(shim-signed_[^"]+_amd64\.deb)"', html))
    if not debs:
        raise RuntimeError("aucun .deb shim-signed trouvé dans le pool")
    deb = debs[-1]
    print("[shim] dernier paquet :", deb, flush=True)
    with tempfile.TemporaryDirectory() as td:
        dpath = os.path.join(td, deb)
        fetch(POOL + deb, dpath)
        subprocess.run(["ar", "x", dpath, "data.tar.zst"], cwd=td, check=True)
        subprocess.run(["tar", "-xf", "data.tar.zst", "-C", td,
                        "./usr/lib/shim/shimx64.efi.signed", "./usr/lib/shim/mmx64.efi.signed"], check=True)
        import shutil
        shutil.copy2(os.path.join(td, "usr/lib/shim/shimx64.efi.signed"), os.path.join(dest_dir, "shimx64.efi"))
        shutil.copy2(os.path.join(td, "usr/lib/shim/mmx64.efi.signed"), os.path.join(dest_dir, "mmx64.efi"))
    print("[shim] OK ->", dest_dir, flush=True)


if __name__ == "__main__":
    sys.exit(main())
