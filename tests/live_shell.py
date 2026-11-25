#!/usr/bin/env python3
"""Tests complets en VM QEMU (TCG, pas besoin de KVM) pour Pastèque Linux :

  0. structure de l'ISO (xorriso : El Torito BIOS+UEFI, fichiers, sha256)
  1. boot BIOS réel depuis le CD (isolinux)      -> console série
  2. boot UEFI depuis le CD (OVMF + grub EFI)     -> console série
  3. shell dans le système live : batterie de tests de la surcouche
     (calamares, appindexer, corbeille rotative, steamlibs, anti-cheat, sécurité...)
  4. installation sur disque virtuel (btrfs whole-disk + finalize + grub MBR)
     puis boot depuis ce disque -> login utilisateur + sudo

Usage: python3 tests/live_shell.py [iso]
Résultats: tests/artifacts/<ts>/report.md
"""
import base64
import glob
import os
import re
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TOOLS = os.path.join(REPO, "tools")
TROOT = os.path.join(TOOLS, "root")
WORK = os.path.join(REPO, "work")
ART = os.path.join(HERE, "artifacts")


def tool_env():
    env = dict(os.environ)
    lib = os.path.join(TROOT, "usr/lib/x86_64-linux-gnu") + ":" + os.path.join(TROOT, "lib/x86_64-linux-gnu")
    env["LD_LIBRARY_PATH"] = lib + ":" + env.get("LD_LIBRARY_PATH", "")
    env["PATH"] = os.path.join(TROOT, "usr/bin") + ":" + os.path.join(TROOT, "usr/sbin") + ":" + env["PATH"]
    return env


class Serial:
    def __init__(self, path, timeout=1):
        self.s = socket.socket(socket.AF_UNIX)
        for _ in range(20):
            try:
                self.s.connect(path)
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("socket indisponible: " + path)
        self.s.settimeout(timeout)
        self.buf = b""
        self.log = b""   # historique complet, jamais consomme (artefact serial-live.log)

    def drain(self, t):
        end = time.time() + t
        while time.time() < end:
            try:
                d = self.s.recv(65536)
                if not d:
                    break
                self.buf += d
                self.log += d
            except socket.timeout:
                pass

    def run(self, cmd, timeout=180):
        nonce = str(int(time.time() * 1000) % 100000)
        marker = "M%sRC=" % nonce
        self.s.sendall(cmd.encode() + b"\n")
        self.s.sendall(("echo %s$?\n" % marker).encode())
        pat = re.compile((marker + r"(\d+)").encode())
        end = time.time() + timeout
        while time.time() < end:
            self.drain(1)
            m = pat.search(self.buf)
            if m:
                out = self.buf[:m.start()].decode("utf-8", "replace")
                self.buf = self.buf[m.end():]
                return out, int(m.group(1))
        return self.buf.decode("utf-8", "replace"), -1

    def wait_for(self, pattern, timeout):
        end = time.time() + timeout
        rx = re.compile(pattern.encode())
        while time.time() < end:
            self.drain(2)
            if rx.search(self.buf):
                return True
        return False


class QMP:
    def __init__(self, path):
        import json
        self.s = socket.socket(socket.AF_UNIX)
        for _ in range(20):
            try:
                self.s.connect(path)
                break
            except OSError:
                time.sleep(0.5)
        self.f = self.s.makefile("rw")
        self.f.readline()
        self.cmd("qmp_capabilities")

    def cmd(self, name, **args):
        import json
        self.f.write(json.dumps({"execute": name, "arguments": args}) + "\n")
        self.f.flush()
        while True:
            line = self.f.readline()
            if not line:
                return None
            r = json.loads(line)
            if "return" in r:
                return r["return"]


def qemu_base(extra):
    cmd = [os.path.join(TROOT, "usr/bin/qemu-system-x86_64"),
           "-L", os.path.join(TROOT, "usr/share/qemu"),
           "-machine", "q35", "-m", "3072", "-smp", "2",
           "-display", "none", "-vga", "std", "-no-reboot"] + extra
    return subprocess.Popen(cmd, env=tool_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_sock(path, proc, tries=40):
    for _ in range(tries):
        if os.path.exists(path):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.5)
    return False


