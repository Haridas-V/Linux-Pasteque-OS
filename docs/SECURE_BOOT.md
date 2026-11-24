# Secure Boot avec Pastèque Linux

## Chaîne de confiance embarquée

```
firmware (db Microsoft)
  └─► shimx64.efi          = BOOTX64.EFI  (shim signé Microsoft, paquet Ubuntu shim-signed)
        └─► grubx64.efi     (GRUB signé avec la clé Pastèque, vérifiée contre le MOK)
              └─► vmlinuz-linux / vmlinuz-lts  (EFI stub signés sbsign, clé Pastèque)
                    └─► modules .ko  (signés CMS/PKCS#7, clé Pastèque)
```

- La **clé publique** à enrôler est embarquée : `/usr/share/pasteque/mok/Pasteque.der`
  (+ empreinte dans `FINGERPRINT.txt`).
- Le **MokManager** (`mmx64.efi`, signé Microsoft) est embarqué pour l'enrôlement au boot.
- Outils de build : `tools/fetch_shim.py` (shim Ubuntu), `tools/sb_sign.py` (clé + signatures),
  étape `secureboot` du build.

## Enrôlement (UNE seule fois, par machine)

1. BIOS : **Secure Boot = Enabled**.
2. Boot la clé Pastèque → si la clé Pastèque n'est pas dans le MOK, le firmware bloque
   (écran « Secure Boot violation »).
3. Sur une session Pastèque (ou live) : `sudo mokutil --import /usr/share/pasteque/mok/Pasteque.der`
   → entrer un mot de passe temporaire → **redémarrer**.
4. Au boot, écran bleu **MokManager** : `Enroll key` → `Continue` → `Yes` → entrer le mot de passe → `Reboot`.
5. Vérifier : `pasteque-secureboot` (affiche l'état + l'empreinte), `mokutil --sb-state` → `SecureBoot enabled`,
   `mokutil --test-key /usr/share/pasteque/mok/Pasteque.der` → clé connue.

## Sans enrôlement

Secure Boot ON + clé non enrôlée → boot bloqué (comportement normal).
Secure Boot OFF → tout boot (shim laisse passer, signatures ignorées).

## Signature des livrables (intégrité)

- `sha256` de l'ISO toujours généré (`pasteque-1.0.iso.sha256`).
- **Signature GPG** `pasteque-1.0.iso.asc` si une clé est configurée :
  - local : `SIGNING_KEY=0x... tools/sign_iso.sh out/pasteque-1.0.iso`
  - CI : secrets `PASTEQUE_GPG_KEY` (clé privée) + `PASTEQUE_GPG_PASSPHRASE`.
- Vérification : `tools/verify_iso.sh pasteque-1.0.iso [empreinte_gpg_attendue]`

## Limites connues

- Chaque machine doit enrôler la clé MOK une fois (standard MOK).
- Si vous rebuildz l'ISO avec une **nouvelle** clé SB (`work/sb/` supprimé ou `SB_KEY`/`SB_CRT` changés),
  il faut ré-enrôler la nouvelle clé.
- Le noyau LTS de secours est signé lui aussi (même clé).
