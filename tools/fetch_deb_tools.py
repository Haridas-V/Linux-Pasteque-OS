#!/usr/bin/env python3
"""Fetch Debian .deb build tools WITHOUT root and extract them into tools/root/.

Used in sandboxes/CI where apt install is impossible (no root). On a normal
Debian/Arch host you do not need this: build.sh uses the system tools.

Usage: python3 tools/fetch_deb_tools.py [package ...]
Env:   DEB_SUITE (default: trixie), DEB_MIRROR (default: https://deb.debian.org/debian)
"""
import io
import lzma
import os
import shutil
import subprocess
import sys
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
    "syslinux-common", "syslinux", "isolinux",
    # compression libs used by the tools above
    "zstd", "xz-utils", "libzstd1", "liblzma5", "bzip2",
    # VM tests
    "qemu-system-x86", "qemu-system-common", "qemu-system-data", "qemu-utils",
]


def http_get(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": "pasteque-build/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if dest:
        with open(dest, "wb") as f:
            f.write(data)
    return data


def seed_apt_lists():
    lists = os.path.join(WORK, "lists")
    os.makedirs(os.path.join(lists, "partial"), exist_ok=True)
    os.makedirs(os.path.join(WORK, "archives", "partial"), exist_ok=True)
    prefix = "deb.debian.org_debian_dists_%s_" % SUITE
    pkg_xz = os.path.join(lists, prefix + "main_binary-amd64_Packages.xz")
    pkg_file = os.path.join(lists, prefix + "main_binary-amd64_Packages")
    if not os.path.exists(pkg_file):
        url = "%s/dists/%s/main/binary-amd64/Packages.xz" % (MIRROR, SUITE)
        print("[deb] downloading package index", url, flush=True)
        http_get(url, pkg_xz)
        with lzma.open(pkg_xz) as f, open(pkg_file, "wb") as o:
            shutil.copyfileobj(f, o)
    inrel = os.path.join(lists, prefix + "InRelease")
    if not os.path.exists(inrel):
        try:
            http_get("%s/dists/%s/InRelease" % (MIRROR, SUITE), inrel)
        except Exception as e:
            print("[deb] InRelease unavailable (%s), continuing with trusted=yes" % e, flush=True)
    src = os.path.join(WORK, "sources.list")
    with open(src, "w") as f:
        f.write("deb [trusted=yes] %s %s main\n" % (MIRROR, SUITE))
    return src


def apt_download(packages):
    src = seed_apt_lists()
    status = os.path.join(WORK, "status")
    if not os.path.exists(status):
        open(status, "w").close()
    cmd = [
        "apt-get",
        "-o", "Dir::Etc::sourcelist=%s" % src,
        "-o", "Dir::Etc::sourceparts=/dev/null",
        "-o", "Dir::State::Lists=%s" % os.path.join(WORK, "lists"),
        "-o", "Dir::State::status=%s" % status,
        "-o", "Debug::NoLocking=1",
        "-o", "Dir::Cache=%s" % WORK,
        "-o", "APT::Get::ListCleanup=0",
        "-o", "Acquire::AllowInsecureRepositories=1",
        "-o", "APT::Get::AllowUnauthenticated=1",
        "-d", "-y", "--no-install-recommends",
        "install",
    ] + packages
    print("[deb] apt-get download:", " ".join(packages), flush=True)
    subprocess.run(cmd, check=True)


def ar_members(data):
    assert data[:8] == b"!<arch>\n", "not an ar archive"
    off = 8
    while off + 60 <= len(data):
        name = data[off:off + 16].decode("ascii", "replace").rstrip()
        size = int(data[off + 48:off + 58].decode().strip())
        body = data[off + 60:off + 60 + size]
        yield name.rstrip("/"), body
        off += 60 + size + (size % 2)


def extract_deb(path, dest):
    import zstandard
    with open(path, "rb") as f:
        data = f.read()
    for name, body in ar_members(data):
        if name.startswith("data.tar"):
            if name.endswith(".zst"):
                raw = zstandard.ZstdDecompressor().decompress(body, max_output_size=512 * 1024 * 1024)
                tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
            elif name.endswith(".xz"):
                tf = tarfile.open(fileobj=io.BytesIO(lzma.decompress(body)), mode="r:")
            else:
                tf = tarfile.open(fileobj=io.BytesIO(body), mode="r:")
            tf.extractall(dest, filter="fully_trusted")
            return
    raise RuntimeError("no data.tar in %s" % path)


def main():
    packages = sys.argv[1:] or DEFAULT_PACKAGES
    os.makedirs(ROOT, exist_ok=True)
    apt_download(packages)
    debs = sorted(
        os.path.join(WORK, "archives", f)
        for f in os.listdir(os.path.join(WORK, "archives"))
        if f.endswith(".deb")
    )
    print("[deb] extracting %d debs into %s" % (len(debs), ROOT), flush=True)
    for d in debs:
        extract_deb(d, ROOT)
    print("[deb] OK. Tools root:", ROOT, flush=True)


if __name__ == "__main__":
    main()