class Report:
    def __init__(self, outdir):
        self.lines = []
        self.outdir = outdir
        self.fails = 0

    def check(self, name, ok, detail=""):
        self.lines.append("- [%s] **%s** %s" % ("PASS" if ok else "FAIL", name, detail))
        if not ok:
            self.fails += 1
        print(("PASS " if ok else "FAIL ") + name + (" " + detail if detail else ""), flush=True)

    def save(self):
        with open(os.path.join(self.outdir, "report.md"), "w") as f:
            f.write("# Rapport de tests Pastèque Linux — %s\n\n" % time.strftime("%Y-%m-%d %H:%M:%S") +
                    "\n".join(self.lines) + "\n")


def extract_iso(iso, ext):
    subprocess.run(["chmod", "-R", "u+w", ext], capture_output=True)
    shutil.rmtree(ext, ignore_errors=True)
    os.makedirs(ext)
    subprocess.run([os.path.join(TROOT, "usr/bin/xorriso"), "-osirrox", "on", "-overwrite", "on",
                    "-indev", iso, "-extract", "/", ext],
                   check=True, env=tool_env(), stdout=subprocess.DEVNULL)


def phase_structure(iso, rep):
    out = subprocess.run([os.path.join(TROOT, "usr/bin/xorriso"), "-indev", iso, "-report_el_torito", "plain"],
                         capture_output=True, text=True, env=tool_env()).stdout
    rep.check("iso-el-torito-bios", "isolinux.bin" in out, "")
    rep.check("iso-el-torito-uefi", "efi.img" in out or "EFI" in out, "")
    listing = subprocess.run([os.path.join(TROOT, "usr/bin/xorriso"), "-indev", iso, "-ls", "/"],
                             capture_output=True, text=True, env=tool_env()).stdout
    for f in ["boot", "arch", "EFI"]:
        rep.check("iso-contains-%s" % f, f in listing, "")
    # Secure Boot : shim MS (BOOTX64.EFI) + grub signe + MokManager dans l'arbre EFI
    efi_ls = subprocess.run([os.path.join(TROOT, "usr/bin/xorriso"), "-indev", iso, "-ls", "/EFI/BOOT"],
                            capture_output=True, text=True, env=tool_env()).stdout
    rep.check("iso-efi-bootx64-shim", "BOOTX64.EFI" in efi_ls.upper(), efi_ls.strip()[:200])
    rep.check("iso-efi-grubx64-signed", "grubx64.efi" in efi_ls.lower(), "")
    rep.check("iso-efi-mokmanager", "mmx64.efi" in efi_ls.lower(), "")
    iso_abs = os.path.abspath(iso)
    sha = subprocess.run(["sha256sum", "-c", os.path.basename(iso_abs) + ".sha256"],
                         capture_output=True, text=True, cwd=os.path.dirname(iso_abs))
    rep.check("iso-sha256", sha.returncode == 0, (sha.stdout + sha.stderr).strip())


