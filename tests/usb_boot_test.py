#!/usr/bin/env python3
"""Simule un flash balenaEtcher : copie brute de l'ISO sur un disque brut
(ce qu'Etcher écrit sur la clé USB, offset 0, system area comprise), puis boot
QEMU depuis ce disque : en BIOS via le MBR isohybrid, et avec --uefi en UEFI
(OVMF) via la partition MBR 0xEF (ESP). Si ça boot, la clé flashée par
Etcher boote aussi.

Usage: python3 tests/usb_boot_test.py [--uefi] [--timeout N] [iso]
"""
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
    env["PATH"] = os.path.join(TROOT, "usr/bin") + ":" + env["PATH"]
    return env


def boot_mode(usb, sock, outdir, name, timeout, uefi):
    if os.path.exists(sock):
        os.remove(sock)
    qemu = [os.path.join(TROOT, "usr/bin/qemu-system-x86_64"),
            "-L", os.path.join(TROOT, "usr/share/qemu"),
            "-machine", "q35", "-m", "3072", "-smp", "2",
            "-drive", "file=%s,format=raw,if=virtio" % usb,
            "-display", "none", "-vga", "std", "-no-reboot",
            "-serial", "unix:%s,server,nowait" % sock]
    if uefi:
        vars_copy = os.path.join(outdir, "ovmf-vars-%s.fd" % name)
        shutil.copyfile(os.path.join(TROOT, "usr/share/OVMF/OVMF_VARS_4M.fd"), vars_copy)
        qemu += ["-drive", "if=pflash,format=raw,readonly=on,file=%s" % os.path.join(TROOT, "usr/share/OVMF/OVMF_CODE_4M.fd"),
                 "-drive", "if=pflash,format=raw,file=%s" % vars_copy]
    proc = subprocess.Popen(qemu, env=tool_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = False
    for _ in range(60):
        if os.path.exists(sock):
            break
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    if os.path.exists(sock):
        s = socket.socket(socket.AF_UNIX)
        for _ in range(20):
            try:
                s.connect(sock)
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("socket série indisponible")
        s.settimeout(2)
        buf = b""
        end = time.time() + timeout
        while time.time() < end:
            try:
                d = s.recv(65536)
                if not d:
                    break
                buf += d
            except socket.timeout:
                pass
            if re.search(rb"pasteque login:|Reached target|Started Simple Desktop|systemd-udevd", buf):
                ok = True
                break
        open(os.path.join(outdir, "serial-%s.log" % name), "wb").write(buf)
        s.close()
    try:
        proc.kill()
        proc.wait(timeout=20)
    except Exception:
        pass
    return ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    timeout = 600
    if "--timeout" in sys.argv:
        timeout = int(sys.argv[sys.argv.index("--timeout") + 1])
    do_uefi = "--uefi" in sys.argv
    iso = args[0] if args else sorted(glob.glob(os.path.join(REPO, "out/*.iso")))[-1]
    run_id = time.strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(ART, run_id)
    os.makedirs(outdir, exist_ok=True)

    # 0) vérification isohybrid (compat Etcher)
    chk = subprocess.run([sys.executable, os.path.join(TOOLS, "check_isohybrid.py"), iso],
                         capture_output=True, text=True)
    open(os.path.join(outdir, "isohybrid-check.txt"), "w").write(chk.stdout + chk.stderr)
    print(chk.stdout, flush=True)
    etcher_ok = chk.returncode == 0

    # 1) "flash" : copie brute de l'ISO (comme Etcher)
    usb = os.path.join(WORK, "usb-flash.raw")
    if not os.path.exists(usb) or os.path.getsize(usb) != os.path.getsize(iso):
        print("[usb] copie brute de l'ISO ->", usb, flush=True)
        shutil.copyfile(iso, usb)

    ok_bios = boot_mode(usb, os.path.join(outdir, "ser-usb-bios.sock"), outdir, "usb-bios", timeout, False)
    ok_uefi = boot_mode(usb, os.path.join(outdir, "ser-usb-uefi.sock"), outdir, "usb-uefi", timeout, True) if do_uefi else None
    results = ["USB_BOOT_OK" if (ok_bios and etcher_ok) else "USB_BOOT_FAIL"]
    if do_uefi:
        results.append("USB_UEFI_BOOT_OK" if ok_uefi else "USB_UEFI_BOOT_FAIL")
    open(os.path.join(outdir, "result.txt"), "w").write("\n".join(results) + "\n")
    print("[usb] RESULT:", ", ".join(results),
          "(isohybrid Etcher-compatible:", etcher_ok, ", boot BIOS disque flashé:", ok_bios,
          ", boot UEFI disque flashé:", ok_uefi, ")", flush=True)
    print("[usb] artifacts:", outdir, flush=True)
    sys.exit(0 if ok_bios and etcher_ok and (ok_uefi is not False) else 2)


if __name__ == "__main__":
    main()
