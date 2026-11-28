#!/usr/bin/env python3
"""Génère le logo Pastèque (pastèque 128x128, PNG pur Python) :
profile/airootfs/usr/share/pasteque/logo.png + copie pour le thème GRUB.
"""
import math
import os
import struct
import sys
import zlib

S = 128


def write_png(path, w, h, pix):
    raw = b"".join(b"\x00" + bytes(pix[y * w * 4:(y + 1) * w * 4]) for y in range(h))
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)


def logo():
    pix = bytearray(S * S * 4)
    cx = cy = S / 2
    for y in range(S):
        for x in range(S):
            d = math.hypot(x - cx, y - cy)
            i = (y * S + x) * 4
            r, g, b, a = 16, 20, 24, 255  # fond sombre
            if d < 58:  # pastèque verte
                stripe = abs(math.sin((x + y) * 0.35)) < 0.25
                r, g, b = (30, 110, 50) if stripe else (70, 170, 90)
                if d > 52:
                    r, g, b = 20, 70, 35  # écorce foncée
                if d < 38:  # chair rouge
                    r, g, b = (229, 72, 77)
                    # pépins
                    if (x * 7 + y * 13) % 23 < 2 and d < 34:
                        r, g, b = 30, 20, 20
            pix[i:i + 4] = bytes((r, g, b, a))
    return pix


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    dests = [os.path.join(repo, "profile/airootfs/usr/share/pasteque/logo.png"),
             os.path.join(repo, "profile/airootfs/usr/share/grub/themes/pasteque/logo.png")]
    for d in dests:
        os.makedirs(os.path.dirname(d), exist_ok=True)
        write_png(d, S, S, logo())
        print("[logo]", d)


if __name__ == "__main__":
    main()
