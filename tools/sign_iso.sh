#!/usr/bin/env bash
# Signe l'ISO Pastèque (signature GPG détachée) + empreinte SHA256.
# Usage :
#   SIGNING_KEY=0xDEADBEEF tools/sign_iso.sh out/pasteque-1.0.iso
# Sans SIGNING_KEY : ne produit que le .sha256 (pas de .asc).
# En CI : définir les secrets PASTEQUE_GPG_KEY (clé privée ASCII blindée) et
# PASTEQUE_GPG_PASSPHRASE -> le workflow importe la clé et signe automatiquement.
set -u
ISO="${1:?usage: SIGNING_KEY=0x... $0 out/pasteque-1.0.iso}"
[ -f "$ISO" ] || { echo "ISO introuvable: $ISO" >&2; exit 1; }
DIR="$(dirname "$ISO")"
BASE="$(basename "$ISO")"

# empreinte SHA256 (toujours) — ECHEC = FATAL (jamais de faux succes)
if ! (cd "$DIR" && sha256sum "$BASE" > "$BASE.sha256" && test -s "$BASE.sha256"); then
    echo "[sign] ERREUR: sha256 a echoue sur $ISO" >&2
    exit 1
fi
echo "[sign] sha256 OK -> $ISO.sha256"

# signature GPG détachée si une clé est disponible
KEY="${SIGNING_KEY:-${PASTEQUE_GPG_KEY_ID:-}}"
PASSPHRASE_ARGS=()
if [ -n "${PASTEQUE_GPG_PASSPHRASE:-}" ]; then
    PASSPHRASE_ARGS=(--pinentry-mode loopback --passphrase "$PASTEQUE_GPG_PASSPHRASE")
fi
if [ -n "$KEY" ]; then
    if gpg --batch --yes "${PASSPHRASE_ARGS[@]}" --local-user "$KEY" --armor --detach-sign --output "$ISO.asc" "$ISO" && [ -s "$ISO.asc" ]; then
        echo "[sign] signature GPG OK -> $ISO.asc (clé $KEY)"
        gpg --list-keys "$KEY" 2>/dev/null | head -3
    else
        echo "[sign] ERREUR: signature GPG a échoué (clé $KEY, passphrase ?)" >&2
        rm -f "$ISO.asc"
        exit 1
    fi
elif [ -n "${PASTEQUE_GPG_KEY:-}" ]; then
    # clé fournie en secret CI (ASCII) : import temporaire
    export GNUPGHOME="$(mktemp -d)"
    echo "$PASTEQUE_GPG_KEY" | gpg --batch --import 2>/dev/null
    FPR=$(gpg --list-secret-keys --with-colons 2>/dev/null | awk -F: '/^fpr/{print $10; exit}')
    if [ -n "$FPR" ]; then
        if gpg --batch --yes "${PASSPHRASE_ARGS[@]}" --local-user "$FPR" --armor --detach-sign --output "$ISO.asc" "$ISO" && [ -s "$ISO.asc" ]; then
            echo "[sign] signature GPG OK -> $ISO.asc (empreinte $FPR)"
        else
            echo "[sign] ERREUR: signature GPG a échoué (empreinte $FPR)" >&2
            rm -f "$ISO.asc"; rm -rf "$GNUPGHOME"; exit 1
        fi
        rm -rf "$GNUPGHOME"
    else
        echo "[sign] ERREUR: PASTEQUE_GPG_KEY fournie mais import impossible -> pas de .asc" >&2
        exit 1
    fi
else
    echo "[sign] pas de clé GPG (SIGNING_KEY / PASTEQUE_GPG_KEY) -> sha256 seul."
    echo "[sign] pour signer : SIGNING_KEY=0x... $0 $ISO   (ou importer ta clé et signer $ISO.asc)"
fi
