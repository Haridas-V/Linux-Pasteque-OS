# Rapport de sprint 72h — Pastèque Linux v1.0

## Phase 0 — Diagnostic (`docs/PHASE0_DIAGNOSTIC.md`)
Bilan honnête fait avant tout code : ce qui marche (build rootless, tests VM, CI), ce qui cassait (5 causes racines de FAIL CI, toutes corrigées), le code mort (supprimé), les faux positifs (liens systemd). Historique CI complet analysé.

## Phase 1 — Stabilisation
- Fix crash CI : `chroot()` retourne le `CompletedProcess` ; build résilient (retry auto si paquet renommé)
- Micro-bugs corrigés : comparaison chaînée morte (`pasteque-bootcheck`), `is False` (`pasteque-steamlibs`), nom paquet `kdeconnect`, apostrophe cassant le `bash -c` du workflow (garde-fou : test unitaire `bash -n`)
- Dépendances verrouillées : `mistralai-agents==1.1.3` ; parité `build.sh` documentée ; code mort supprimé
- **14 tests unitaires** exécutés en CI avant chaque build (`tests/test_units.py`) — tous PASS
- Non-régression : run CI vert `487971d7` — build + `ETCHER_COMPATIBLE` + `USB_BOOT_OK` + `USB_UEFI_BOOT_OK` + install disque virtuel + boot système installé

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

## État CI
Dernier run vert : `487971d7` (et `91e37fb` en cours avec les derniers fix de tests). Commandes :
```bash
gh run list --repo Haridas-V/Linux-Pasteque-OS --limit 1
gh run download <ID> -n pasteque-iso     # ISO + sha256 (+ .asc si signé)
gh run download <ID> -n test-logs        # logs VM détaillés
```

## Reste à valider en matériel (pas testable en VM sans GPU/SB)
`docs/POINTS_A_VALIDER_EN_MATERIEL.md` — session Plasma réelle, Fortnite/EAC en ligne, Secure Boot avec MOK enrôlé, dual-boot, LUKS, manettes BT, perfs, etc.
