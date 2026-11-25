# Trace d'avancement — mission évolution majeure (mise à jour continue)

Dernier commit : voir `git log -1`. Dernier run CI vert connu : `487971d7` (+ `224fd35`).

## Fait (avec preuves)
- Phase 0/1 : diagnostic `docs/PHASE0_DIAGNOSTIC.md`, audit `docs/AUDIT_PHASE1.md`, fixes CI (chroot return, sbsigntool, shim version, workflow apostrophe, kdeconnect), 18 tests unitaires PASS en local et CI
- Boot : hybride BIOS+UEFI OK depuis clé flashée (`USB_BOOT_OK`/`USB_UEFI_BOOT_OK`), fix UEFI clé USB (efi.img embarque kernel+initrd+grub.cfg), Secure Boot (shim MS + 12 982 modules signés + MOK), GPG ISO, noyau LTS secours
- Install : Calamares effacer/dual-boot/LUKS, finalize (root lock, sudo, mkinitcpio, grub os-prober)
- Hub central + 13 modules, maj manuelles par défaut (AUTO_UPDATE=0) + liste GUI + historique log, profils par jeu, priorités, benchmark mesuré, pare-feu GUI, diagnostic (+écrans DRM), profils d'apparence, thème GRUB pastèque, générateur d'apps FR, apps natives (notes/minuteur/snake/monitor/games/fortnite), ProtonUp-Qt + gamescope embarqués, recherche globale appmanager, règles udev SSD
- Rapport sprint : `docs/SPRINT_RAPPORT.md`

## En cours / ouvert
- [ ] Diagnostic boot CD en QEMU (boot-bios/uefi-chargeur, live-mount, BOOT_NOT_CONFIRMED) — logs dispos via artifact `test-logs` du prochain run vert ; boot USB (chemin réel Etcher) OK
- [ ] Run CI vert final avec toutes les features (en cours : fc320f2 puis 326d93d)
- [ ] Validation matériel : `docs/POINTS_A_VALIDER_EN_MATERIEL.md` (GPU réel, Fortnite serveurs Epic, SB avec MOK, dual-boot, LUKS, 1440p/240Hz, manettes)
