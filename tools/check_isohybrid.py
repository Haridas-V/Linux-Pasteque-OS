#!/usr/bin/env python3
"""Vérifie qu'une ISO est flashable telle quelle avec balenaEtcher :
- signature MBR 0x55AA + entrée de partition bootable (isohybrid)
- El Torito BIOS + EFI présents
- rapport xorriso de la system area

Usage: python3 tools/check_isohybrid.py out/pasteque-dev.iso
Exit 0 si OK (compatible Etcher "Flash from file" sans option spéciale).
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TROOT = os.path.join(HERE, "root")


def tool_env():
    env = dict(os.environ)
    lib = os.path.join(TROOT, "usr/lib/x86_64-linux-gnu") + ":" + os.path.join(TROOT, "lib/x86_64-linux-gnu")
    env["LD_LIBRARY_PATH"] = lib + ":" + env.get("LD_LIBRARY_PATH", "")
    env["PATH"] = os.path.join(TROOT, "usr/bin") + ":" + env["PATH"]
    return env


def main():
    iso = sys.argv[1] if len(sys.argv) > 1 else sorted(__import__("glob").glob(os.path.join(REPO, "out/*.iso")))[-1]
    ok = True
    with open(iso, "rb") as f:
        f.seek(0)
        mbr = f.read(512)
    if mbr[510:512] != b"\x55\xaa":
        print("FAIL: pas de signature MBR 0x55AA (image non hybride)")
        ok = False
    else:
        print("PASS: signature MBR 0x55AA")
    parts = []
    for i in range(4):
        e = mbr[446 + 16 * i: 446 + 16 * (i + 1)]
        if any(e):
            boot = e[0] == 0x80
            ptype = e[4]
            start = struct.unpack("<I", e[8:12])[0]
            parts.append((i + 1, boot, ptype, start))
    if parts and any(p[1] for p in parts):
        print("PASS: partition MBR bootable (isohybrid):", parts)
    else:
        print("FAIL: aucune partition bootable dans le MBR -> Etcher ne verra pas d'image disque valide")
        ok = False
    if any(p[2] == 0xEF for p in parts):
        print("PASS: partition MBR 0xEF (ESP) presente -> boot UEFI depuis cle USB")
    else:
        print("FAIL: pas de partition 0xEF -> pas de boot UEFI depuis cle USB flashée")
        ok = False
    # El Torito
    out = subprocess.run([os.path.join(TROOT, "usr/bin/xorriso"), "-indev", iso,
                          "-report_el_torito", "plain"], capture_output=True, text=True, env=tool_env()).stdout
    has_bios = "isolinux.bin" in out or "eltorito" in out.lower()
    has_efi = "efi.img" in out or "EFI" in out
    print(("PASS" if has_bios else "FAIL") + ": El Torito BIOS présent")
    print(("PASS" if has_efi else "FAIL") + ": El Torito EFI présent")
    ok = ok and has_bios and has_efi
    # system area
    out2 = subprocess.run([os.path.join(TROOT, "usr/bin/xorriso"), "-indev", iso,
                           "-report_system_area", "plain"], capture_output=True, text=True, env=tool_env()).stdout
    print("--- system area ---")
    print("\n".join(out2.splitlines()[:12]))
    if "isohybrid" in out2.lower() or "MBR" in out2:
        print("PASS: system area isohybrid-MBR")
    else:
        print("WARN: system area non reconnue comme isohybrid")
    print("RESULT:", "ETCHER_COMPATIBLE" if ok else "NON_COMPATIBLE")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
