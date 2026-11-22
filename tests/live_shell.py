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

    def drain(self, t):
        end = time.time() + t
        while time.time() < end:
            try:
                d = self.s.recv(65536)
                if not d:
                    break
                self.buf += d
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
    sha = subprocess.run(["sha256sum", "-c", iso + ".sha256"], capture_output=True, text=True, cwd=os.path.dirname(iso))
    rep.check("iso-sha256", sha.returncode == 0, sha.stdout.strip())


def phase_boot_loader(iso, rep, outdir, uefi):
    """Boot depuis le CD via le vrai chargeur (isolinux BIOS ou grub UEFI/OVMF)."""
    sock = os.path.join(outdir, "ser-%s.sock" % ("uefi" if uefi else "bios"))
    qmps = os.path.join(outdir, "qmp-%s.sock" % ("uefi" if uefi else "bios"))
    for p in (sock, qmps):
        if os.path.exists(p):
            os.remove(p)
    extra = ["-cdrom", iso, "-boot", "d",
             "-serial", "unix:%s,server,nowait" % sock,
             "-qmp", "unix:%s,server,nowait" % qmps]
    if uefi:
        extra = ["-bios", os.path.join(TROOT, "usr/share/OVMF/OVMF_CODE_4M.fd")] + extra
    proc = qemu_base(extra)
    ok_sock = wait_sock(sock, proc)
    rep.check("boot-%s-socket" % ("uefi" if uefi else "bios"), ok_sock, "")
    if not ok_sock:
        proc.kill()
        return
    ser = Serial(sock)
    ser.wait_for(r"(login:|Reached target|Started Simple Desktop)", timeout=600)
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
        "-append", "archisolabel=PASTEQUE archisobasedir=arch console=ttyS0,115200 init=/bin/bash",
        "-cdrom", iso, "-boot", "d",
        "-drive", "file=%s,if=virtio" % vda,
        "-drive", "file=%s,if=virtio" % vdb,
        "-serial", "unix:%s,server,nowait" % sock,
    ])
    if not wait_sock(sock, proc):
        rep.check("live-shell-boot", False, "pas de socket série")
        proc.kill()
        return
    ser = Serial(sock)
    ser.wait_for(r"/ #|~ #|\]#", timeout=180)
    time.sleep(2)
    ser.drain(2)

    setup = [
        "modprobe sr_mod; modprobe cdrom; modprobe loop; modprobe squashfs; modprobe isofs; modprobe overlay; modprobe virtio_blk",
        "mkdir -p /run/m /tmp/sfs /newroot /mnt/scratch",
        "mount /dev/sr0 /run/m",
        "mount /dev/vdb /mnt/scratch",
        "mkdir -p /mnt/scratch/up /mnt/scratch/wrk",
        "mount -t squashfs -o loop,ro /run/m/arch/x86_64/airootfs.sfs /tmp/sfs",
        "mount -t overlay overlay -o lowerdir=/tmp/sfs,upperdir=/mnt/scratch/up,workdir=/mnt/scratch/wrk /newroot",
        "mount --bind /dev /newroot/dev",
        "mount --bind /proc /newroot/proc",
        "mount --bind /sys /newroot/sys",
    ]
    for c in setup:
        out, rc = ser.run(c, timeout=240)
        if rc != 0:
            rep.check("live-mount", False, c + " -> " + out[-200:])
            proc.kill()
            return
    rep.check("live-mount", True, "squashfs montée, overlay OK")

    # batterie de tests dans le chroot
    b64 = base64.b64encode(open(os.path.join(HERE, "live_tests.sh"), "rb").read()).decode()
    ser.run("echo %s | base64 -d > /newroot/tmp/live_tests.sh" % b64, timeout=60)
    out, rc = ser.run("chroot /newroot /bin/bash /tmp/live_tests.sh", timeout=900)
    open(os.path.join(outdir, "live-tests.txt"), "w").write(out)
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
        out, rc = ser.run(c, timeout=900)
        if rc != 0:
            rep.check("install-copie", False, c + " -> " + out[-300:])
            break
    else:
        rep.check("install-copie", True, "système copié sur /dev/vda (btrfs)")

    final = r'''
useradd -m -G wheel,video,audio,input,storage,optical -s /bin/bash gamer 2>/dev/null
echo "gamer:gamer" | chpasswd
/usr/local/bin/pasteque-finalize-install
mkinitcpio -P
grub-install --target=i386-pc --boot-directory=/boot /dev/vda
mkdir -p /boot/grub
printf 'menuentry "Pasteque Linux (installe)" {\n  linux /boot/vmlinuz-linux root=/dev/vda rw console=ttyS0,115200\n  initrd /boot/initramfs-linux.img\n}\n' > /boot/grub/grub.cfg
'''
    out, rc = ser.run("chroot /newroot/mnt/target /bin/bash -c %s" % repr(final), timeout=900)
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
    phase_boot_loader(iso, rep, outdir, uefi=False)
    phase_boot_loader(iso, rep, outdir, uefi=True)
    phase_live_and_install(iso, rep, outdir)
    rep.save()
    print("[tests] rapport:", os.path.join(outdir, "report.md"), "FAILS=%d" % rep.fails, flush=True)
    sys.exit(1 if rep.fails else 0)


if __name__ == "__main__":
    main()
