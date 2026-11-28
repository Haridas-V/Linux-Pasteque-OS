# Phase 1 — Audit complet du projet (commit 5d70609)

## Architecture actuelle
- **Base** : Arch Linux, KDE Plasma 6 Wayland, FR, sombre par défaut. ✅ conservée
- **Build** : `tools/build_sandbox.py` (rootless, userns+chroot) en CI (conteneur trixie privilégié) + `build.sh` (mkarchiso, chemin secondaire documenté)
- **ISO** : hybride isohybrid (BIOS isolinux + UEFI grub/shim), `pasteque-1.0.iso` ~5,8 Go, squashfs xz
- **Install** : Calamares 3.4.2 (AUR, buildé au build) : effacer disque / dual-boot / LUKS
- **Overlay anti-frustration** : 30 scripts `pasteque-*` dans `profile/airootfs/usr/local/bin/`
- **Tests** : 14 unitaires (`tests/test_units.py`, CI avant build) + 46 checks live (`live_tests.sh`) + VM QEMU (boot CD/USB BIOS+UEFI, install disque virtuel)
- **Agents** : `agents/` orchestrateur + 4 sous-agents (Mistral SDK épinglé 1.1.3)

## Ce qui marche (preuves CI run `487971d7` vert)
14/14 unitaires, build ISO OK, `ETCHER_COMPATIBLE`, `USB_BOOT_OK` + `USB_UEFI_BOOT_OK`, 12 982 modules signés SB, shim OK, install+boot disque virtuel OK.

## Bugs / zones fragiles identifiés
1. **Boot CD en QEMU** (`boot-bios/uefi-chargeur`, `live-mount`, `BOOT_NOT_CONFIRMED`) : FAIL depuis que l'ISO a grossi (5,8 Go) — boot USB OK. Logs détaillés désormais uploadés (`test-logs`) pour diagnostiquer au prochain run. Piste : initramfs/archiso sur CD vs disque.
2. **Ordre des étapes SB** : `secureboot` tournait avant la création d'`efiwork` → grub EFI non signé embarqué. Corrigé (`--efi-only` dans `step_iso`, commit `91e37fb`).
3. **Mises à jour auto par défaut** (`AUTO_UPDATE=1`) : contraire à la philosophie « contrôle utilisateur » → passer en manuel par défaut, garder le bouton GUI.
4. Pas d'**app centrale** (hub) — dispersé en plusieurs apps.
5. Pas de **profils par jeu** (env/priorité/proton par jeu), pas de **gestionnaire de priorités**, pas de **benchmark**, pas de **GUI pare-feu**, pas de **diagnostic système**, pas de **profils d'apparence** sauvegardés, pas de **thème GRUB** Pastèque.
6. Gaming : ProtonUp-Qt et gamescope non embarqués ; Bottles (Flatpak) documenté seulement.
7. App manager : pas de recherche globale multi-sources.

## Plan d'évolution (priorisé)
- **CRITIQUE** : diagnostiquer/fixer boot CD (logs du prochain run) ; maj manuelles par défaut
- **IMPORTANT** : hub central `pasteque-hub` ; profils par jeu (pasteque-games) ; priorités (`pasteque-priorites`) ; benchmark (`pasteque-benchmark`) ; pare-feu GUI (`pasteque-parefeu`) ; diagnostic (`pasteque-diagnostic`) ; profils d'apparence save/restore dans `pasteque-personnalise` ; thème GRUB Pastèque ; recherche globale appmanager ; gamescope + ProtonUp-Qt embarqués
- **MOYEN** : install AUR guidé ; packs de thèmes
- **FACULTATIF** : fonds animés (option, non imposé)
