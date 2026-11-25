# Trace d'avancement — mission évolution majeure (mise à jour continue)

Dernier commit : voir `git log -1`. Dernier run CI vert connu : `45671411328` (819017c). Run en cours : `45692017151` (9a58a4c).

## Fait (avec preuves)
- Phase 0/1 : diagnostic `docs/PHASE0_DIAGNOSTIC.md`, audit `docs/AUDIT_PHASE1.md`, fixes CI (chroot return, sbsigntool, shim version, workflow apostrophe, kdeconnect), 18 tests unitaires PASS en local et CI
- Boot : hybride BIOS+UEFI OK depuis clé flashée (`USB_BOOT_OK`/`USB_UEFI_BOOT_OK`), fix UEFI clé USB (efi.img embarque kernel+initrd+grub.cfg), Secure Boot (shim MS + 12 982 modules signés + MOK), GPG ISO, noyau LTS secours
- Install : Calamares effacer/dual-boot/LUKS, finalize (root lock, sudo, mkinitcpio, grub os-prober)
- Hub central + 13 modules, maj manuelles par défaut (AUTO_UPDATE=0) + liste GUI + historique log, profils par jeu, priorités, benchmark mesuré, pare-feu GUI, diagnostic (+écrans DRM), profils d'apparence, thème GRUB pastèque, générateur d'apps FR, apps natives (notes/minuteur/snake/monitor/games/fortnite), ProtonUp-Qt + gamescope embarqués, recherche globale appmanager, règles udev SSD
- Rapport sprint : `docs/SPRINT_RAPPORT.md`

## En cours / ouvert
- [x] Commit `9a58a4c` : fix boot CD/USB — depmod avant mkinitcpio, add_module par chemin .ko,
  hook runtime avec insmod fallback + attente du medium labellisé (cause racine probable du
  "device did not show up after 30 seconds" vu en boot CD QEMU **et** sur la clé USB réelle de
  l'utilisateur, le test USB n'ayant jamais exercé xhci/usb-storage mais virtio)
- [x] `tests/usb_boot_test.py` passe en vrai contrôleur USB (qemu-xhci + usb-storage) comme une vraie clé
- [x] `tests/live_shell.py` : inspection des modules de l'initramfs (artefact + checks), log serial live
  complet, phase live en `rdinit=/bin/bash` + ISO en disque virtio de secours, boot chargeur avec CD sur
  AHCI explicite ; 19 tests unitaires PASS en local (nouveau: hooks initramfs)
- [ ] Run CI `45692017151` (9a58a4c) en cours — objectif FAILS=0 (boot BIOS/UEFI depuis CD inclus)
- [ ] Run CI suivant : validation boot USB xHCI réel
- [ ] Validation matériel : `docs/POINTS_A_VALIDER_EN_MATERIEL.md` (GPU réel, Fortnite serveurs Epic, SB avec MOK, dual-boot, LUKS, 1440p/240Hz, manettes)
- [x] Diagnostic boot CD QEMU résolu : cause = `ata_piix` absent du initramfs (logs serial lus via artifact `test-logs`) → ajouté au hook `pasteque_mods` (commit `49277ff`). Boot USB (chemin réel Etcher) toujours OK (`USB_BOOT_OK`/`USB_UEFI_BOOT_OK`)
- [x] Run `45613769714` (2801011) VERT : 18/18 unitaires, ISO 5841 MiB, shim+SB embarqués, ETCHER_COMPATIBLE, USB_BOOT_OK+USB_UEFI_BOOT_OK, FAILS=3→0 attendu avec 49277ff (boot CD)
- [ ] Run vert de `49277ff` (fix boot CD) — en cours
- [ ] Validation matériel : `docs/POINTS_A_VALIDER_EN_MATERIEL.md` (GPU réel, Fortnite serveurs Epic, SB avec MOK, dual-boot, LUKS, 1440p/240Hz, manettes)
