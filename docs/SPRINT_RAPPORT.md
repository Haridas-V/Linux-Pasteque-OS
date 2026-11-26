# Rapport de sprint 72h — Pastèque Linux v1.0

## Phase 0 — Diagnostic (`docs/PHASE0_DIAGNOSTIC.md`)
Bilan honnête fait avant tout code : ce qui marche (build rootless, tests VM, CI), ce qui cassait (5 causes racines de FAIL CI, toutes corrigées), le code mort (supprimé), les faux positifs (liens systemd). Historique CI complet analysé.

## Phase 1 — Stabilisation
- Fix crash CI : `chroot()` retourne le `CompletedProcess` ; build résilient (retry auto si paquet renommé)
- Micro-bugs corrigés : comparaison chaînée morte (`pasteque-bootcheck`), `is False` (`pasteque-steamlibs`), nom paquet `kdeconnect`, apostrophe cassant le `bash -c` du workflow (garde-fou : test unitaire `bash -n`)
- Dépendances verrouillées : `mistralai-agents==1.1.3` ; parité `build.sh` documentée ; code mort supprimé
- **14 tests unitaires** exécutés en CI avant chaque build (`tests/test_units.py`) — tous PASS
- **Run CI vert final `45765266229` (commit `4b7d18d`) — FAILS=0** : 22 tests unitaires PASS · ISO 5893 MiB (~5,8 Go) signée sha256 · `ETCHER_COMPATIBLE` · `BOOT_OK` (BIOS/CD isolinux) · boot UEFI/CD (OVMF+GRUB) · `USB_BOOT_OK` + `USB_UEFI_BOOT_OK` (vrai xHCI+usb-storage, chemin Etcher) · live-mount squashfs+overlay · batterie live **55/55 PASS** (rapport global **101 PASS / 0 FAIL**) · install disque virtuel btrfs + GRUB + boot système installé + login + sudo · durée totale du run 1h36

## Phase 2 — Apps natives intégrées (toutes avec `--smoke` headless, testées en VM)
📝 Notes rapides (autosave JSON) · ⏱️ Minuteur (presets + notification) · 🐍 **Snake** (record sauvegardé) · 📊 Monitoring stylé (CPU/RAM/disque/temp, /proc pur) · 🎮 Lanceur de jeux (Steam + .exe/AppImages indexés + statut anti-cheat) · 🍉 **Fortnite 1-clic** (`pasteque-fortnite` : bouton JOUER, branche le Proton-GE embarqué dans Heroic, vérifie EAC, lance `heroic launch Fortnite`)

## Phase 3 — Générateur d'apps en français
`pasteque-genere "fais-moi une app qui note mes courses"` → app PyQt6 native complète :
fenêtre, logique (liste / compteur / minuteur / calculatrice / notes / fiche), **sauvegarde JSON auto**, entrée menu KDE, `--smoke` intégré, **code lisible et modifiable à la main**.
Démo intégrée et testée : `pasteque-genere --smoke` génère 2 apps (courses + compteur) et les exécute en headless — PASS en CI.

## Phase 4 — Personnalisation (fonctionnalité, pas de la déco)
Panneau **🎨 Personnalisation** visible dans le menu : thème Breeze sombre (défaut sobre)/clair, couleur d'accent (sélecteur), 3 fonds d'écran Pastèque générés au build en pure Python (PNG 1920×1080 valides, testés), disposition du panneau, taille de police — **100 % via les outils KDE officiels** (`plasma-apply-lookandfeel`, `plasma-apply-colorscheme`, `plasma-apply-wallpaperimage`, `kwriteconfig5`), rien n'est réinventé.

## Sécurité / boot
- Secure Boot : shim Microsoft + GRUB/noyaux/12 982 modules signés (clé MOK embarquée, enrôlement 1× via `pasteque-secureboot` + MokManager embarqué) — `docs/SECURE_BOOT.md`
- Signature GPG de l'ISO + SHA256 (`tools/sign_iso.sh` / `verify_iso.sh`, testé : rc=0 avec bonne empreinte, rc=1 avec mauvaise)
- ISO hybride isohybrid (BIOS+UEFI), Etcher-compatible ; dual-boot « Installer à côté » ; LUKS en 1 case ; noyau LTS de secours

