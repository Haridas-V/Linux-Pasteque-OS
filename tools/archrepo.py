#!/usr/bin/env python3
"""Minimal Arch repository client (no pacman needed).

Reads core/extra/multilib .db files from a mirror, resolves the dependency
closure of a package list and downloads + extracts .pkg.tar.zst into a rootfs
directory. Used only to BOOTSTRAP pacman itself in rootless sandboxes; the real
system is then installed by pacman inside a chroot (see build_sandbox.py).
"""
import io
import os
import re
import tarfile
import urllib.request

import zstandard

MIRROR = os.environ.get("ARCH_MIRROR", "https://geo.mirror.pkgbuild.com")
REPOS = ["core", "extra", "multilib"]
ARCH = "x86_64"

_dctx = zstandard.ZstdDecompressor()


def http_get(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": "pasteque-build/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    if dest:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
    return data


def load_db(repo, cache_dir):
    """Return {pkgname: pkginfo} for a repo. pkginfo has filename/depends/provides."""
    os.makedirs(cache_dir, exist_ok=True)
    db_path = os.path.join(cache_dir, repo + ".db")
    if not os.path.exists(db_path):
        print("[arch] downloading %s.db ..." % repo, flush=True)
        http_get("%s/%s/os/%s/%s.db" % (MIRROR, repo, ARCH, repo), db_path)
    pkgs = {}
    with tarfile.open(db_path, "r:gz") as tf:
        for m in tf.getmembers():
            if not m.name.endswith("/desc"):
                continue
            data = tf.extractfile(m).read().decode("utf-8", "replace")
            info = {"depends": [], "provides": [], "name": None}
            cur = None
            for line in data.splitlines():
                if line.startswith("%") and line.endswith("%"):
                    cur = line.strip("%")
                    continue
                if cur == "NAME" and not info["name"]:
                    info["name"] = line
                elif cur == "FILENAME" and not info.get("filename"):
                    info["filename"] = line
                elif cur == "DEPENDS":
                    info["depends"].append(line)
                elif cur == "PROVIDES":
                    info["provides"].append(line)
            if info["name"]:
                pkgs[info["name"]] = info
    return pkgs


def _dep_name(d):
    return re.split(r"[<>=]", d.strip(), 1)[0].strip()


class RepoSet:
    def __init__(self, cache_dir, repos=REPOS):
        self.dbs = {r: load_db(r, cache_dir) for r in repos}
        self.provides = {}
        for r in repos:
            for name, info in self.dbs[r].items():
                self.provides.setdefault(name, (r, name))
                for p in info["provides"]:
                    self.provides.setdefault(_dep_name(p), (r, name))

    def find(self, name):
        for r in REPOS:
            if name in self.dbs.get(r, {}):
                return r, name
        if name in self.provides:
            return self.provides[name]
        return None

    def resolve(self, targets):
        """Dependency closure (order: deps first). Returns list of (repo, name, info)."""
        seen = {}
        order = []

        def visit(name, stack):
            key = name
            if key in seen:
                return
            found = self.find(name)
            if not found:
                print("[arch] WARN: no provider for %s (from %s)" % (name, stack[-1] if stack else "?"), flush=True)
                return
            repo, pkg = found
            info = self.dbs[repo][pkg]
            if pkg in seen:
                return
            seen[pkg] = (repo, info)
            for d in info["depends"]:
                visit(_dep_name(d), stack + [pkg])
            order.append(pkg)

        for t in targets:
            visit(t, [])
        return [seen[p] for p in order]

    def download(self, repo, info, dest_dir):
        fn = info["filename"]
        dest = os.path.join(dest_dir, fn)
        if not os.path.exists(dest):
            url = "%s/%s/os/%s/%s" % (MIRROR, repo, ARCH, fn)
            print("[arch] GET %s" % fn, flush=True)
            http_get(url, dest)
        return dest


def extract_pkg(path, rootfs):
    """Extract a .pkg.tar.zst into rootfs (like tar -xpf, keeping .INSTALL etc.)."""
    import tempfile
    tmp = path + ".raw"
    with open(path, "rb") as f, open(tmp, "wb") as o:
        with _dctx.stream_reader(f) as r:
            while True:
                chunk = r.read(1 << 22)
                if not chunk:
                    break
                o.write(chunk)
    try:
        with tarfile.open(tmp, "r:") as tf:
            tf.extractall(rootfs, filter="fully_trusted")
    finally:
        os.unlink(tmp)


def bootstrap_pacman(rootfs, cache_dir, extra=("ca-certificates",)):
    import subprocess
    rs = RepoSet(cache_dir)
    pkgs = rs.resolve(["pacman"] + list(extra))
    os.makedirs(rootfs, exist_ok=True)
    subprocess.run(["chmod", "-R", "u+w", rootfs], check=False)
    dl = os.path.join(cache_dir, "pkgs")
    for repo, info in pkgs:
        extract_pkg(rs.download(repo, info, dl), rootfs)
    return rs


if __name__ == "__main__":
    import sys
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/archcache"
    rootfs = sys.argv[2] if len(sys.argv) > 2 else "/tmp/rootfs"
    bootstrap_pacman(rootfs, cache, extra=["ca-certificates"])
    print("bootstrap done ->", rootfs)
