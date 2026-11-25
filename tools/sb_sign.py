#!/usr/bin/env python3
"""Signature Secure Boot de la Pastèque ISO (étape build 'secureboot') :

1. Génère (ou réutilise) une paire de clés SB dans work/sb/ :
   - sb.key / sb.crt (PEM) pour signer, Pasteque.der (cert DER) pour le MOK.
2. Signe avec sbsign : grub EFI (BOOTX64 -> grubx64.efi signé) et les noyaux
   vmlinuz-linux / vmlinuz-lts (EFI stub).
3. Signe TOUS les modules noyau (.ko) avec une signature CMS (openssl cms),
   format "module signature appended" du noyau.
4. Copie la clé publique MOK dans l'airootfs (/usr/share/pasteque/mok/Pasteque.der)
   pour l'enrôlement au 1er boot (voir pasteque-secureboot).

Usage : python3 tools/sb_sign.py [--skip-modules]
Variables : SB_KEY / SB_CRT pour réutiliser une clé existante (ex: fournie en CI).
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WORK = os.path.join(REPO, "work")
ROOTFS = os.path.join(WORK, "rootfs")
TROOT = os.path.join(REPO, "tools", "root")
SB = os.path.join(WORK, "sb")

import shutil as _sh
SBSIGN = os.path.join(TROOT, "usr/bin/sbsign") if os.path.exists(os.path.join(TROOT, "usr/bin/sbsign")) else _sh.which("sbsign")
OPENSSL = os.path.join(TROOT, "usr/bin/openssl") if os.path.exists(os.path.join(TROOT, "usr/bin/openssl")) else _sh.which("openssl")

MAGIC = b"~Module signature appended~\n"


def run(cmd, **kw):
    print("[sb]", " ".join(cmd), flush=True)
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ensure_tools():
    # degradation gracieuse : sans sbsign on signe quand meme les modules (openssl),
    # le boot Secure Boot complet necessite sbsign (paquet sbsigntool) mais le build ne casse pas.
    if not SBSIGN:
        print("[sb] sbsign absent (paquet sbsigntool) -> EFI/noyaux NON signes, modules signes quand meme", file=sys.stderr)
    if not OPENSSL:
        print("[sb] openssl absent -> aucune signature, SB off requis", file=sys.stderr)
        sys.exit(1)


def ensure_key():
    os.makedirs(SB, exist_ok=True)
    key = os.environ.get("SB_KEY") or os.path.join(SB, "sb.key")
    crt = os.environ.get("SB_CRT") or os.path.join(SB, "sb.crt")
    der = os.path.join(SB, "Pasteque.der")
    if not (os.path.exists(key) and os.path.exists(crt)):
        print("[sb] génération d'une nouvelle paire de clés SB (CN=Pasteque Linux SB)...", flush=True)
        r = run([OPENSSL, "req", "-new", "-x509", "-newkey", "rsa:3072", "-nodes",
                 "-keyout", key, "-out", crt, "-days", "3650",
                 "-subj", "/CN=Pasteque Linux Secure Boot/O=Pasteque Linux"])
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            sys.exit(1)
    run([OPENSSL, "x509", "-in", crt, "-outform", "DER", "-out", der])
    # cle publique MOK dans l'airootfs (enrôlement au 1er boot)
    mokdir = os.path.join(ROOTFS, "usr/share/pasteque/mok")
    os.makedirs(mokdir, exist_ok=True)
    shutil.copy2(der, os.path.join(mokdir, "Pasteque.der"))
    with open(os.path.join(mokdir, "FINGERPRINT.txt"), "w") as f:
        f.write(run([OPENSSL, "x509", "-in", crt, "-noout", "-fingerprint", "-sha256"]).stdout)
    print("[sb] clé prête :", crt, flush=True)
    return key, crt


def sbsign(src, dst, key, crt):
    r = run([SBSIGN, "--key", key, "--cert", crt, "--output", dst, src])
    if r.returncode != 0 or not os.path.exists(dst):
        print("[sb] ERREUR sbsign", src, r.stderr[-300:], file=sys.stderr)
        sys.exit(1)
    print("[sb] signé:", os.path.basename(dst), flush=True)


def sign_efi_and_kernels(key, crt):
    # grub EFI signé (sera renommé grubx64.efi, chargé par le shim)
    grub_src = os.path.join(WORK, "efiwork", "EFI/BOOT/BOOTX64.EFI")
    if os.path.exists(grub_src):
        sbsign(grub_src, os.path.join(WORK, "efiwork", "EFI/BOOT/grubx64.efi"), key, crt)
    # noyaux (EFI stub) signés sur place dans la rootfs
    for kv in ["/boot/vmlinuz-linux", "/boot/vmlinuz-lts"]:
        k = os.path.join(ROOTFS, kv)
        if os.path.exists(k):
            tmp = k + ".signed"
            sbsign(k, tmp, key, crt)
            os.replace(tmp, k)


def sign_module(path, key, crt):
    """Ajoute une signature CMS (PKCS#7) à un .ko : [data][CMS][magic][12-byte header]."""
    with open(path, "rb") as f:
        data = f.read()
    if MAGIC in data[-64:]:
        return  # déjà signé
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        sig = os.path.join(td, "sig.der")
        r = run([OPENSSL, "cms", "-sign", "-binary", "-md", "sha256", "-nocerts" if False else "-signer", crt,
                 "-inkey", key, "-in", path, "-outform", "DER", "-out", sig, "-nosmimecap"])
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-300:])
        with open(sig, "rb") as f:
            cms = f.read()
    # en-tête module_signature : algo=1(RSA) hash=5(sha256) id_type=2(PKCS7) signer_len key_id_len pad[3] sig_len(BE32)
    subj = run([OPENSSL, "x509", "-in", crt, "-noout", "-subject", "-nameopt", "RFC2253"]).stdout
    cn = "Pasteque Linux Secure Boot"
    import re
    m = re.search(r"CN=([^,/]+)", subj)
    if m:
        cn = m.group(1)
    signer = cn.encode()[:255]
    # key id = SKID si dispo, sinon hash du cert
    skid = run([OPENSSL, "x509", "-in", crt, "-noout", "-ext", "subjectKeyIdentifier"]).stdout
    m = re.search(r"([0-9A-F:]{20,})", skid)
    keyid = bytes.fromhex(m.group(1).replace(":", ""))[:255] if m else b"pasteque-sb"
    header = bytes([1, 5, 2, len(signer), len(keyid), 0, 0, 0]) + len(cms).to_bytes(4, "big")
    with open(path, "ab") as f:
        f.write(cms + MAGIC + header)


def sign_all_modules(key, crt):
    mods = glob.glob(os.path.join(ROOTFS, "usr/lib/modules/*/kernel/**/*.ko*"), recursive=True)
    print("[sb] signature de %d modules..." % len(mods), flush=True)
    n = 0
    for m in mods:
        try:
            sign_module(m, key, crt)
            n += 1
        except Exception as e:
            print("[sb] module non signé:", m, e, flush=True)
        if n % 500 == 0:
            print("[sb]  %d/%d" % (n, len(mods)), flush=True)
    print("[sb] modules signés: %d/%d" % (n, len(mods)), flush=True)


def main():
    skip_modules = "--skip-modules" in sys.argv
    ensure_tools()
    key, crt = ensure_key()
    if SBSIGN:
        sign_efi_and_kernels(key, crt)
    else:
        print("[sb] sbsign absent -> signature EFI/noyaux sautee", flush=True)
    if not skip_modules:
        sign_all_modules(key, crt)
    print("[sb] OK", flush=True)


if __name__ == "__main__":
    main()
