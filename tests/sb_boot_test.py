#!/usr/bin/env python3
"""Test Secure Boot REEL en VM : QEMU + OVMF (firmware secboot, Secure Boot ACTIF)
avec la cle publique Pastèque enrôlée dans la variable db via virt-fw-vars.

Chaine testee de bout en bout (vraie verification cryptographique par le firmware,
le shim, et le noyau en lockdown) :
    OVMF(SB on, db += Pasteque.der) -> shimx64.efi (signe MS, dans db)
      -> grubx64.efi (signe cle Pastèque, verifie vs db/MOK)
      -> vmlinuz (EFI stub signe) -> initramfs -> modules .ko signes (verifies
         par le noyau en lockdown : un module non signe est REJETE)

Controle negatif : meme boot avec un varstore SANS notre cle -> le shim doit
BLOQUER (pas de prompt login) => prouve que le test positif n'est pas vide.

Sortie : exit 0 si positif OK ET negatif bloque ; exit 2 sinon ; exit 3 si
outils absents (OVMF secboot / virt-fw-vars / qemu) — appele alors SKIP explicite.

Usage : python3 tests/sb_boot_test.py <iso> <Pasteque.der> [--timeout 900]
"""
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from live_shell import Serial, wait_sock  # helpers serial/qemu existants

TROOT = os.path.join(REPO, "tools", "root")


def tool_env():
    env = dict(os.environ)
    lib = os.path.join(TROOT, "usr/lib/x86_64-linux-gnu") + ":" + os.path.join(TROOT, "lib/x86_64-linux-gnu")
    env["LD_LIBRARY_PATH"] = lib + ":" + env.get("LD_LIBRARY_PATH", "")
    env["PATH"] = os.path.join(TROOT, "usr/bin") + ":" + env.get("PATH", "")
    return env


def find_qemu():
    for c in (os.path.join(TROOT, "usr/bin/qemu-system-x86_64"), shutil.which("qemu-system-x86_64")):
        if c and os.path.exists(c):
            return c
    return None


def find_ovmf():
    """Retourne (code_secboot, vars) — OVMF avec Secure Boot compilé."""
    cands_code = [
        "/usr/share/OVMF/OVMF_CODE_4M.secboot.fd",
        "/usr/share/ovmf/OVMF_CODE_4M.secboot.fd",
        os.path.join(TROOT, "usr/share/OVMF/OVMF_CODE_4M.secboot.fd"),
        os.path.join(TROOT, "usr/share/ovmf/OVMF_CODE_4M.secboot.fd"),
    ]
    cands_vars = [c.replace("OVMF_CODE_4M.secboot.fd", "OVMF_VARS_4M.fd") for c in cands_code] + [
        "/usr/share/OVMF/OVMF_VARS_4M.fd",
        "/usr/share/ovmf/OVMF_VARS_4M.fd",
    ]
    code = next((c for c in cands_code if os.path.exists(c)), None)
    vars_ = next((v for v in cands_vars if os.path.exists(v)), None)
    return code, vars_


def build_vars_with_key(vars_in, der, out_path):
    """Enrôle le certificat DER dans la variable db du varstore OVMF (virt-fw-vars)."""
    fw = shutil.which("virt-fw-vars")
    if not fw:
        return None
    shutil.copy2(vars_in, out_path)
    # syntaxe moderne (python3-virt-firmware) : --inplace ; l'ancien -i/-o --output en repli
    for argv in ([fw, "--inplace", out_path, "--add-db", der],
                 [fw, "--input", out_path, "--output", out_path, "--add-db", der]):
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode == 0:
            return out_path
        print("[sb] virt-fw-vars %s a echoue: %s" % (argv[1], r.stderr[-200:]), flush=True)
    return None


