#!/usr/bin/env bash
# Pastèque Linux — build reproductible de l'ISO en UNE commande.
#
# Sur un hôte Arch (ou dans le conteneur archlinux:ci) :
#   sudo ./build.sh
# Sans archiso installé, utilise Docker automatiquement.
set -euo pipefail
cd "$(dirname "$0")"

PROFILE="profile"
WORK="${WORK:-$PWD/work/mkarchiso}"
OUT="${OUT:-$PWD/out}"

mkdir -p "$OUT"

if command -v mkarchiso >/dev/null 2>&1; then
    exec sudo mkarchiso -v -w "$WORK" -o "$OUT" "$PROFILE"
fi

if command -v docker >/dev/null 2>&1; then
    echo "[build] mkarchiso absent -> conteneur archlinux:ci"
    exec docker run --rm -it \
        -v "$PWD:/pasteque" -w /pasteque \
        archlinux:ci bash -c "pacman -Sy --noconfirm archiso && mkarchiso -v -w /pasteque/work/mkarchiso -o /pasteque/out $PROFILE"
fi

echo "[build] ERREUR: installez archiso (pacman -S archiso) ou docker." >&2
exit 1