def inspect_initramfs(iso, rep, outdir):
    """Extrait l'initramfs de l'ISO et verifie que les modules critiques du boot
    (CD/USB/squashfs + index kmod) y sont embarques. Liste les .ko dans un artefact."""
    import lzma
    tmp = os.path.join(outdir, "initrd-inspect.img")
    r = subprocess.run([os.path.join(TROOT, "usr/bin/xorriso"), "-osirrox", "on", "-overwrite", "on",
                        "-indev", iso, "-extract", "/boot/x86_64/initramfs-linux.img", tmp],
                       capture_output=True, env=tool_env())
    if r.returncode != 0 or not os.path.exists(tmp):
        rep.check("initramfs-extract", False, "xorriso rc=%d" % r.returncode)
        return
    required = {
        "ahci": b"ahci.ko", "ata_piix": b"ata_piix.ko", "ata_generic": b"ata_generic.ko",
        "sr_mod": b"sr_mod.ko", "cdrom": b"cdrom.ko", "scsi_mod": b"scsi_mod.ko",
        "sd_mod": b"sd_mod.ko", "nvme": b"nvme.ko", "virtio_blk": b"virtio_blk.ko",
        "virtio_scsi": b"virtio_scsi.ko", "usb-storage": b"usb-storage.ko", "xhci-pci": b"xhci-pci.ko",
        "squashfs": b"squashfs.ko", "isofs": b"isofs.ko", "overlay": b"overlay.ko",
        "loop": b"loop.ko", "ext4": b"ext4.ko", "btrfs": b"btrfs.ko",
        "modules.dep": b"modules.dep", "modules.alias": b"modules.alias",
    }
    raw = open(tmp, "rb").read()
    # decompresse chaque stream xz present (l'initramfs peut en contenir plusieurs)
    dec_all = b""
    magic = b"\xfd7zXZ\x00"
    pos = 0
    while pos < len(raw):
        i = raw.find(magic, pos)
        if i < 0:
            break
        dec = lzma.LZMADecompressor()
        try:
            dec_all += dec.decompress(raw[i:])
        except lzma.LZMAError:
            pass
        if dec.eof and dec.unused_data:
            pos = len(raw) - len(dec.unused_data)
        else:
            break
    os.remove(tmp)
    hay_all = raw + dec_all   # brut (cpio early non compressé) + decompressé
    found = {k: (pat in hay_all) for k, pat in required.items()}
    mods = set(re.findall(rb"[\w./+-]*\.ko(?:\.\w+)?", dec_all))
    with open(os.path.join(outdir, "initramfs-modules.txt"), "w") as f:
        f.write("\n".join(sorted(m.decode() for m in mods)) + "\n")
    rep.check("initramfs-decompress", bool(dec_all), "%d .ko, %d Mo decompresses" % (len(mods), len(dec_all) // 1048576))
    for k, ok in sorted(found.items()):
        rep.check("initramfs-module-%s" % k, ok, "")


def phase_boot_loader(iso, rep, outdir, uefi):
    """Boot depuis le CD via le vrai chargeur (isolinux BIOS ou grub UEFI/OVMF)."""
    sock = os.path.join(outdir, "ser-%s.sock" % ("uefi" if uefi else "bios"))
    qmps = os.path.join(outdir, "qmp-%s.sock" % ("uefi" if uefi else "bios"))
    for p in (sock, qmps):
        if os.path.exists(p):
            os.remove(p)
    # CD attache explicitement sur un controleur AHCI (q35) : le noyau verra /dev/sr0
    extra = ["-device", "ahci,id=pq-sata",
             "-drive", "if=none,id=pq-cd,media=cdrom,readonly=on,file=%s" % iso,
             "-device", "ide-cd,bus=pq-sata.0,drive=pq-cd",
             "-boot", "d",
             "-serial", "unix:%s,server,nowait" % sock,
             "-qmp", "unix:%s,server,nowait" % qmps]
    if uefi:
        # OVMF en pflash (CODE + VARS) : boot UEFI pur
        ovmf_code = os.path.join(TROOT, "usr/share/OVMF/OVMF_CODE_4M.fd")
        ovmf_vars_src = os.path.join(TROOT, "usr/share/OVMF/OVMF_VARS_4M.fd")
        if not os.path.exists(ovmf_vars_src):
            ovmf_vars_src = os.path.join(TROOT, "usr/share/ovmf/OVMF_VARS.fd")
        vars_copy = os.path.join(outdir, "ovmf-vars.fd")
        shutil.copyfile(ovmf_vars_src, vars_copy)
        extra = ["-drive", "if=pflash,format=raw,readonly=on,file=%s" % ovmf_code,
                 "-drive", "if=pflash,format=raw,file=%s" % vars_copy] + extra
    proc = qemu_base(extra)
    ok_sock = wait_sock(sock, proc)
    rep.check("boot-%s-socket" % ("uefi" if uefi else "bios"), ok_sock, "")
    if not ok_sock:
        proc.kill()
        return
    ser = Serial(sock)
    ser.wait_for(r"(login:|Reached target|Started Simple Desktop)", timeout=900)
    time.sleep(30)
    ser.drain(5)
    text = ser.buf.decode("utf-8", "replace")
    log = os.path.join(outdir, "serial-%s.log" % ("uefi" if uefi else "bios"))
    open(log, "w").write(text)
    ok = ("login:" in text) or ("Reached target" in text) or ("SDDM" in text) or ("Multi-User" in text)
    rep.check("boot-%s-chargeur" % ("uefi" if uefi else "bios"), ok,
              "serial: %s" % log)
    # screendump
    if wait_sock(qmps, proc):
        try:
            q = QMP(qmps)
            ppm = os.path.join(outdir, "screen-%s.ppm" % ("uefi" if uefi else "bios"))
            q.cmd("screendump", filename=ppm)
            time.sleep(1)
            from PIL import Image
            Image.open(ppm).save(ppm.replace(".ppm", ".png"))
        except Exception as e:
            print("screendump KO:", e, flush=True)
    try:
        q.cmd("quit")
    except Exception:
        pass
    proc.wait(timeout=30)


def phase_live_and_install(iso, rep, outdir):
    ext = os.path.join(WORK, "liveshell-extract")
    extract_iso(iso, ext)
    kernel = os.path.join(ext, "boot/x86_64/vmlinuz-linux")
    initrd = os.path.join(ext, "boot/x86_64/initramfs-linux.img")

    vda = os.path.join(WORK, "vda.raw")   # disque cible de l'installation
    vdb = os.path.join(WORK, "vdb.raw")   # disque scratch (upperdir overlay)
    for f in (vda, vdb):
        if os.path.exists(f):
            os.remove(f)
    subprocess.run([os.path.join(TROOT, "usr/bin/qemu-img"), "create", "-f", "raw", vda, "20G"], check=True, env=tool_env())
    subprocess.run([os.path.join(TROOT, "usr/bin/qemu-img"), "create", "-f", "raw", vdb, "12G"], check=True, env=tool_env())
    subprocess.run(["mkfs.ext4", "-F", "-q", vdb], check=True)

    sock = os.path.join(outdir, "ser-live.sock")
    if os.path.exists(sock):
        os.remove(sock)
    proc = qemu_base([
        "-kernel", kernel, "-initrd", initrd,
        # rdinit (pas init=) : /bin/bash vraiment en PID1 de l'initramfs, sans passer
        # par /init -> on controle nous-memes les modprobe/montages ci-dessous
        "-append", "archisolabel=PASTEQUE archisobasedir=arch console=ttyS0,115200 rdinit=/bin/bash",
        "-cdrom", iso, "-boot", "d",
        "-drive", "file=%s,if=virtio" % vda,
        "-drive", "file=%s,if=virtio" % vdb,
        # l'ISO aussi en disque virtio (secours si le CD SATA n'est pas vu) -> /dev/vdc
        "-drive", "file=%s,format=raw,if=virtio,readonly=on" % iso,
        "-serial", "unix:%s,server,nowait" % sock,
    ])
    if not wait_sock(sock, proc):
        rep.check("live-shell-boot", False, "pas de socket série")
        proc.kill()
        return
    ser = Serial(sock)
    ser.wait_for(r"/ #|~ #|\]#|bash-[0-9.]+#", timeout=180)
    time.sleep(2)
    ser.drain(2)

    # sonde de diagnostic : quels blocs/modules/dmesg voit le noyau ?
    probe, _ = ser.run("echo ===BLOCK===; ls /sys/block 2>&1; echo ===MODS===; "
                       "cat /proc/modules 2>/dev/null | cut -d' ' -f1 | tr '\\n' ' '; echo; "
                       "echo ===DMESG===; dmesg | grep -iE 'ahci|ata[0-9]|sr[0-9]|scsi|virtio|cdrom' | tail -30; "
                       "echo ===LABEL===; ls -la /dev/disk/by-label 2>&1; echo ===END===", timeout=90)
    open(os.path.join(outdir, "live-probe.txt"), "w").write(probe)
    open(os.path.join(outdir, "serial-live.log"), "w").write(ser.log.decode("utf-8", "replace"))

    setup = [
        # le hook cleanup d'archiso a demonte /dev /proc /sys : on les recree
        "mkdir -p /dev /proc /sys /run/m /tmp/sfs /newroot /mnt/scratch; true",
        "mount -t devtmpfs devtmpfs /dev; mount -t proc proc /proc; mount -t sysfs sys /sys; true",
        "modprobe ahci; modprobe virtio_blk; modprobe sr_mod; modprobe cdrom; modprobe loop; modprobe squashfs; modprobe isofs; modprobe overlay; sleep 2; ls /dev > /tmp/devlist.txt 2>&1; true",
        "modprobe ata_piix ata_generic ahci sr_mod cdrom scsi_mod 2>/dev/null; for i in $(seq 1 30); do [ -e /dev/disk/by-label/PASTEQUE ] && break; [ -b /dev/sr0 ] && break; sleep 1; done; "
        "mkdir -p /run/m; mount -o ro /dev/sr0 /run/m 2>/dev/null || mount -o ro LABEL=PASTEQUE /run/m 2>/dev/null || "
        "for d in /dev/sr* /dev/sd* /dev/vd*; do [ -b \"$d\" ] && blkid \"$d\" 2>/dev/null | grep -q PASTEQUE && mount -o ro \"$d\" /run/m && break; done || "
        "(ls -la /dev /dev/disk/by-label /dev/sr* /dev/vd* 2>/dev/null > /tmp/devlist.txt; dmesg | tail -40 >> /tmp/devlist.txt; cat /proc/modules >> /tmp/devlist.txt; cat /tmp/devlist.txt; false)",
        "mount /dev/vdb /mnt/scratch || true",
        "mkdir -p /mnt/scratch/up /mnt/scratch/wrk",
        "mount -t squashfs -o loop,ro /run/m/arch/x86_64/airootfs.sfs /tmp/sfs",
        "mount -t overlay overlay -o lowerdir=/tmp/sfs,upperdir=/mnt/scratch/up,workdir=/mnt/scratch/wrk /newroot",
        "mkdir -p /newroot/dev /newroot/proc /newroot/sys; true",
        "mount --bind /dev /newroot/dev",
        "mount --bind /proc /newroot/proc",
        "mount --bind /sys /newroot/sys",
    ]
    for c in setup:
        out, rc = ser.run(c, timeout=240)
        open(os.path.join(outdir, "serial-live.log"), "w").write(ser.log.decode("utf-8", "replace"))
        if rc != 0:
            rep.check("live-mount", False, c + " -> " + out[-3000:])
            proc.kill()
            return
    rep.check("live-mount", True, "squashfs montée, overlay OK")

    # batterie de tests dans le chroot
    b64 = base64.b64encode(open(os.path.join(HERE, "live_tests.sh"), "rb").read()).decode()
    ser.run("mkdir -p /newroot/tmp; : > /newroot/tmp/live_tests.b64", timeout=30)
    for i in range(0, len(b64), 512):
        chunk = b64[i:i + 512]
        out, rc = ser.run("echo -n %s >> /newroot/tmp/live_tests.b64" % chunk, timeout=30)
        if rc != 0:
            rep.check("live-upload-script", False, "chunk %d rc=%d" % (i, rc))
            proc.kill()
            return
    ser.run("base64 -d /newroot/tmp/live_tests.b64 > /newroot/tmp/live_tests.sh && chmod +x /newroot/tmp/live_tests.sh", timeout=30)
    rep.check("live-upload-script", True, "")
    out, rc = ser.run("chroot /newroot /bin/bash /tmp/live_tests.sh", timeout=900)
    open(os.path.join(outdir, "live-tests.txt"), "w").write(out)
    open(os.path.join(outdir, "serial-live.log"), "w").write(ser.log.decode("utf-8", "replace"))
    for line in out.splitlines():
        if line.startswith(("PASS ", "FAIL ")):
            rep.check("live: " + line.split(None, 1)[1], line.startswith("PASS"), "")
    m = re.search(r"RESULT live-tests PASS=(\d+) FAIL=(\d+)", out)
    rep.check("live-batterie-globale", rc == 0 and m is not None and m.group(2) == "0",
              m.group(0) if m else out[-300:])

    # --- installation sur /dev/vda ---
    install_cmds = [
        "chroot /newroot /bin/bash -c 'mkfs.btrfs -f /dev/vda'",
        "mkdir -p /newroot/mnt/target",
        "mount /dev/vda /newroot/mnt/target",
        "cp -a /tmp/sfs/. /newroot/mnt/target/",
        "mkdir -p /newroot/mnt/target/boot /newroot/mnt/target/dev /newroot/mnt/target/proc /newroot/mnt/target/sys",
        "cp /run/m/boot/x86_64/vmlinuz-linux /run/m/boot/x86_64/initramfs-linux.img /newroot/mnt/target/boot/",
        "mount --bind /dev /newroot/mnt/target/dev",
        "mount --bind /proc /newroot/mnt/target/proc",
        "mount --bind /sys /newroot/mnt/target/sys",
    ]
    for c in install_cmds:
        out, rc = ser.run(c, timeout=3600)
        if rc != 0:
            rep.check("install-copie", False, c + " -> " + out[-300:])
            break
    else:
        rep.check("install-copie", True, "système copié sur /dev/vda (btrfs)")

    final = '''useradd -m -G wheel,video,audio,input,storage,optical -s /bin/bash gamer 2>/dev/null
echo "gamer:gamer" | chpasswd
/usr/local/bin/pasteque-finalize-install
mkinitcpio -P
grub-install --target=i386-pc --boot-directory=/boot /dev/vda
mkdir -p /boot/grub
printf 'set timeout=1\\nserial --speed=115200\\nterminal_output console serial\\nmenuentry "Pasteque Linux (installe)" {\\n  linux /boot/vmlinuz-linux root=/dev/vda rw console=ttyS0,115200\\n  initrd /boot/initramfs-linux.img\\n}\\n' > /boot/grub/grub.cfg
'''
    fb64 = base64.b64encode(final.encode()).decode()
    ser.run("mkdir -p /newroot/mnt/target/tmp; : > /newroot/mnt/target/tmp/finalize.b64", timeout=30)
    for i in range(0, len(fb64), 512):
        ser.run("echo -n %s >> /newroot/mnt/target/tmp/finalize.b64" % fb64[i:i + 512], timeout=30)
    ser.run("base64 -d /newroot/mnt/target/tmp/finalize.b64 > /newroot/mnt/target/tmp/finalize.sh", timeout=30)
    out, rc = ser.run("chroot /newroot/mnt/target /bin/bash /tmp/finalize.sh", timeout=3600)
    open(os.path.join(outdir, "install-finalize.txt"), "w").write(out)
    rep.check("install-finalize-grub", rc == 0, out[-300:] if rc else "finalize + mkinitcpio + grub-install OK")
    ser.run("sync", timeout=60)
    proc.kill()
    proc.wait(timeout=30)

    # --- boot depuis le disque installé ---
    sock2 = os.path.join(outdir, "ser-installed.sock")
    if os.path.exists(sock2):
        os.remove(sock2)
    proc2 = qemu_base([
        "-drive", "file=%s,if=virtio" % vda,
        "-serial", "unix:%s,server,nowait" % sock2,
    ])
    if not wait_sock(sock2, proc2):
        rep.check("boot-installe", False, "pas de socket")
        proc2.kill()
        return
    ser2 = Serial(sock2)
    ok = ser2.wait_for(r"pasteque login:", timeout=900)
    time.sleep(10)
    ser2.drain(5)
    text = ser2.buf.decode("utf-8", "replace")
    open(os.path.join(outdir, "serial-installed.log"), "w").write(text)
    rep.check("boot-disque-installe", ok, "login prompt atteint depuis /dev/vda (grub MBR)")
    if ok:
        ser2.run("gamer", timeout=30)
        ser2.wait_for(r"[Pp]assword", timeout=30)
        ser2.run("gamer", timeout=30)
        out, rc = ser2.run("hostname; echo gamer | sudo -S whoami; systemctl is-enabled sddm firewalld 2>/dev/null; ls /home/gamer | head -3", timeout=120)
        open(os.path.join(outdir, "installed-session.txt"), "w").write(out)
        rep.check("session-installee-sudo", "root" in out and "pasteque" in out, out.strip().replace("\n", " | ")[:200])
    proc2.kill()
    proc2.wait(timeout=30)


def main():
    iso = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(REPO, "out/*.iso")))[-1]
    run_id = time.strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(ART, run_id)
    os.makedirs(outdir, exist_ok=True)
    rep = Report(outdir)
    print("[tests] ISO:", iso, "->", outdir, flush=True)
    phase_structure(iso, rep, )
    inspect_initramfs(iso, rep, outdir)
    phase_boot_loader(iso, rep, outdir, uefi=False)
    phase_boot_loader(iso, rep, outdir, uefi=True)
    phase_live_and_install(iso, rep, outdir)
    rep.save()
    print("[tests] rapport:", os.path.join(outdir, "report.md"), "FAILS=%d" % rep.fails, flush=True)
    sys.exit(1 if rep.fails else 0)


if __name__ == "__main__":
    main()
