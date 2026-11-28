# Architecture de Pastèque Linux

## Principes

1. **Installé une fois, plus jamais touché** : tout est dans l'ISO (hors-ligne).
2. **Zéro configuration post-installation** : aucun terminal nécessaire.
3. **Tout est réversible** : chaque préréglage est modifiable (voir MAINTENANCE.md).
4. **Tests honnêtes** : on ne déclare « testé » que ce qui a vraiment été exécuté
   (voir POINTS_A_VALIDER_EN_MATERIEL.md pour le reste).

## Chaîne de build

Deux chemins produisent la **même ISO** :

| Chemin | Commande | Quand |
|---|---|---|
| Standard | `sudo ./build.sh` | hôte Arch (mkarchiso + profil `profile/`) ou Docker `archlinux:ci` |
| Sans root | `python3 tools/build_sandbox.py all` | sandbox/CI sans root |

`build_sandbox.py` enchaîne :

1. `tools` — outillage extrait de .deb Debian sans root (`fetch_deb_tools.py`) :
   xorriso, grub, mksquashfs, qemu, syslinux, cpio…
2. `bootstrap` — `archrepo.py` télécharge `pacman` + deps depuis les miroirs Arch
   et les extrait dans `work/rootfs` (mini-résolveur de dépendances).
3. `install` — **vrai pacman** dans un chroot user-namespace (`chroot.sh`, euid 0
   mappé) installe `profile/packages.x86_64` ; l'overlay `profile/airootfs/` est
   appliqué ; `pacman.conf` de production copiée.
4. `aur` — `packages-aur/*` : PKGBUILD téléchargé depuis l'AUR, compilé en chroot
   (`makepkg` en user `builder`), installé dans l'ISO (ex. **calamares**).
5. `extras` — `fetch_extras.py` embarque les releases GitHub : **Proton-GE**,
   **Wine-GE**, **Heroic** (AppImage), **Teams** (AppImage) dans
   `/opt/pasteque/extras`.
6. `initramfs` — `mkinitcpio` réel en chroot (preset archiso + hook maison
   `pasteque_mods` qui charge explicitement les modules de boot ;
   `patch_initcpio.py` adapte mkinitcpio aux chroots sans `/proc/self/fd`).
7. `iso` — `mksquashfs` (xz, `-all-root`) + isolinux (BIOS) + grub-mkimage (UEFI)
   + `xorriso` hybride (MBR + El Torito) → `out/pasteque-*.iso` + sha256.

## Layout de l'ISO

```
/boot/x86_64/vmlinuz-linux, initramfs-linux.img
/boot/isolinux/…            (BIOS)
/boot/grub/grub.cfg + efi.img (UEFI)
/arch/x86_64/airootfs.sfs   (squashfs du système complet)
```

Boot : initramfs (hook `pasteque_mods` charge sr_mod/cdrom/ahci/usb-storage/
nvme/loop/squashfs/isofs/overlay + fs) → hook `archiso` monte l'ISO par label
`PASTEQUE` → overlay tmpfs → switch_root → systemd → SDDM (Wayland, autologin
`live` en session ISO).

## Surcouche anti-frustration (dans `profile/airootfs`)

| Composant | Fichiers | Rôle |
|---|---|---|
| App indexer | `usr/local/bin/pasteque-appindexer` + timer user | .exe (icône via wrestool), AppImages, binaires perso → entrées `.desktop` dans le menu KDE + krunner |
| Gestionnaire d'apps | `usr/local/bin/pasteque-appmanager` (PyQt6) | retrait en 2 clics (pacman -Rns / flatpak --delete-data / rm AppImage/.exe) + nettoyage résidus ; onglets jeux/anti-cheat, corbeille, réglages |
| Corbeille rotative | `usr/local/bin/pasteque-rotating-trash` + timer user | copie la corbeille KDE vers `~/.local/share/pasteque-trash`, plafonnée (ROTATING_TRASH_GB), restauration via GUI/CLI |
| Updater + rollback | `usr/local/bin/pasteque-update` + timer 6 h, `pasteque-bootcheck` | update seulement si idle (logind IdleHint), snapshots Btrfs pre/post, entrées GRUB, rollback auto si boot KO |
| Immuabilité | `usr/local/bin/pasteque-immutable-usr` + conf | curseur 0..5 ; ≥3 → `/usr` en overlayfs lecture seule |
| Anti-cheat | `usr/local/bin/pasteque-anticheat*` + `usr/share/pasteque/anticheat-db.json` | statut embarqué (areweanticheatyet/ProtonDB) + avertissement au lancement via launch options Steam |
| Steam disques externes | `usr/local/bin/pasteque-steamlibs` + timer | détecte `SteamLibrary` sur /run/media, /mnt, /media → `libraryfolders.vdf` |
| Extras embarqués | `pasteque-extras.service` | installe Proton-GE (`compatibilitytools.d`) et Wine-GE (runner Lutris) pour chaque utilisateur |

## Installateur (Calamares)

`profile/airootfs/etc/calamares/` : séquence 4 écrans (welcome → locale →
clavier → partition → users → summary), `partition.conf` = **effacer le disque
entier** (Btrfs) avec confirmation explicite, `users.conf` = compte non-root,
groupe wheel, root verrouillé. Job `shellprocess_pasteque` →
`pasteque-finalize-install` (sécurité, SDDM Wayland, services Pastèque,
initramfs cible, extras utilisateur).

## Tests

`tests/run_vm_test.py` : QEMU TCG (pas besoin de KVM), boot par `-kernel`/`-initrd`
extraits de l'ISO, console série + screendumps QMP horodatés dans
`tests/artifacts/<ts>/`. Résultat `BOOT_OK` = cible multi-user/graphical atteinte.
