#!/usr/bin/env python3
"""Fetch Debian .deb build tools WITHOUT root and extract them into tools/root/.

Pure Python (no apt-get): reads the trixie Packages index, resolves the
dependency closure of the requested packages, downloads the .debs from the
mirror and extracts them (ar + tar, zstd via the `zstandard` module).
Works identically on a dev machine, in the sandbox and on a CI runner.

Usage: python3 tools/fetch_deb_tools.py [package ...]
Env:   DEB_SUITE (default: trixie), DEB_MIRROR (default: https://deb.debian.org/debian)
"""
import io
import lzma
import os
import re
import shutil
import tarfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "root")
WORK = os.path.join(HERE, ".aptwork")

SUITE = os.environ.get("DEB_SUITE", "trixie")
MIRROR = os.environ.get("DEB_MIRROR", "https://deb.debian.org/debian")

DEFAULT_PACKAGES = [
    # ISO assembly
    "xorriso", "grub-pc-bin", "grub-efi-amd64-bin", "grub-common", "grub2-common",
    "mtools", "dosfstools", "squashfs-tools", "cpio", "rsync",
    "syslinux-common", "syslinux", "isolinux", "syslinux-utils",
    # Secure Boot : signature EFI (sbsign) + CMS modules + openssl
    "sbsigntools", "openssl", "python3-cryptography",
    # compression libs used by the tools above
    "zstd", "xz-utils", "libzstd1", "liblzma5", "bzip2",
    # VM tests
    "qemu-system-x86", "qemu-system-common", "qemu-system-data", "qemu-utils",
    "ovmf",
]


def http_get(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": "pasteque-build/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    if dest:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
    return data


def load_index():
    """Return {package: {"Filename":..., "Depends": [...], "Provides": [...]}}."""
    os.makedirs(WORK, exist_ok=True)
    pkg_file = os.path.join(WORK, "Packages")
    if not os.path.exists(pkg_file):
        url = "%s/dists/%s/main/binary-amd64/Packages.xz" % (MIRROR, SUITE)
        print("[deb] index", url, flush=True)
        raw = lzma.decompress(http_get(url))
        with open(pkg_file, "wb") as f:
            f.write(raw)
    pkgs = {}
    cur = {}
    last_key = None
    for line in open(pkg_file, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if not line:
            if cur.get("Package"):
                pkgs[cur["Package"]] = cur
            cur = {}
            last_key = None
            continue
        if line.startswith((" ", "\t")) and last_key:
            cur[last_key] += "\n" + line.strip()
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            cur[k] = v.strip()
            last_key = k
    if cur.get("Package"):
        pkgs[cur["Package"]] = cur
    return pkgs


def dep_names(dep_field):
    """'a (>= 1) | b, c:any' -> ['a', 'c'] (première alternative résolvable plus tard)."""
    out = []
    for alt_group in (dep_field or "").split(","):
        alts = [a.strip() for a in alt_group.split("|")]
        alts = [re.split(r"\s*\(", a)[0].strip() for a in alts]
        alts = [a.split(":")[0] for a in alts if a]
        if alts:
            out.append(alts)
    return out


def resolve(pkgs, targets):
    provides = {}
    for name, info in pkgs.items():
        for p in re.findall(r"([^\s,()]+)", info.get("Provides", "")):
            provides.setdefault(p.split(":")[0], name)
    seen = set()
    order = []

    def visit(name):
        if name in seen:
            return
        real = name if name in pkgs else provides.get(name)
        if not real:
            print("[deb] WARN: introuvable:", name, flush=True)
            return
        seen.add(name)
        info = pkgs[real]
        if real not in order:
            pass
        for group in dep_names(info.get("Depends", "")):
            for alt in group:
                if alt in pkgs or alt in provides:
                    visit(alt)
                    break
        if real not in order:
            order.append(real)

    for t in targets:
        visit(t)
    return [pkgs[p] for p in order]


def ar_members(data):
    assert data[:8] == b"!<arch>\n", "not an ar archive"
    off = 8
    while off + 60 <= len(data):
        name = data[off:off + 16].decode("ascii", "replace").rstrip()
        size = int(data[off + 48:off + 58].decode().strip())
        yield name.rstrip("/"), data[off + 60:off + 60 + size]
        off += 60 + size + (size % 2)


def extract_deb(path, dest):
    import zstandard
    with open(path, "rb") as f:
        data = f.read()
    for name, body in ar_members(data):
        if name.startswith("data.tar"):
            if name.endswith(".zst"):
                raw = zstandard.ZstdDecompressor().decompress(body, max_output_size=1024 * 1024 * 1024)
                tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
            elif name.endswith(".xz"):
                tf = tarfile.open(fileobj=io.BytesIO(lzma.decompress(body)), mode="r:")
            else:
                tf = tarfile.open(fileobj=io.BytesIO(body), mode="r:")
            tf.extractall(dest, filter="fully_trusted")
            return
    raise RuntimeError("no data.tar in %s" % path)


def main():
    import sys
    packages = sys.argv[1:] or DEFAULT_PACKAGES
    os.makedirs(ROOT, exist_ok=True)
    pkgs = load_index()
    resolved = resolve(pkgs, packages)
    dl = os.path.join(WORK, "debs")
    os.makedirs(dl, exist_ok=True)
    print("[deb] %d paquets à télécharger" % len(resolved), flush=True)
    for info in resolved:
        fn = info["Filename"]
        dest = os.path.join(dl, os.path.basename(fn))
        if not os.path.exists(dest):
            http_get("%s/%s" % (MIRROR, fn), dest)
    print("[deb] extraction dans", ROOT, flush=True)
    for info in resolved:
        extract_deb(os.path.join(dl, os.path.basename(info["Filename"])), ROOT)
    # QEMU a besoin des BIOS SeaBIOS dans son datadir : copie depuis le paquet seabios
    seabios = os.path.join(ROOT, "usr/share/seabios")
    qemudata = os.path.join(ROOT, "usr/share/qemu")
    if os.path.isdir(seabios) and os.path.isdir(qemudata):
        for f in os.listdir(seabios):
            if f.endswith(".bin") or f.endswith(".rom"):
                dst = os.path.join(qemudata, f)
                if not os.path.exists(dst):
                    shutil.copy2(os.path.join(seabios, f), dst)
    print("[deb] OK. Tools root:", ROOT, flush=True)


if __name__ == "__main__":
    main()
