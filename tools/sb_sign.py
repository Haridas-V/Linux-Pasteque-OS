#!/usr/bin/env python3
"""Signature Secure Boot de la Pasteque ISO (etape build 'secureboot').

Format EXACT de scripts/sign-file du noyau (kernel >= 4.x) :
    [ module (eventuellement compressé) ][ CMS DER ][ header 12 octets ][ magic ]
    - header: algo=0, hash=0, id_type=2 (PKEY_ID_PKCS7), signer_len=0, key_id_len=0,
      pad=0, sig_len=BE32(len(CMS))   (le noyau utilise SON propre hash compile)
    - magic "~Module signature appended~\\n" est le DERNIER bloc du fichier
    - CMS: detached, NOCERTS, NOATTR, BINARY, NOSMIMECAP, md = CONFIG_MODULE_SIG_HASH
    - pour un .ko.zst/.xz/.gz : le CMS est calcule sur le module DECOMPRESSE
      (le noyau decompresse puis verifie la signature sur le contenu brut;
       kmod ne reconnait la signature que si le magic est en dernier)

Le hash est lu depuis la config embarquee du noyau (IKCONFIG / /proc/config.gz),
pas suppose : CONFIG_MODULE_SIG_HASH (sha512 sur Arch).

Echec strict : si sbsign/openssl manquent ou qu'une signature echoue, on sort
en erreur (exit 1) — jamais de "succes" annonce sans tout signer.

Usage : python3 tools/sb_sign.py [--skip-modules] [--efi-only]
Variables : SB_KEY / SB_CRT pour reutiliser une cle existante (ex: fournie en CI).
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WORK = os.path.join(REPO, "work")
ROOTFS = os.path.join(WORK, "rootfs")
TROOT = os.path.join(REPO, "tools", "root")
SB = os.path.join(WORK, "sb")

MAGIC = b"~Module signature appended~\n"          # 28 octets, DERNIER bloc
HEADER_LEN = 12

SBSIGN = os.path.join(TROOT, "usr/bin/sbsign") if os.path.exists(os.path.join(TROOT, "usr/bin/sbsign")) else shutil.which("sbsign")
SBVERIFY = os.path.join(TROOT, "usr/bin/sbverify") if os.path.exists(os.path.join(TROOT, "usr/bin/sbverify")) else shutil.which("sbverify")
OPENSSL = os.path.join(TROOT, "usr/bin/openssl") if os.path.exists(os.path.join(TROOT, "usr/bin/openssl")) else shutil.which("openssl")


def run(cmd, **kw):
    print("[sb]", " ".join(cmd), flush=True)
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ensure_tools():
    """Strict : sans sbsign ni openssl, on ne peut PAS produire une ISO Secure Boot
    complete -> echec franc (pas de degradation silencieuse)."""
    missing = []
    if not SBSIGN:
        missing.append("sbsign (paquet sbsigntool)")
    if not OPENSSL:
        missing.append("openssl")
    if missing:
        print("[sb] ERREUR: outils manquants: %s -> impossible de signer, build STOPPE" % ", ".join(missing),
              file=sys.stderr)
        sys.exit(1)


def kernel_sig_hash(rootfs):
    """Lit CONFIG_MODULE_SIG_HASH depuis la config embarquee (IKCONFIG) du noyau.
    Repli: sha512 (valeur Arch)."""
    for vmlinuz in glob.glob(os.path.join(rootfs, "usr/lib/modules/*/vmlinuz")) + \
                   glob.glob(os.path.join(rootfs, "boot/vmlinuz-*")):
        try:
            data = open(vmlinuz, "rb").read()
        except OSError:
            continue
        i = data.find(b"IKCFG_ST")
        j = data.find(b"IKCFG_ED", i + 8) if i >= 0 else -1
        if i >= 0 and j > i:
            import gzip
            try:
                cfg = gzip.decompress(data[i + 8:j]).decode("utf-8", "replace")
                m = re.search(r'CONFIG_MODULE_SIG_HASH="(\w+)"', cfg)
                if m:
                    print("[sb] hash module lu depuis IKCONFIG:", m.group(1), flush=True)
                    return m.group(1)
                m2 = re.search(r"CONFIG_MODULE_SIG_SHA(\d+)=y", cfg)
                if m2:
                    return "sha" + m2.group(1)
            except Exception as e:
                print("[sb] IKCONFIG illisible (%s), repli sha512" % e, flush=True)
    print("[sb] IKCONFIG absent, hash par defaut: sha512", flush=True)
    return "sha512"


def ensure_key():
    os.makedirs(SB, exist_ok=True)
    key = os.environ.get("SB_KEY") or os.path.join(SB, "sb.key")
    crt = os.environ.get("SB_CRT") or os.path.join(SB, "sb.crt")
    der = os.path.join(SB, "Pasteque.der")
    if not (os.path.exists(key) and os.path.exists(crt)):
        print("[sb] generation d'une nouvelle paire de cles SB (CN=Pasteque Linux SB)...", flush=True)
        r = run([OPENSSL, "req", "-new", "-x509", "-newkey", "rsa:3072", "-nodes",
                 "-keyout", key, "-out", crt, "-days", "3650",
                 "-subj", "/CN=Pasteque Linux Secure Boot/O=Pasteque Linux"])
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            sys.exit(1)
    r = run([OPENSSL, "x509", "-in", crt, "-outform", "DER", "-out", der])
    if r.returncode != 0 or not os.path.exists(der):
        print("[sb] ERREUR export DER", r.stderr[-300:], file=sys.stderr)
        sys.exit(1)
    # cle publique MOK dans l'airootfs (enrolement au 1er boot, voir SECURE_BOOT.md)
    mokdir = os.path.join(ROOTFS, "usr/share/pasteque/mok")
    os.makedirs(mokdir, exist_ok=True)
    shutil.copy2(der, os.path.join(mokdir, "Pasteque.der"))
    with open(os.path.join(mokdir, "FINGERPRINT.txt"), "w") as f:
        f.write(run([OPENSSL, "x509", "-in", crt, "-noout", "-fingerprint", "-sha256"]).stdout)
    print("[sb] cle prete :", crt, flush=True)
    return key, crt, der


def sbsign(src, dst, key, crt):
    r = run([SBSIGN, "--key", key, "--cert", crt, "--output", dst, src])
    if r.returncode != 0 or not os.path.exists(dst):
        print("[sb] ERREUR sbsign", src, r.stderr[-300:], file=sys.stderr)
        sys.exit(1)
    if SBVERIFY:
        # sbverify attend un certificat PEM (le DER sert au MOK/mokutil)
        v = run([SBVERIFY, "--cert", crt, dst])
        if v.returncode != 0:
            print("[sb] ERREUR sbverify", dst, v.stderr[-300:], file=sys.stderr)
            sys.exit(1)
    print("[sb] signe + verifie:", os.path.basename(dst), flush=True)


def kernel_targets(rootfs):
    """Chemins REELS (realpath, dedupliques, tries) des noyaux a signer dans la rootfs.

    /boot/vmlinuz-linux est un SYMLINK vers usr/lib/modules/<kver>/vmlinuz (cree par
    l'etape initramfs, qui tourne APRES l'etape secureboot dans 'all') : a l'etape
    secureboot ce fichier n'existe peut-etre pas encore, et os.replace(tmp, lien)
    remplacerait le LIEN sans signer la cible. Et step_iso copie le noyau de l'ISO
    depuis usr/lib/modules/<kver>/vmlinuz. -> on signe toujours la CIBLE reelle."""
    seen, out = set(), []
    cands = glob.glob(os.path.join(rootfs, "usr/lib/modules", "*", "vmlinuz")) + \
            glob.glob(os.path.join(rootfs, "boot", "vmlinuz-*"))
    for c in sorted(cands):
        real = os.path.realpath(c)
        if real in seen or not os.path.isfile(real):
            continue
        seen.add(real)
        out.append(real)
    return out


def sign_efi_and_kernels(key, crt):
    # grub EFI (sera renomme grubx64.efi, charge par le shim) — present seulement
    # apres step_iso (efiwork) ; sinon signe en --efi-only a ce moment-la.
    grub_src = os.path.join(WORK, "efiwork", "EFI/BOOT/BOOTX64.EFI")
    if os.path.exists(grub_src):
        sbsign(grub_src, os.path.join(WORK, "efiwork", "EFI/BOOT/grubx64.efi"), key, crt)
    # noyaux (EFI stub) signes IN PLACE sur leur chemin REEL — jamais via un symlink
    # (regression reproduite en local : noyau de l'ISO non signe, sbverify 'No signature
    # table present', boot SB 'error: bad shim signature'). STRICT : aucun noyau trouve
    # = build STOPPE (jamais de "succes" annonce sans noyau signe).
    kernels = kernel_targets(ROOTFS)
    if not kernels:
        print("[sb] ERREUR: aucun noyau dans %s (usr/lib/modules/*/vmlinuz) -> "
              "boot Secure Boot impossible, build STOPPE" % ROOTFS, file=sys.stderr, flush=True)
        sys.exit(1)
    for k in kernels:
        tmp = k + ".signed"
        sbsign(k, tmp, key, crt)   # sbsign() verifie deja la signature avec sbverify --cert
        os.replace(tmp, k)         # signe la cible reelle ; les symlinks /boot/vmlinuz-* restent valides
    # relecture stricte : chaque noyau signe doit avoir une table de certificats PE non vide
    sys.path.insert(0, HERE)
    from fetch_shim import pe_signed
    for k in kernels:
        if not pe_signed(open(k, "rb").read()):
            print("[sb] ERREUR: %s sans table de certificats PE apres sbsign -> build STOPPE" % k,
                  file=sys.stderr, flush=True)
            sys.exit(1)
        print("[sb] noyau signe + verifie (cert PE present):", k, flush=True)


def strip_appended_sig(raw):
    """Retire une signature 'module signature appended' existante (Arch signe
    deja ses modules a la construction) : [data][cms][hdr 12][magic 28]."""
    if len(raw) > len(MAGIC) + HEADER_LEN and raw[-len(MAGIC):] == MAGIC:
        sig_len = int.from_bytes(raw[-(len(MAGIC) + HEADER_LEN):-len(MAGIC)][HEADER_LEN - 4:HEADER_LEN], "big")
        return raw[:-(len(MAGIC) + HEADER_LEN + sig_len)]
    return raw


def sign_module(path, key, crt, hash_algo):
    """Signe un module avec notre cle, format sign-file :
    [data][CMS][header 12o][magic 28o en DERNIER], CMS sur le contenu brut.
    Les modules compresses (.ko.zst...) sont DECOMPRESSES, l'ancienne signature
    Arch est strippee, le .ko signe est ecrit EN CLAIR (kmod/depmod ne sait pas
    lire une signature ajoutee apres un frame zstd -> erreurs 'Src size incorrect').
    Retourne le chemin final du module signe."""
    with open(path, "rb") as f:
        data = f.read()
    out = path
    if path.endswith((".ko.zst", ".ko.xz", ".ko.gz")):
        if path.endswith(".ko.zst"):
            suf, comp = ".ko.zst", ".zst"
        elif path.endswith(".ko.xz"):
            suf, comp = ".ko.xz", ".xz"
        else:
            suf, comp = ".ko.gz", ".gz"
        raw = strip_appended_sig(_decompress_bytes(data, comp))
        out = path[: -len(comp)]                # .ko.zst -> .ko (garde le nom du module)
        if out != path:
            os.unlink(path)
        data = raw
    else:
        data = strip_appended_sig(data)
    if len(data) > len(MAGIC) and data[-len(MAGIC):] == MAGIC:
        raise RuntimeError("signature presente apres strip ?! " + path)
    with tempfile.TemporaryDirectory() as td:
        rawf = os.path.join(td, "mod.ko")
        with open(rawf, "wb") as f:
            f.write(data)
        sig = os.path.join(td, "sig.der")
        # CMS detached NOCERTS NOATTR BINARY NOSMIMECAP, md = hash noyau
        r = run([OPENSSL, "cms", "-sign", "-binary", "-nocerts", "-noattr", "-nosmimecap",
                 "-md", hash_algo, "-signer", crt, "-inkey", key,
                 "-in", rawf, "-outform", "DER", "-out", sig])
        if r.returncode != 0:
            raise RuntimeError("cms -sign: " + r.stderr[-300:])
        cms = open(sig, "rb").read()
        # verification croisee immediate de la signature produite
        v = run([OPENSSL, "cms", "-verify", "-binary", "-noverify", "-inform", "DER",
                 "-in", sig, "-certfile", crt, "-content", rawf, "-out", os.devnull])
        if v.returncode != 0:
            raise RuntimeError("cms -verify: " + v.stderr[-300:])
    header = bytes([0, 0, 2, 0, 0, 0, 0, 0]) + len(cms).to_bytes(4, "big")  # algo=0 hash=0 id=2
    with open(out, "wb") as f:
        f.write(data + cms + header + MAGIC)   # ordre sign-file : magic EN DERNIER
    # controle structurel : magic en dernier + sig_len coherent
    with open(out, "rb") as f:
        f.seek(-(len(MAGIC) + HEADER_LEN), os.SEEK_END)
        tail = f.read()
    assert tail[-len(MAGIC):] == MAGIC, "magic non terminal apres signature"
    assert int.from_bytes(tail[HEADER_LEN - 4:HEADER_LEN], "big") == len(cms), "sig_len incoherent"
    return out


def _decompress_bytes(data, suffix):
    if suffix == ".zst":
        try:
            import zstandard
            return zstandard.ZstdDecompressor().stream_reader(data).read()
        except ImportError:
            pass
        import io
        zcli = os.path.join(TROOT, "usr/bin/zstd") if os.path.exists(os.path.join(TROOT, "usr/bin/zstd")) else shutil.which("zstd")
        if zcli:
            return subprocess.run([zcli, "-dc"], input=data, capture_output=True, check=True).stdout
        raise RuntimeError("pas de zstd pour decompresser")
    if suffix == ".xz":
        import lzma
        return lzma.decompress(data)
    if suffix == ".gz":
        import gzip
        return gzip.decompress(data)
    raise RuntimeError("suffixe inconnu " + suffix)


def sign_all_modules(key, crt, hash_algo):
    # TOUS les modules du noyau (kernel/**, updates/**, extra/**) : un .ko.zst restant
    # dans updates/ ou extra/ provoquerait des erreurs depmod dans le systeme installe
    mods = sorted(glob.glob(os.path.join(ROOTFS, "usr/lib/modules/*/**/*.ko*"), recursive=True))
    print("[sb] signature de %d modules (hash=%s, decompression en .ko signe)..." % (len(mods), hash_algo), flush=True)
    n = failed = 0
    final = []
    for m in mods:
        try:
            final.append(sign_module(m, key, crt, hash_algo))
            n += 1
        except Exception as e:
            failed += 1
            print("[sb] ERREUR module non signe:", m, e, flush=True)
        if (n + failed) % 500 == 0:
            print("[sb]  %d/%d (echecs=%d)" % (n + failed, len(mods), failed), flush=True)
    # relecture : chaque module final doit finir par le magic
    unsigned = 0
    for m in final:
        with open(m, "rb") as f:
            f.seek(-len(MAGIC), os.SEEK_END)
            if f.read() != MAGIC:
                unsigned += 1
    print("[sb] modules signes: %d/%d, non signes apres relecture: %d, echecs: %d"
          % (n, len(mods), unsigned, failed), flush=True)
    if failed or unsigned:
        print("[sb] ERREUR: %d modules non signes -> Secure Boot INCOMPLET, build STOPPE" % (failed + unsigned),
              file=sys.stderr)
        sys.exit(1)
    return n


def main():
    skip_modules = "--skip-modules" in sys.argv
    efi_only = "--efi-only" in sys.argv
    ensure_tools()
    key, crt, der = ensure_key()
    hash_algo = kernel_sig_hash(ROOTFS)
    sign_efi_and_kernels(key, crt)
    if not skip_modules and not efi_only:
        n = sign_all_modules(key, crt, hash_algo)
        print("[sb] OK: %d modules signes (hash=%s), cle MOK: %s" % (n, hash_algo, der), flush=True)
    else:
        print("[sb] OK (efi-only/skip-modules), cle MOK: %s" % der, flush=True)


if __name__ == "__main__":
    main()
