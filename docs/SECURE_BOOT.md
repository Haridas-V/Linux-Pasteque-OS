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

## Enrôlement de la clé MOK (UNE seule fois, par machine)

La clé privée de build ne quitte jamais la machine de build ; seule la **clé publique**
`Pasteque.der` (embarquée dans l'ISO à `/usr/share/pasteque/mok/Pasteque.der`) doit être
enrôlée dans le MOK de chaque PC.

### Méthode recommandée (deux boots)

1. **Premier boot avec Secure Boot = OFF** (BIOS) : la clé Pastèque démarre normalement
   (le shim laisse passer, les signatures sont ignorées).
2. Dans la session live (ou installée), demander l'enrôlement :
   ```bash
   sudo mokutil --import /usr/share/pasteque/mok/Pasteque.der
   ```
   → entrer un **mot de passe temporaire** (8–64 caractères, à ressaisir au prochain boot), confirmez.
   (`mokutil --import` écrit la demande dans la variable EFI `MokNew`.)
3. **Redémarrer**, puis dans le BIOS passer **Secure Boot = ON**.
4. Au boot suivant, le shim (signé Microsoft, donc accepté par `db`) voit `MokNew` pending
   et lance automatiquement le **MokManager** (écran bleu) :
   `Enroll MOK` → `Continue` → `Yes` → saisissez le mot de passe → `Reboot`.
5. Vérifications :
   ```bash
   mokutil --sb-state                                  # -> SecureBoot enabled
   mokutil --test-key /usr/share/pasteque/mok/Pasteque.der   # -> "is already in the MOK list" / known
   pasteque-secureboot                                 # empreinte + état
   dmesg | grep -i "secure boot"                       # -> "Secure Boot enabled"
   ```

### Méthode alternative (un seul boot, clé USB FAT)

1. Copier `Pasteque.der` à la racine d'une **petite clé USB formatée en FAT**.
2. Boot avec **Secure Boot = ON** : le shim bloque `grubx64.efi` (non signé par `db`)
   et affiche « Security Violation » ; appuyez sur une touche pour entrer le **MokManager**.
3. `Enroll MOK` → `View key` / choisissez le fichier `Pasteque.der` sur la clé USB → `Continue` → `Yes` → `Reboot`.

### Points importants

- La clé embarquée dans l'ISO (`/usr/share/pasteque/mok/Pasteque.der`) correspond à la clé
  de build courante (`work/sb/`, empreinte dans `FINGERPRINT.txt`). Si l'ISO est rebuildée
  avec une **nouvelle** clé SB, il faut ré-enrôler la nouvelle clé (et révoquer l'ancienne :
  MokManager → `Reset MOK` ou `Delete MOK`).
- Sans enrôlement, Secure Boot ON bloque le boot (comportement normal, voir ci-dessous).
- `mokutil --import` nécessite une session démarrée : faites donc d'abord un boot
  Secure Boot OFF (méthode 1), ou utilisez la méthode clé USB (méthode 2).

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
