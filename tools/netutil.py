"""HTTP robuste pour le build Pastèque : retry + backoff exponentiel sur les erreurs
transitoires (5xx type 503 codeberg vu en CI run 45995052877, 429, timeouts).

Regles : ecriture atomique via <dest>.part (jamais de fichier partiel), .part nettoye
apres chaque echec, et RuntimeError FRANCHE si tous les essais echouent — un build ne
doit jamais annoncer un telechargement OK qui ne l'est pas."""
import os
import time
import urllib.request

UA = {"User-Agent": "pasteque-build/1.0"}


def http_get(url, dest=None, tries=5, base=10, timeout=300):
    """GET url. Si dest est donne, ecrit le contenu dans dest (atomique via .part).
    Retourne le contenu (bytes). Retry avec backoff exponentiel (base * 2^i s)."""
    last = None
    for i in range(tries):
        tmp = (dest + ".part") if dest else None
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if dest:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, dest)
            return data
        except Exception as e:
            last = e
            code = getattr(e, "code", None)
            print("[net] %s : essai %d/%d echoue (HTTP %s: %s)" % (url, i + 1, tries, code, e), flush=True)
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
            if i + 1 < tries:
                time.sleep(base * (2 ** i))
    raise RuntimeError("HTTP impossible apres %d essais: %s (%s)" % (tries, url, last))
