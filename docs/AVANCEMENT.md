# Trace d'avancement — mission évolution majeure (mise à jour continue)

Dernier commit : voir `git log -1`. Dernier run CI vert connu : `45730337362` (d2e1176). Run en cours : `45740640989` (97ba030).

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
- [x] **CAUSE RACINE boot CD/USB trouvée et prouvée en local** : l'initramfs était construite
  pour le noyau LTS (6.18.65) alors que l'ISO embarque le noyau 7.3.6 (`ls | head -1` triait le LTS
  en premier) → au boot `modprobe: FATAL: Module sr_mod not found in directory /lib/modules/7.3.6-arch1-1`
  → pas de sr0 → archiso « device did not show up after 30 seconds ». Preuve : boot local du noyau LTS
  6.18.65 + cette initramfs + CD → « Device '/dev/disk/by-label/PASTEQUE' mounted successfully »
  (artefact /tmp/ser-lts.txt). Fix : sélection explicite du noyau non-LTS + `verify_initramfs()`
  au build (échoue le build si modules != noyau de l'ISO) + `depmod -a` avant mkinitcpio
- [x] `add_module` par chemin .ko = erreur mkinitcpio (exit 1) → retour à `add_module` par nom
- [x] `rdinit=/bin/bash` fait paniquer le noyau (« Unable to mount root fs ») → on garde `init=`
  (testé en local) ; phase live avec label bidon PASTEQUEZZZ pour garder le shell archiso
- [x] Runs intermédiaires résolus (voir ci-dessous)
- [x] Run `45714194999` (f470906) **VERT** : ETCHER_COMPATIBLE, BOOT_OK, **USB_BOOT_OK + USB_UEFI_BOOT_OK
  via vrai xHCI+usb-storage**, boot-bios-chargeur PASS, boot-uefi-chargeur PASS (CD), live-mount PASS,
  install btrfs + boot disque installé + sudo PASS, 84 PASS / 3 FAIL (les 3 = bugs de TEST, pas du produit :
  $a non échappé sous set -u qui tronquait la batterie live, paquet kdeconnect-kde renommé, xhci-hcd builtin)
- [x] Commit `c11be60` : ces 3 bugs de test corrigés + test unitaire anti-« unbound variable » (20 tests PASS)
- [x] Run `45730337362` (d2e1176) VERT mais FAILS=7 : la batterie live, desormais non tronquee,
  a trouve de vrais bugs produit : 5 scripts en mode 644 (Permission denied), crash lire_cpu()
  de pasteque-monitor a la 1ere lecture, 2e bug set -u ligne 129 (scripts-audit)
- [x] Commit `97ba030` : chmod +x (git 100755) + filet de securite chmod au build + test unitaire
  « tous les pasteque-* en 755 » ; fix lire_cpu (1ere lecture) ; quoting scripts-audit ; util-apps
  diagnostique ; regex du test anti-unbound encore plus strict (21 tests unitaires PASS en local)
- [x] Run `45740640989` (97ba030) VERT, FAILS=1 (gamescope-test, ligne masquée par `>/dev/null` mal placé)
- [x] Run `45753207300` (befce01) VERT, FAILS=3 : cause = GPGDir `/etc/pacman.d/gnupg/` absent de la squashfs
  -> pacman -Q échouait (rc=1) dans le système live (prouvé en local : AVANT=1, APRES OK après mkdir).
  Fix : dir ajouté à l'overlay + makedirs au build. + inversion `exit $ok` -> `exit $bad` dans 2 tests
- [x] **Run `45765266229` (4b7d18d) VERT — FAILS=0** 🎉 : 22 tests unitaires, ETCHER_COMPATIBLE, BOOT_OK,
  USB_BOOT_OK + USB_UEFI_BOOT_OK (vrai xHCI), boot-bios-chargeur + boot-uefi-chargeur (CD), live-mount,
  batterie live **PASS=55 FAIL=0**, install btrfs + boot disque installé + sudo, rapport **101 PASS / 0 FAIL**.
  ISO 5893 MiB (~5,8 Go), run total 1h36 (06:00:41 → 07:37:08)
- [ ] Validation matériel : `docs/POINTS_A_VALIDER_EN_MATERIEL.md` (GPU réel, Fortnite serveurs Epic, SB avec MOK, dual-boot, LUKS, 1440p/240Hz, manettes)
- [x] Diagnostic boot CD QEMU résolu : cause = `ata_piix` absent du initramfs (logs serial lus via artifact `test-logs`) → ajouté au hook `pasteque_mods` (commit `49277ff`). Boot USB (chemin réel Etcher) toujours OK (`USB_BOOT_OK`/`USB_UEFI_BOOT_OK`)
- [x] Run `45613769714` (2801011) VERT : 18/18 unitaires, ISO 5841 MiB, shim+SB embarqués, ETCHER_COMPATIBLE, USB_BOOT_OK+USB_UEFI_BOOT_OK, FAILS=3→0 attendu avec 49277ff (boot CD)
- [x] Fix boot CD validé par les runs 45714194999 et suivants
- [ ] Validation matériel : `docs/POINTS_A_VALIDER_EN_MATERIEL.md` (GPU réel, Fortnite serveurs Epic, SB avec MOK, dual-boot, LUKS, 1440p/240Hz, manettes)
