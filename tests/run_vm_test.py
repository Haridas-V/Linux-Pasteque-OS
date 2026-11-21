#!/usr/bin/env python3
"""Boot-test a Pastèque ISO in QEMU (TCG, no KVM needed).

Extracts kernel+initrd from the ISO, boots with console=ttyS0, captures the
serial log and timestamped screendumps as proof.

Usage: python3 tests/run_vm_test.py [iso] [--timeout 600] [--ram 2048]
Artifacts: tests/artifacts/<run-ts>/serial.log, screen-*.png
"""
import argparse
import glob
import json
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
ART = os.path.join(HERE, "artifacts")


def tool_env():
    env = dict(os.environ)
    lib = os.path.join(TROOT, "usr/lib/x86_64-linux-gnu") + ":" + os.path.join(TROOT, "lib/x86_64-linux-gnu")
    env["LD_LIBRARY_PATH"] = lib + ":" + env.get("LD_LIBRARY_PATH", "")
    env["PATH"] = os.path.join(TROOT, "usr/bin") + ":" + os.path.join(TROOT, "usr/sbin") + ":" + env["PATH"]
    return env


class QMP:
    def __init__(self, path):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.connect(path)
        self.f = self.s.makefile("rw")
        self._read()  # greeting
        self.cmd("qmp_capabilities")

    def _read(self):
        line = self.f.readline()
        return json.loads(line) if line.strip() else None

    def cmd(self, name, **args):
        self.f.write(json.dumps({"execute": name, "arguments": args}) + "\n")
        self.f.flush()
        while True:
            r = self._read()
            if r and "return" in r:
                return r["return"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("iso", nargs="?", default=sorted(glob.glob(os.path.join(REPO, "out/*.iso")))[-1])
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--ram", type=int, default=2048)
    ap.add_argument("--label", default="PASTEQUE")
    args = ap.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(ART, run_id)
    os.makedirs(outdir, exist_ok=True)
    serial = os.path.join(outdir, "serial.log")
    qmp_sock = os.path.join(outdir, "qmp.sock")

    # extract kernel/initrd from the ISO
    ext = os.path.join(REPO, "work", "isoextract-" + run_id)
    shutil.rmtree(ext, ignore_errors=True)
    os.makedirs(ext, exist_ok=True)
    subprocess.run([os.path.join(TROOT, "usr/bin/xorriso"), "-osirrox", "on",
                    "-overwrite", "on", "-indev", args.iso, "-extract", "/", ext],
                   check=True, env=tool_env(), stdout=subprocess.DEVNULL)
    kernel = os.path.join(ext, "boot/x86_64/vmlinuz-linux")
    initrd = os.path.join(ext, "boot/x86_64/initramfs-linux.img")
    assert os.path.exists(kernel) and os.path.exists(initrd), "kernel/initrd absents de l'ISO"

    cmd = [os.path.join(TROOT, "usr/bin/qemu-system-x86_64"),
           "-L", os.path.join(TROOT, "usr/share/qemu"),
           "-machine", "q35", "-m", str(args.ram), "-smp", "2",
           "-cdrom", args.iso, "-boot", "d",
           "-kernel", kernel, "-initrd", initrd,
           "-append", "archisolabel=%s archisobasedir=arch console=ttyS0,115200" % args.label,
           "-display", "none", "-vga", "std",
           "-serial", "file:" + serial,
           "-qmp", "unix:%s,server,nowait" % qmp_sock,
           "-no-reboot"]
    print("[vm] qemu:", " ".join(cmd[1:6]), "...", flush=True)
    proc = subprocess.Popen(cmd, env=tool_env(), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    qmp = None
    for _ in range(30):
        if os.path.exists(qmp_sock):
            try:
                qmp = QMP(qmp_sock)
                break
            except Exception:
                pass
        if proc.poll() is not None:
            print("[vm] qemu a quitté prématurément rc=", proc.returncode, flush=True)
            break
        time.sleep(0.5)
    assert qmp is not None, "QMP indisponible"
    markers = ["Login", "login:", "Reached target", "Started Getty", "systemd", "Welcome"]
    ok = False
    t0 = time.time()
    shots = 0
    last_len = 0
    while time.time() - t0 < args.timeout:
        time.sleep(5)
        if os.path.exists(serial):
            data = open(serial, "rb").read().decode("utf-8", "replace")
            if len(data) != last_len:
                last_len = len(data)
            if any(m.lower() in data.lower() for m in ["reached target", "login:", "multi-user"]):
                ok = True
        # screendump toutes les 30s
        if int(time.time() - t0) // 30 > shots:
            shots += 1
            ppm = os.path.join(outdir, "screen-%02d-%s.ppm" % (shots, time.strftime("%H%M%S")))
            try:
                qmp.cmd("screendump", filename=ppm)
                from PIL import Image
                img = Image.open(ppm)
                img.save(ppm.replace(".ppm", ".png"))
                os.unlink(ppm)
            except Exception as e:
                print("[vm] screendump KO:", e, flush=True)
        if proc.poll() is not None:
            break
        if ok and int(time.time() - t0) > 120:
            # laisser la VM monter un peu puis arrêter
            time.sleep(20)
            break
    try:
        qmp.cmd("quit")
    except Exception:
        pass
    proc.wait(timeout=30)

    data = open(serial, "rb").read().decode("utf-8", "replace") if os.path.exists(serial) else ""
    tail = "\n".join(data.splitlines()[-25:])
    print("[vm] === serial tail ===\n" + tail, flush=True)
    print("[vm] RESULT:", "BOOT_OK" if ok else "BOOT_NOT_CONFIRMED", flush=True)
    print("[vm] artifacts:", outdir, flush=True)
    with open(os.path.join(outdir, "result.txt"), "w") as f:
        f.write("BOOT_OK\n" if ok else "BOOT_NOT_CONFIRMED\n")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