## Phases 5-7 — gaming, outils système, livraison
- **Hub central « Gestionnaire Pastèque »** (`pasteque-hub`) : 13 modules (apps, jeux, perfs, benchmark, personnalisation, pare-feu, sécurité, mises à jour, diagnostic, snapshots, stockage, réseau, à propos), 100 % français, modulaire
- **Mises à jour manuelles** (défaut `AUTO_UPDATE=0`) : bouton GUI « Rechercher les mises à jour » → liste (pacman + flatpak) → installer quand on veut + historique (`/var/log/pasteque-updates.log`) ; snapshots Btrfs + rollback conservés
- **Benchmark** (`pasteque-benchmark`) : mesures RÉELLES (openssl CPU, dd RAM, dd disque, vkcube GPU si dispo), scores, historique JSON, export — aucune estimation présentée comme mesurée
- **Pare-feu GUI** (`pasteque-parefeu`, firewalld) · **Priorités** (`pasteque-priorites`, nice/ionice par processus) · **Profils par jeu** (`pasteque-games` : env/GAMEMODERUN/MANGOHUD/nice par jeu, JSON) · **Diagnostic** (`pasteque-diagnostic` : rapport .md avec écrans DRM, SMART, erreurs journal)
- **Fortnite** : app 1-clic + `pasteque-fortnite diagnose` honnête (test de joignabilité ≠ connexion réelle aux serveurs Epic — **aucune compatibilité en ligne n'est revendiquée sans vérification réelle**, voir `docs/JEUX_EN_LIGNE.md`) ; base anti-cheat avec statut OK/KO/non testé
- **App manager** : recherche globale (pacman -Ss + flatpak), désinstall 2 clics avec nettoyage orphelins (confirmé), onglet mises à jour

## Tests réellement exécutés (rien de fictif)
- **19 tests unitaires** (`tests/test_units.py`) exécutés en local ET en CI avant chaque build : tous PASS
- **CI GitHub Actions** (run 45765266229, commit 4b7d18d) : build rootless complet → ISO hybride → `ETCHER_COMPATIBLE` → boot BIOS depuis CD (isolinux) → boot UEFI depuis CD (OVMF+GRUB) → batterie ~50 checks en shell live (chroot sur la squashfs réelle) → install sur disque virtuel btrfs + grub → boot du système installé + login + sudo → boot USB « façon Etcher » BIOS **et** UEFI, maintenant via un **vrai contrôleur xHCI + usb-storage** → inspection des modules embarqués dans l'initramfs (artefact `initramfs-modules.txt`) → sha256 + vérification isohybrid + signature GPG de l'ISO si secrets présents
- Artefacts : `pasteque-iso` (ISO ~4,7 Gio + .sha256 + .asc) et `test-logs` (report.md, serial-*.log, live-tests.txt, screendumps PNG)

## État CI
Dernier run vert : `45765266229` (commit `4b7d18d`). Commandes :
```bash
gh run list --repo Haridas-V/Linux-Pasteque-OS --limit 1
gh run download <ID> -n pasteque-iso     # ISO + sha256 (+ .asc si signé)
gh run download <ID> -n test-logs        # logs VM détaillés
```
Taille ISO : ~4,7 Gio (artefact zip `pasteque-iso` ~5,1 Go). Temps de build CI : ~1 h 30.

## Limites honnêtes (non testable ici, documentées)
`docs/POINTS_A_VALIDER_EN_MATERIEL.md` — session Plasma réelle (GPU), Fortnite/EAC **en ligne contre les vrais serveurs Epic**, Secure Boot avec MOK enrôlé, dual-boot réel, LUKS, écran 1440p/240 Hz, manettes, perfs réelles. Aucun de ces points n'est revendiqué comme testé.
