#!/usr/bin/env python3
"""Download the AUR/GitHub "extras" embedded in the ISO (offline install).

Fetches the latest release assets from GitHub into work/extras/ :
  - GE-Proton (proton-ge-custom)  -> Proton-GE par défaut pour Steam
  - wine-ge-custom                -> runner Wine-GE pour Lutris
  - HeroicGamesLauncher AppImage  -> Epic / GOG
  - teams-for-linux AppImage      -> Teams

Usage: python3 tools/fetch_extras.py [destdir]
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

EXTRAS = [
    # (repos candidats, pattern, prefix de destination)
    (["GloriousEggroll/proton-ge-custom"], "GE-Proton*.tar.gz", "proton-ge"),
    (["GloriousEggroll/wine-ge-custom"], "wine-*-x86_64.tar.xz", "wine-ge"),
    (["Heroic-Games-Launcher/HeroicGamesLauncher", "HeroicGamesLauncher/HeroicGamesLauncher"],
     "Heroic-*.AppImage", "heroic"),
    (["IsmaelMartinez/teams-for-linux"], "teams-for-linux-*.AppImage", "teams"),
]


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "work", "extras")
    os.makedirs(dest, exist_ok=True)
    for repos, pattern, prefix in EXTRAS:
        out = os.path.join(dest, prefix)
        if os.path.exists(out) and os.listdir(out):
            print("[extras] %s déjà présent, skip" % prefix, flush=True)
            continue
        os.makedirs(out, exist_ok=True)
        last_err = None
        for repo in repos:
            print("[extras] %s <- %s (latest, pattern %s)" % (prefix, repo, pattern), flush=True)
            try:
                subprocess.run(["gh", "release", "download", "--repo", repo,
                                "--pattern", pattern, "--dir", out], check=True)
                break
            except subprocess.CalledProcessError as e:
                last_err = e
        else:
            print("[extras] ERREUR %s: %s" % (prefix, last_err), flush=True)
            continue
        # garde uniquement l'asset x86_64 et normalise le nom des AppImages
        apps = [f for f in os.listdir(out) if f.endswith(".AppImage")]
        keep = [f for f in apps if "arm" not in f.lower() and "aarch64" not in f.lower()] or apps
        for f in apps:
            if f not in keep:
                os.remove(os.path.join(out, f))
        if prefix in ("heroic", "teams") and keep:
            target = prefix + ".AppImage"
            if keep[0] != target:
                os.rename(os.path.join(out, keep[0]), os.path.join(out, target))
        for f in os.listdir(out):
            if f.endswith(".AppImage"):
                os.chmod(os.path.join(out, f), 0o755)
    print("[extras] OK ->", dest, flush=True)


if __name__ == "__main__":
    main()
