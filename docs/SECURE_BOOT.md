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
2. Boot avec **Secure Boot = ON**. Deux possibilités :
   - le shim bloque `grubx64.efi` (non signé par `db`) et affiche « Security Violation » ;
     selon la version du shim, une touche permet d'ouvrir le **MokManager** ;
   - ou lancer directement le MokManager embarqué sur la clé Pastèque :
     menu de boot du firmware → lancez `\EFI\BOOT\mmx64.efi`
     (MokManager signé Microsoft, embarqué dans l'ESP de l'ISO).
3. Dans le MokManager : `Enroll MOK` → `Enroll key from file` (ou `View key` selon version)
   → choisissez `Pasteque.der` sur la clé USB FAT → `Continue` → `Yes` → `Reboot`.

> Note : la clé est enrôlée dans **MokList** (GUID du shim), pas dans `db` — c'est le
> mécanisme standard MOK, et c'est aussi ce que fait le test automatisé ci-dessous
> (`--add-mok` avec le GUID shim `605dab50-e046-4300-abb6-3dd810dd8b23`).

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
- Le noyau LTS de secours est signé lui aussi (même clé), embarqué dans l'ISO et dans l'ESP.

## Tests automatisés (vraiment exécutés, pas simulés)

`tests/sb_boot_test.py` (lancé par le workflow CI après le build de l'ISO) :

1. construit deux varstores OVMF réels avec `virt-fw-vars` et les **re-lit** pour prouver
   `SecureBoot=1` : un avec la clé Pastèque dans `db` **et** `MokList` (positif),
   un avec seulement les clés Microsoft (négatif) ;
2. écrit l'ISO en bloc sur un disque virtio (comme `dd`/Etcher sur clé USB — la partition
   MBR `0xEF` contient l'ESP) ;
3. boot **OVMF secboot réel** (`q35,smm=on`, pflash `secure=on`) :
   - **positif** : le boot doit aller jusqu'au système live, avec le marqueur
     `PASTEQUE-SECUREBOOT: 1` (lu depuis `/sys/kernel/security/secureboot`, écrit sur la
     console par `pasteque-liveuser`) et **aucun** `module verification failed` ;
   - **négatif** : sans la clé, le shim doit bloquer le boot (aucun login atteint).
4. le build lui-même échoue désormais si un composant de la chaîne SB n'est pas signé
   (`require_signed_iso_kernel` dans `tools/build_sandbox.py`, `sbverify --cert` sur les
   noyaux embarqués ISO + ESP).

Ce test tourne sous **QEMU TCG avec le vrai firmware OVMF** : c'est une validation réelle de
la chaîne de signatures, mais **pas** une validation matérielle. Sur un vrai PC, refaire :
`mokutil --sb-state` (doit dire `enabled`), boot avec la clé enrôlée, et
`dmesg | grep -i "secure boot\|module verification"` — voir
`docs/POINTS_A_VALIDER_EN_MATERIEL.md`.

## Le système INSTALLÉ sous Secure Boot (vrai matériel — issue « runs 73/74 »)

La live bootée depuis la clé USB a toute la chaîne signée (testée en OVMF secboot :
`SB_POSITIVE_OK SB_NEGATIVE_OK`). Mais à l'**installation**, le module `bootloader`
de Calamares écrit sur l'ESP un `grubx64.efi` **non signé** (celui du paquet grub) :
un vrai firmware avec Secure Boot actif le rejette — c'est l'écart VM vs matériel réel.

Correction (build + install) :

1. **Le build embarque la chaîne signée dans l'airootfs** :
   `/usr/share/pasteque/sb/{shimx64.efi, grubx64.efi, mmx64.efi}` + `SHA256SUMS`
   (noms ESP : `BOOTX64.EFI`, `grubx64.efi`, `mmx64.efi`), copiés **avant** le
   `mksquashfs` pour être dans le squashfs. Le build **échoue** si un composant est
   absent ou non signé (`pe_signed` + `sbverify --cert work/sb/sb.crt` sur le grub).
2. **`settings.conf`** : `shellprocess` (notre `pasteque-finalize-install`) tourne
   désormais **après** `bootloader`/`grubcfg`, donc sa copie gagne sur le grub non signé.
3. **`pasteque-secureboot-install`** (appelé par finalize, testé fonctionnellement) :
   copie le shim signé Microsoft en `EFI/BOOT/BOOTX64.EFI`, le grub signé en
   `EFI/BOOT/grubx64.efi` **et** dans le répertoire distro `EFI/<vendor>/`, le
   MokManager en `EFI/BOOT/mmx64.efi`, crée l'entrée `efibootmgr` vers
   `\EFI\BOOT\BOOTX64.EFI`, puis **vérifie `sha256sum -c SHA256SUMS`** (exit 1 si
   la chaîne copiée ne correspond pas au build). Sans ESP (install BIOS) : exit 0.

Chaîne résultante sur le disque installé, identique à la live :
`firmware db (Microsoft) → BOOTX64.EFI (shim MS) → grubx64.efi (signé, vérifié MOK) → vmlinuz (signé) → modules (signés)`.

Test VM : `install-sb-chaine-esp`, `install-sb-sha256-esp`, `install-sb-grub-distro-remplace-par-signe`
dans `tests/live_shell.py` (ESP simulée dans la cible, install réelle du script en chroot).
Reste à valider sur vrai PC : enrôler le MOK (procédure ci-dessus), SB=ON, booter le disque installé.
