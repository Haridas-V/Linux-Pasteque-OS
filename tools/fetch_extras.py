#!/usr/bin/env python3
"""Download the AUR/GitHub "extras" embedded in the ISO (offline install).

Fetches the latest release assets from GitHub into work/extras/ :
  - GE-Proton (proton-ge-custom)  -> Proton-GE par défaut pour Steam
  - wine-ge-custom                -> runner Wine-GE pour Lutris
  - HeroicGamesLauncher AppImage  -> Epic / GOG
  - teams-for-linux AppImage      -> Teams

Usage: python3 tools/fetch_extras.py [destdir]
"""
import fnmatch
import json
import os
import sys
import time
import urllib.request

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


def gh_headers():
    h = {"User-Agent": "pasteque-build/1.0", "Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        h["Authorization"] = "Bearer " + tok  # 5000 req/h au lieu de 60 sans token (rate limit CI)
    return h


def urlopen_retry(req, timeout, tries=4):
    """urlopen avec retry + backoff sur les erreurs transitoires (403 rate limit, 5xx)."""
    last = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            last = e
            code = getattr(e, "code", None)
            if code in (403, 429, 500, 502, 503, 504):
                wait = min(180, 20 * (2 ** i))
                print("[extras] HTTP %s, retry dans %ds... (%s)" % (code, wait, e), flush=True)
                time.sleep(wait)
            else:
                raise
    raise last


def gh_api_latest_assets(repo):
    """Derniers assets de la release 'latest' d'un repo GitHub, via l'API publique (pas besoin de gh)."""
    url = "https://api.github.com/repos/%s/releases/latest" % repo
    req = urllib.request.Request(url, headers=gh_headers())
    with urlopen_retry(req, 120) as r:
        data = json.load(r)
    return [(a["name"], a["browser_download_url"]) for a in data.get("assets", [])]


def download(url, dest):
    req = urllib.request.Request(url, headers=gh_headers())
    with urlopen_retry(req, 600) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


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
                assets = gh_api_latest_assets(repo)
                match = [a for a in assets if fnmatch.fnmatch(a[0], pattern)]
                x86 = [a for a in match if "x86_64" in a[0] and "aarch64" not in a[0].lower() and "arm" not in a[0].lower()]
                if x86:
                    match = x86
                if not match:
                    raise RuntimeError("aucun asset ne correspond au pattern %s" % pattern)
                name, url = match[0]
                print("[extras]   asset: %s" % name, flush=True)
                download(url, os.path.join(out, name))
                break
            except Exception as e:
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