def boot_once(qemu, code_fd, vars_fd, iso, sock, timeout, extra_append=""):
    """Boot via OVMF (pflash) + cdrom. Retourne le log serial complet."""
    if os.path.exists(sock):
        os.remove(sock)
    append = "archisolabel=PASTEQUE archisobasedir=arch console=ttyS0,115200" + extra_append
    proc = subprocess.Popen([
        qemu, "-machine", "q35", "-m", "2048", "-smp", "2",
        "-drive", "if=pflash,format=raw,readonly=on,file=" + code_fd,
        "-drive", "if=pflash,format=raw,file=" + vars_fd,
        "-cdrom", iso, "-boot", "d",
        "-display", "none", "-vga", "none",
        "-serial", "unix:%s,server,nowait" % sock,
        "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0",
    ], env=tool_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_sock(sock, proc, timeout=60):
            return None, proc, "pas de socket serial"
        ser = Serial(sock)
        end = time.time() + timeout
        while time.time() < end:
            if proc.poll() is not None:
                break
            time.sleep(2)
            ser.drain(1.5)
            # on scanne l'historique COMPLET (ser.log), pas seulement le dernier
            # morceau, pour ne pas rater un marqueur coupe entre deux lectures
            low = ser.log.decode("utf-8", "replace").lower()
            if "login:" in low or "reached target" in low or "multi-user" in low:
                ser.drain(3)
                return ser.log.decode("utf-8", "replace"), proc, "LOGIN_OK"
            if "security violation" in low or "verification failed" in low or "not signed" in low:
                ser.drain(3)
                return ser.log.decode("utf-8", "replace"), proc, "BLOCKED"
        ser.drain(2)
        return ser.log.decode("utf-8", "replace"), proc, "TIMEOUT"
    finally:
        try:
            proc.kill()
        except Exception:
            pass


def main():
    args = sys.argv[1:]
    iso = args[0] if args else None
    der = args[1] if len(args) > 1 else None
    timeout = 900
    if "--timeout" in args:
        timeout = int(args[args.index("--timeout") + 1])
    if not iso or not os.path.exists(iso):
        print("[sb] usage: sb_boot_test.py <iso> <Pasteque.der> [--timeout N]", flush=True)
        sys.exit(2)
    if not der or not os.path.exists(der):
        print("[sb] ERREUR: cle MOK %s introuvable (build secureboot incomplet ?)" % der, flush=True)
        sys.exit(2)
    qemu = find_qemu()
    code, vars_ = find_ovmf()
    fw = shutil.which("virt-fw-vars")
    if not (qemu and code and vars_ and fw):
        print("[sb] SKIP explicite: outils absents (qemu=%s ovmf_secboot=%s vars=%s virt-fw-vars=%s)"
              % (bool(qemu), bool(code), bool(vars_), bool(fw)), flush=True)
        print("[sb] -> test Secure Boot NON EXECUTE dans cet environnement (sera execute en CI avec ovmf+libvirt-clients)", flush=True)
        sys.exit(3)

    work = os.path.join(HERE, "artifacts", "sb-test")
    os.makedirs(work, exist_ok=True)
    vars_ok = os.path.join(work, "vars-sb-on.fd")
    vars_ko = os.path.join(work, "vars-sb-off.fd")
    shutil.copy2(vars_, vars_ko)  # controle negatif : varstore d'origine (cles MS seules)
    if not build_vars_with_key(vars_, der, vars_ok):
        print("[sb] ERREUR: impossible d'enrôler la cle dans db", flush=True)
        sys.exit(2)
    print("[sb] varstore avec cle Pastèque en db: OK", flush=True)

    # --- test POSITIF : SB on + cle enrôlée -> boot complet attendu ---
    log, proc, state = boot_once(qemu, code, vars_ok, iso, os.path.join(work, "pos.sock"), timeout)
    open(os.path.join(work, "serial-sb-on.log"), "w").write(log or "")
    sb_enabled = bool(log) and ("secure boot enabled" in log.lower()
                                or "locked down from efi secure boot" in log.lower())
    mod_fail = bool(log) and ("module verification failed" in log.lower())
    login_ok = state == "LOGIN_OK"
    print("[sb] POSITIF: etat=%s login=%s secureboot_enabled=%s module_verification_failed=%s"
          % (state, login_ok, sb_enabled, mod_fail), flush=True)
    pos_ok = login_ok and sb_enabled and not mod_fail

    # --- controle NEGATIF : SB on, cle ABSENTE -> boot bloque par le shim ---
    log2, proc2, state2 = boot_once(qemu, code, vars_ko, iso, os.path.join(work, "neg.sock"), min(timeout, 300))
    open(os.path.join(work, "serial-sb-off.log"), "w").write(log2 or "")
    blocked = state2 in ("BLOCKED", "TIMEOUT") and "login:" not in (log2 or "").lower()
    print("[sb] NEGATIF (sans la cle): etat=%s bloque=%s" % (state2, blocked), flush=True)

    print("[sb] RESULT: SB_POSITIVE_%s SB_NEGATIVE_%s"
          % ("OK" if pos_ok else "FAIL", "OK" if blocked else "FAIL"), flush=True)
    sys.exit(0 if (pos_ok and blocked) else 2)


if __name__ == "__main__":
    main()
