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
  (testé en local) ; phase live avec label bidon PASTEQUE-TEST-NOMOUNT (label bidon volontaire de la phase shell-live du harnais ; les vrais boots passent par les tests boot-*-chargeur avec le label reel PASTEQUE) pour garder le shell archiso
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

## Tour de corrections "audit GPT test-logs" (commit suivant)

- **Signature modules Secure Boot réécrite au format exact de scripts/sign-file** :
  magic EN DERNIER, header algo=0/hash=0/id=2, CMS detached NOCERTS NOATTR, hash lu
  dans IKCONFIG du noyau (sha512 sur Arch). Les modules Arch étant DEJA signés (sig
  interne au .ko compressé), l'ancienne signature est strippée, le module décompressé
  en .ko puis re-signé — sinon kmod/depmod échouait ("zstd: Src size is incorrect",
  les 959 erreurs du run 45817953651) et le noyau rejetait la double signature.
  Preuve locale : round-trip .ko.gz -> .ko signé, `openssl cms -verify` OK, depmod sans erreur.
- step_secureboot STRICT : shim/MokManager manquants ou signature incomplète = build en échec.
- Ordre des étapes : secureboot AVANT initramfs (l'initramfs embarque les modules signés).
- Nouveau test REEL `tests/sb_boot_test.py` : OVMF secboot + cle Pastèque en db via
  virt-fw-vars -> boot OK attendu ; contrôle négatif sans la cle -> boot bloqué.
- Workflow : plus de `set +e`, uploads en `if: always()`, sha256/signé avant les tests,
  4 suites de tests obligatoires (vm, usb, live, sb).
- `SigLevel = Never` supprimé (build) : `Required DatabaseOptional` + pacman-key populate.
- depmod au build en loud (work/depmod-build.log, fatal si erreurs) ; mkinitcpio principal patché (/dev/fd).
- finalize-install : mkinitcpio -P / grub-mkconfig / pacman-key en fatals + preset linux-lts.
- Hook pasteque_mods : version noyau via `uname -r`. Label de test renommé NOMOUNT_LABEL.
- SECURE_BOOT.md : procédure MOK corrigée (boot SB off -> mokutil --import -> SB on -> MokManager).

## Mission prioritaire — audit et fiabilisation totale (2026-11-26, session en cours)

Audit domaine par domaine (10 domaines du brief, faits manuellement — aucun sous-agent
déployable dans le bac à sable : pas de clé API Mistral disponible, déclaré honnêtement
dans le rapport final) :

- **Bug trouvé en relecture avant CI** : `tests/sb_boot_test.py` appelait
  `wait_sock(sock, proc, timeout=60)` alors que la signature n'acceptait que `tries=`
  → TypeError en CI. Corrigé : `wait_sock(path, proc, tries=40, timeout=None)` +
  test de non-régression qui scanne TOUS les appels `wait_sock(...)` de tests/.
- **sb_boot_test.py renforcé** : scan de l'historique serial COMPLET (marqueurs coupés
  entre deux lectures), double marqueur SB (`secureboot: Secure boot enabled` /
  `Kernel is locked down from EFI Secure Boot` — chaînes vérifiées contre de vrais dmesg).
- **Aucun `|| true` restant sur commandes critiques** : `pasteque-finalize-install`
  (root verrouillé, firewalld, sddm, locale-gen FR, services/timers pasteque),
  `pasteque-liveuser`, `tools/sign_iso.sh` (échec sha256 ou import clé GPG CI = exit 1,
  plus de faux succès) rendus fatals. `os-prober` : avertissement explicite non silencieux
  (retour non nul légitime quand aucun autre OS). `pasteque-secureboot` : DER/FINGERPRINT
  absents = message d'erreur au lieu de silence.
- **Build strict** (`tools/build_sandbox.py`) : `locale-gen` fatal dans la live,
  vérification explicite que sshd est bien désactivé (masqué + plus de *.wants),
  logo/fonds d'écran vérifiés présents (fatal sinon), `chmod +x /usr/local/bin/*` fatal,
  sudoers.d wheel chmod 440 forcé (git ne stocke que 644/755).
- **Faux positif de test supprimé** : le test live `sudoers-wheel` s'auto-mutait
  (`|| echo ... > /etc/sudoers.d/...`) pour passer. Fichier ajouté à l'overlay
  (`profile/airootfs/etc/sudoers.d/010-pasteque-wheel`), test rendu 100% pur
  (existe + bonne règle + mode 440), + test de non-régression anti auto-mutation
  sur toute la batterie live.
