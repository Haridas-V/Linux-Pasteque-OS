#!/usr/bin/env python3
"""Génère 3 fonds d'écran PNG Pastèque (dégradés sobres) sans aucune dépendance
(PNG écrit à la main : zlib + struct). Appelé au build -> airootfs/usr/share/backgrounds/pasteque/.
Usage : python3 tools/gen_wallpapers.py [destdir]
"""
import os
import struct
import sys
import zlib

W, H = 1920, 1080

WALLS = {
    "pasteque-sombre.png": ((16, 20, 24), (30, 60, 40), (120, 30, 35)),   # vert pastèque sombre + touche rouge
    "ocean-nuit.png":      ((10, 16, 32), (16, 42, 74), (24, 90, 110)),
    "soleil-froid.png":    ((24, 18, 30), (70, 40, 60), (180, 90, 60)),
}


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def write_png(path, pix):
    raw = b"".join(b"\x00" + bytes(pix[y * W * 3:(y + 1) * W * 3]) for y in range(H))
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    open(path, "wb").write(png)


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "profile/airootfs/usr/share/backgrounds/pasteque")
    os.makedirs(dest, exist_ok=True)
    for name, (c0, c1, c2) in WALLS.items():
        pix = bytearray(W * H * 3)
        for y in range(H):
            t = y / (H - 1)
            row = lerp(c0, c1, t)
            # bande diagonale douce vers c2
            for x in range(W):
                tt = min(1.0, max(0.0, (x / W + t) / 2))
                c = lerp(row, c2, tt * 0.35)
                i = (y * W + x) * 3
                pix[i:i + 3] = bytes(c)
        p = os.path.join(dest, name)
        write_png(p, pix)
        print("[wallpapers]", p, os.path.getsize(p) // 1024, "Ko")


if __name__ == "__main__":
    main()
