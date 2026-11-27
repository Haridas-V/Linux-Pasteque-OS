#!/usr/bin/env python3
"""Test Secure Boot REEL en VM : QEMU + OVMF (firmware secboot, Secure Boot ACTIF)
avec la cle publique Pastèque enrôlée dans la variable db via virt-fw-vars.

Chaine testee de bout en bout (vraie verification cryptographique par le firmware,
le shim, et le noyau en lockdown) :
    OVMF(SB on, db += Pasteque.der) -> shimx64.efi (signe MS, dans db)
      -> grubx64.efi (signe cle Pastèque, verifie vs db/MOK)
      -> vmlinuz (EFI stub signe) -> initramfs -> modules .ko signes (verifies
         par le noyau en lockdown : un module non signe est REJETE)

Controle negatif : meme boot avec un varstore SANS notre cle (mais Secure Boot ON,
cles Microsoft seules) -> le shim doit BLOQUER (pas de prompt login) => prouve que
le test positif n'est pas vide. Les deux varstores sont construits avec
`virt-fw-vars --secure-boot` explicite et RE-LUS (`--print --verbose`) pour exiger
SecureBoot=ON avant de booter : un varstore sans SB actif invaliderait le test.

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


# GUID de la variable db (EFI_IMAGE_SECURITY_DATABASE) — owner requis par virt-fw-vars
DB_GUID = "d719b2cb-3d3a-4596-a3bc-dad00e67656f"


def find_ovmf():
    """Retourne (code_secboot, vars_ms, vars_plain).
    - code : firmware OVMF compile AVEC Secure Boot (OVMF_CODE_4M.secboot.fd)
    - vars_ms : template varstore AVEC cles Microsoft + SB pre-active (OVMF_VARS_4M.ms.fd,
      paquet ovmf Debian/Ubuntu) — PREFERE, sinon le shim signe MS ne verifie pas.
    - vars_plain : varstore vierge (setup mode) — repli : on activera SB nous-memes
      (--secure-boot) et on enrolera les cles MS (--enroll-redhat ajoute les cles MS a db)."""
    code_cands = [
        "/usr/share/OVMF/OVMF_CODE_4M.secboot.fd",
        "/usr/share/ovmf/OVMF_CODE_4M.secboot.fd",
        os.path.join(TROOT, "usr/share/OVMF/OVMF_CODE_4M.secboot.fd"),
        os.path.join(TROOT, "usr/share/ovmf/OVMF_CODE_4M.secboot.fd"),
    ]
    ms_cands = [
        "/usr/share/OVMF/OVMF_VARS_4M.ms.fd",
        "/usr/share/ovmf/OVMF_VARS_4M.ms.fd",
        "/usr/share/OVMF/OVMF_VARS.secboot.fd",
        "/usr/share/ovmf/OVMF_VARS.secboot.fd",
        os.path.join(TROOT, "usr/share/OVMF/OVMF_VARS_4M.ms.fd"),
        os.path.join(TROOT, "usr/share/ovmf/OVMF_VARS_4M.ms.fd"),
    ]
    plain_cands = [
        "/usr/share/OVMF/OVMF_VARS_4M.fd",
        "/usr/share/ovmf/OVMF_VARS_4M.fd",
        "/usr/share/OVMF/OVMF_VARS.fd",
        "/usr/share/ovmf/OVMF_VARS.fd",
        os.path.join(TROOT, "usr/share/OVMF/OVMF_VARS_4M.fd"),
        os.path.join(TROOT, "usr/share/ovmf/OVMF_VARS_4M.fd"),
    ]
    code = next((c for c in code_cands if os.path.exists(c)), None)
    vars_ms = next((v for v in ms_cands if os.path.exists(v)), None)
    vars_plain = next((v for v in plain_cands if os.path.exists(v)), None)
    return code, vars_ms, vars_plain


def run_fw(fw, argv):
    r = subprocess.run([fw] + argv, capture_output=True, text=True)
    if r.returncode != 0:
        print("[sb] virt-fw-vars %s a echoue (rc=%d): %s" % (argv[0], r.returncode, (r.stderr or "")[-300:]), flush=True)
    return r


def build_vars(vars_base, out_path, der=None, enroll_ms=False):
    """Construit un varstore avec Secure Boot ACTIVÉ (--secure-boot, jamais suppose),
    optionnellement + notre cle dans db (--add-db GUID FILE, DER ou PEM accepte),
    et + les cles Microsoft dans db si le template de base est vierge."""
    fw = shutil.which("virt-fw-vars")
    if not fw:
        return None
    shutil.copy2(vars_base, out_path)
    argv = ["--inplace", out_path, "--secure-boot"]   # SB ON explicite, sinon test VIDE
    if enroll_ms:
        argv.append("--enroll-redhat")  # ajoute PK/KEK + cles MS (db) au varstore vierge
    if der:
        argv += ["--add-db", DB_GUID, der]
    if run_fw(fw, argv).returncode != 0:
        return None
    return out_path


def verify_sb_on(vars_path, expect_cn=None):
    """Auto-verification anti-test-vide : relit le varstore et exige SecureBoot ON
    (et la presence de notre certificat dans db si expect_cn fourni)."""
    fw = shutil.which("virt-fw-vars")
    r = subprocess.run([fw, "--input", vars_path, "--print", "--verbose"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("[sb] impossible de relire le varstore: %s" % (r.stderr or "")[-200:], flush=True)
        return False
    lines = r.stdout.splitlines()
    sb_on = False
    for i, line in enumerate(lines):
        low = line.lower()
        # format --print --verbose : "name=SecureBootEnable ..." suivi de "  bool: ON"
        if low.startswith("name=") and "secureboot" in low:
            val = lines[i + 1].lower() if i + 1 < len(lines) else ""
            if "bool: on" in val:
                sb_on = True
    if not sb_on:
        print("[sb] VARSTORE SANS SECURE BOOT ACTIF -> le test serait VIDE, on refuse", flush=True)
        return False
    if expect_cn and expect_cn.lower() not in r.stdout.lower():
        print("[sb] certificat %r absent de db dans le varstore" % expect_cn, flush=True)
        return False
    return True


def boot_once(qemu, code_fd, vars_fd, iso, sock, timeout, extra_append=""):
    """Boot via OVMF (pflash) + cdrom. Retourne le log serial complet."""
    if os.path.exists(sock):
        os.remove(sock)
    append = "archisolabel=PASTEQUE archisobasedir=arch console=ttyS0,115200" + extra_append
    # stderr qemu capture dans un fichier : indispensable pour diagnostiquer un
    # demarrage qui echoue apres creation du socket (ex: option machine invalide)
    qerr_path = sock + ".qemu.err"
    qerr = open(qerr_path, "w")
    # -L INDISPENSABLE : sinon qemu cherche ses roms dans /usr/share/qemu (absent
    # du conteneur CI) -> il cree le socket serial puis meurt (rc=1, romfile
    # "efi-virtio.rom"/"kvmvapic.bin" introuvable). Reproduit en local.
    qemu_data = next((d for d in (os.path.join(TROOT, "usr/share/qemu"),
                                  "/usr/share/qemu", "/usr/share/qemu-kvm")
                      if os.path.isdir(d)), None)
    cmd = [qemu] + (["-L", qemu_data] if qemu_data else []) + [
        "-machine", "q35,smm=on", "-m", "2048", "-smp", "2",
        # pflash "secure" requis par OVMF secboot (protection du varstore), OK en TCG
        "-global", "driver=cfi.pflash01,property=secure,value=on",
        "-drive", "if=pflash,format=raw,readonly=on,file=" + code_fd,
        "-drive", "if=pflash,format=raw,file=" + vars_fd,
        "-cdrom", iso, "-boot", "d",
        "-display", "none", "-vga", "none",
        "-serial", "unix:%s,server,nowait" % sock,
        "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0",
    ]
    proc = subprocess.Popen(cmd, env=tool_env(), stdout=qerr, stderr=qerr)
    try:
        if not wait_sock(sock, proc, timeout=60):
            tail = ""
            try:
                tail = open(qerr_path).read()[-500:]
            except OSError:
                pass
            return None, proc, "pas de socket serial (qemu rc=%s) stderr: %s" % (proc.poll(), tail)
        try:
            ser = Serial(sock)
        except RuntimeError as e:
            tail = ""
            try:
                tail = open(qerr_path).read()[-500:]
            except OSError:
                pass
            return None, proc, "%s (qemu rc=%s) stderr: %s" % (e, proc.poll(), tail)
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
    code, vars_ms, vars_plain = find_ovmf()
    fw = shutil.which("virt-fw-vars")
    base = vars_ms or vars_plain
    if not (qemu and code and base and fw):
        print("[sb] SKIP explicite: outils absents (qemu=%s ovmf_secboot=%s vars_ms=%s vars_plain=%s virt-fw-vars=%s)"
              % (bool(qemu), bool(code), bool(vars_ms), bool(vars_plain), bool(fw)), flush=True)
        print("[sb] -> test Secure Boot NON EXECUTE ici (en CI: paquets ovmf + python3-virt-firmware requis)", flush=True)
        sys.exit(3)

    work = os.path.join(HERE, "artifacts", "sb-test")
    os.makedirs(work, exist_ok=True)
    vars_ok = os.path.join(work, "vars-sb-on.fd")   # SB ON + cle Pastèque dans db (positif)
    vars_ko = os.path.join(work, "vars-sb-off.fd")  # SB ON, cles MS seules (controle negatif)
    enroll_ms = vars_ms is None  # template vierge -> enroler les cles MS nous-memes
    if not build_vars(base, vars_ko, der=None, enroll_ms=enroll_ms) or not verify_sb_on(vars_ko):
        print("[sb] ERREUR: varstore negatif (SB on, sans notre cle) non constructible ou non verifie", flush=True)
        sys.exit(2)
    if not build_vars(base, vars_ok, der=der, enroll_ms=enroll_ms) or not verify_sb_on(vars_ok, expect_cn="Pasteque Linux Secure Boot"):
        print("[sb] ERREUR: impossible d'enrôler la cle Pastèque dans db (varstore positif invalide)", flush=True)
        sys.exit(2)
    print("[sb] varstores OK: Secure Boot verifie ON dans les deux, cle Pastèque en db pour le positif", flush=True)

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