- **Trio anti-cheat durci** : `PASTEQUE_ANTICHEAT_DB` overridable (testable),
  `pasteque-anticheat-setlaunch` : usage/mode/fichier vérifiés (exit 2/1 propre au lieu
  d'un IndexError), `pasteque-anticheat-warn` : DB illisible = erreur explicite.
- **Tests unitaires : 39/39 PASS** (nouveaux tests de non-régression inclus).
- CI : runs en cours à chaque push (workflow strict `set -e`, 4 suites obligatoires :
  vm, usb, live, **sb_boot_test OVMF réel positif+négatif**). Résultats dans le rapport final.

## Saga test Secure Boot réel (OVMF secboot) — diagnostic étape par étape

Chaque cause a été reproduite/prouvée avant correction (jamais de correction à l'aveugle) :

1. `wait_sock(..., timeout=60)` appelé avec un kwarg inexistant → TypeError.
   Corrigé (`timeout=` accepté) + test de non-régression sur tous les appels.
2. `virt-fw-vars --add-db` exige **GUID FILE** (nargs=2, source Debian 24.11 lue) et
   le varstore par défaut (`OVMF_VARS_4M.fd`) est **SB OFF / setup mode** → test vide.
   Corrigé : template `OVMF_VARS_4M.ms.fd` (clés MS + SB on), `--secure-boot` explicite,
   `--add-db <GUID db> <der>`, repli `--enroll-redhat` sur varstore vierge, et
   **re-lecture du varstore** (`--print --verbose`) qui exige `SecureBootEnable: ON`
   (et la présence du CN `Pasteque Linux Secure Boot` dans db pour le positif).
   Validé EN LOCAL avec les vrais fds OVMF (dépot deb ovmf trixie) + virt-fw-vars :
   positif OK, négatif OK (clé absente), repli OK, anti-vacuité OK (varstore sans SB refusé).
3. Sans `-L <datadir qemu>`, QEMU crée le socket serial puis **meurt** (rc=1,
   roms `kvmvapic.bin`/`efi-virtio.rom` introuvables — reproduit en local, le conteneur
   CI n'a pas /usr/share/qemu) → `RuntimeError: socket indisponible`. Corrigé : `-L`
   + capture du stderr QEMU dans un fichier + `wait_sock` vérifie le process d'abord.
4. OVMF secboot exige `-machine q35,smm=on` + pflash `secure=on` (docs Debian/libvirt) — ajouté.
5. Boot CD (`-cdrom`) sous OVMF **secboot** : `BdsDxe: failed to load Boot0001 "UEFI QEMU
   DVD-ROM..." : ...` côté firmware, alors que le même ISO boote en CD avec SB OFF
   (batterie live verte) et en disque raw (usb_boot_test vert). Non résolu à la source
   (probablement lié à l'image El Torito 1 GiB sous vérification SB) → le test SB boote
   désormais l'ISO en **disque raw** (partition MBR 0xEF, exactement ce qu'Etcher écrit
   sur une clé USB). Le boot CD reste couvert sans SB par `tests/live_shell.py`.
   → à valider en CI (run e0119c5) ; si le positif atteint le login avec
   `secureboot: Secure boot enabled` et aucun `module verification failed`, et si le
   négatif (sans la clé) est bloqué, le test SB est prouvé de bout en bout.

## Round correctif Secure Boot — cause racine « bad shim signature » (reproduit en local, preuve dure)

Symptôme (run CI 45950999610 + boot OVMF local, screendump) : le menu GRUB s'affiche (shim→grub OK)
puis `Booting 'Pasteque Linux (live)'` → `error: bad shim signature` → retour au menu.

Cause racine (2 bugs composés, prouvés avec sbverify sur l'ISO locale) :
1. `sb_sign.py` signait `/boot/vmlinuz-linux` — un **symlink** créé par l'étape initramfs qui tourne
   **après** l'étape secureboot dans `all` : sur un build frais le fichier n'existe pas encore,
   la boucle `if os.path.exists(k)` sautait **silencieusement** → aucun noyau signé.
   `sbverify --list work/iso/boot/x86_64/vmlinuz-linux` → « No signature table present ».
2. `step_iso` copie le noyau de l'ISO depuis `usr/lib/modules/<kver>/vmlinuz` — jamais signé.

Corrections :
- `tools/sb_sign.py` : nouvelle fonction `kernel_targets(rootfs)` (realpath + déduplication) ;
  les noyaux sont signés **in place sur le chemin réel** `usr/lib/modules/<kver>/vmlinuz` ;
  **exit 1 si aucun noyau trouvé** ; re-lecture stricte (table de certificats PE via `pe_signed`)
  après chaque signature. Le glob des modules couvre désormais `usr/lib/modules/*/**/*.ko*`
  (kernel/ + updates/ + extra/ — les .ko.zst restants provoquaient des erreurs depmod dans la cible installée).
- `tools/build_sandbox.py` : `require_signed_iso_kernel()` — si la chaîne SB est active (shim présent),
  le noyau embarqué dans l'ISO (et copié dans l'ESP) DOIT être signé et vérifié `sbverify --cert work/sb/sb.crt`,
  sinon **le build échoue** (jamais de boot SB annoncé avec un composant non signé).
- Preuve locale : `sbverify --cert work/sb/sb.crt` OK sur vmlinuz-linux **et** vmlinuz-lts extraits de l'ISO
  et sur le noyau de l'ESP (efi.img) ; BOOTX64.EFI = shim signé Microsoft ; grubx64.efi signé clé Pastèque.
- Marqueur honnête : `pasteque-liveuser` imprime `PASTEQUE-SECUREBOOT: <0|1>` sur /dev/console
  (lu depuis `/sys/kernel/security/secureboot`) — les 1ers messages noyau partent avant la console série ;
  `tests/sb_boot_test.py` attend ce marqueur (grâce 180 s) et le compte comme preuve SB active.
- `pasteque-finalize-install` : `depmod -a` en **fatal** avant `mkinitcpio -P` (index kmod périmé
  après renommage .ko.zst → .ko signés).
- `docs/SECURE_BOOT.md` : procédure MOK corrigée (MokList/GUID shim, lancement direct de mmx64.efi)
  + section « tests automatisés » qui distingue validation QEMU/OVMF réelle vs validation matérielle.
- Tests unitaires : 42 PASS (nouveaux : chemins réels des noyaux + guard ISO + marqueur console + depmod fatal).
- Validation locale en cours : `sb_boot_test.py` sur l'ISO rebuildée localement (noyau signé vérifié dans ISO+ESP,
  marqueur présent dans l'airootfs.sfs) → boot OVMF secboot positif attendu jusqu'au système live avec
  `PASTEQUE-SECUREBOOT: 1`, négatif bloqué par le shim.

Mise a jour apres debug OVMF secboot reel (boot -kernel init=/bin/bash, /sys monte) :
le fichier /sys/kernel/security/secureboot N'EXISTE PAS dans le noyau Arch 7.3.6
(monte pourtant) -> le marqueur securityfs donnait 'unknown'. Preuve fiable :
l'efivar EFI `SecureBoot-8be4df61-...` lu avec `od -An -tu1 -j4 -N1` -> **1** sous OVMF
secboot avec la cle enrolee (lockdown: [none] integrity confidentiality). Le marqueur
PASTEQUE-SECUREBOOT utilise desormais securityfs d'abord, puis l'efivar EFI en repli
(montage efivarfs tente si besoin). Valide en local: od -> 1.

## Résultats de validation locale (après corrections, ISO rebuildée en local 4750 MiB)

- `sbverify --cert work/sb/sb.crt` OK sur vmlinuz-linux ET vmlinuz-lts extraits de l'ISO,
  et sur le noyau embarqué dans l'ESP (efi.img) ; BOOTX64.EFI = shim signé Microsoft ;
  grubx64.efi = signé clé Pastèque. Le garde `require_signed_iso_kernel` a tourné au build.
- `tests/sb_boot_test.py` en local (QEMU TCG + OVMF secboot réel, varstores vérifiés SB-on) :
  **`RESULT: SB_POSITIVE_OK SB_NEGATIVE_OK`** — positif : boot jusqu'au système live
  (LOGIN_OK) avec `PASTEQUE-SECUREBOOT: 1` sur la console série et AUCUN
  `module verification failed` ; négatif (clé absente) : boot bloqué par le shim.
- Preuve noyau du marqueur (boot -kernel init=/bin/bash sous OVMF secboot, /sys monté) :
  efivar `SecureBoot-8be4df61-...` lu via `od -An -tu1 -j4 -N1` -> **1** ;
  `/sys/kernel/security/secureboot` n'existe pas dans le noyau Arch 7.3.6 (d'où le repli efivar) ;
  lockdown = `[none] integrity confidentiality`.
- 43 tests unitaires PASS en local (nouveau : `fetch_url_retry` fonctionnel avec serveur
  HTTP local — succès après 2×503, échec franc si indisponible).
- Run CI 45995052877 : échec **transitoire** (HTTP 503 codeberg au fetch du tarball
  Calamares, étape AUR) -> corrigé par `fetch_url_retry` (commit e1b9692). Run suivant : 46000041335.

## Run CI vert 46000641720 (e692abe) — TOUT PASS
- 43 tests unitaires PASS en CI ; build docker trixie : noyaux ISO verifies signes (vmlinuz-linux + vmlinuz-lts, garde require_signed_iso_kernel), 12982/12982 modules signes, ISO 5817 MiB, ETCHER_COMPATIBLE
- [vm] BOOT_OK ; USB_BOOT_OK + USB_UEFI_BOOT_OK ; live PASS=55 FAIL=0 (FAILS=0) ; install VM OK (finalize+grub, depmod propre, boot disque installe, sudo gamer)
- sb_boot_test: POSITIF LOGIN_OK secureboot_enabled=True (PASTEQUE-SECUREBOOT: 1 en serie) module_verification_failed=False ; NEGATIF bloque par le shim -> SB_POSITIVE_OK SB_NEGATIVE_OK
- Run 46000041335 (e1b9692) : SUCCESS aussi. Run 45995052877 : failure = 503 transitoire codeberg -> netutil retry (fix).
- Correctif supplementaire apres lecture des artefacts : /boot exclu du squashfs -> finalize-install recree /boot/vmlinuz-linux et /boot/vmlinuz-lts dans la cible (sinon mkinitcpio -P echoue en install reelle) + 2 checks live stricts (install-finalize-sans-erreur, install-boot-noyaux-et-initramfs-presents).
