#!/usr/bin/env bash
# Vérifie l'intégrité (SHA256) et l'authenticité (signature GPG, si clé importée) d'une ISO Pastèque.
# Usage : tools/verify_iso.sh out/pasteque-1.0.iso [empreinte_empreinte_gpg_attendue]
#   - sans clé GPG importée : vérifie seulement le sha256 (et avertit si un .asc existe)
#   - avec la clé publique de signature importée : vérifie aussi la signature .asc
set -u
ISO="${1:?usage: $0 out/pasteque-1.0.iso [fingerprint_gpg_attendu]}"
EXPECT_FPR="${2:-}"
[ -f "$ISO" ] || { echo "ISO introuvable: $ISO" >&2; exit 1; }
cd "$(dirname "$ISO")"
BASE="$(basename "$ISO")"
rc=0

if [ -f "$BASE.sha256" ]; then
    sha256sum -c "$BASE.sha256" || rc=1
else
    echo "[verify] pas de $BASE.sha256" >&2; rc=1
fi

if [ -f "$BASE.asc" ]; then
    if gpg --verify --status-fd 1 "$BASE.asc" "$BASE" >/tmp/gpgverify.log 2>&1; then
        fpr=$(awk '/\[GNUPG:\] VALIDSIG/{print $3; exit}' /tmp/gpgverify.log)
        echo "[verify] signature GPG OK (empreinte: ${fpr:-inconnue})"
        if [ -n "$EXPECT_FPR" ] && [ "$fpr" != "${EXPECT_FPR// /}" ]; then
            echo "[verify] ERREUR: empreinte $fpr != attendue $EXPECT_FPR" >&2; rc=1
        fi
    else
        echo "[verify] signature GPG INVALIDE (voir /tmp/gpgverify.log)" >&2; rc=1
    fi
else
    echo "[verify] pas de signature .asc (sha256 seul)"
fi
exit $rc
