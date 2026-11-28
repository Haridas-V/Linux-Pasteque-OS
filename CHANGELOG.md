# CHANGELOG — Pastèque Linux

## v1.0 — évolution majeure (mission 72h)

- **Gestionnaire Pastèque central** (`pasteque-hub`, 13 modules) ; **mises à jour 100 % manuelles** par défaut (liste consultable, install au clic, snapshot auto)
- **Profils par jeu** (pasteque-games : env, GameMode, MangoHud, nice → appliqués au lancement)
- ⚡ **Gestionnaire de priorités** (`pasteque-priorites`, nice par processus, jamais de RT arbitraire)
- 🧪 **Benchmark** (`pasteque-benchmark` : CPU/RAM/disque mesurés, GPU vkcube si dispo, historique JSON + export)
- 🛡️ **Pare-feu graphique** (`pasteque-parefeu`, firewalld) ; 🔍 **Diagnostic** (`pasteque-diagnostic`, rapport .md exportable, SMART)
- 🎨 Personnalisation : **profils d'apparence** (Sober/Gaming/Clair/Minimal + sauvegarde perso JSON)
- 🍉 **Thème GRUB Pastèque** (logo pastèque généré en pure Python au build)
- 🎮 Gaming : **gamescope** + **ProtonUp-Qt embarqué** (hors-ligne) ; Bottles via Flatpak (doc)
- App manager : **recherche globale pacman + Flatpak** avec sources
- 18 tests unitaires (tous PASS) + nouveaux checks live

## v1.0 (en cours de build CI)

### Sprint apps / générateur / custom (phases 2-4)
- Apps natives testées (--smoke headless) : notes rapides, minuteur+notification, **snake avec record sauvegardé**, monitoring CPU/RAM/disque/temp stylé, lanceur de jeux
- **Générateur d'apps piloté en français** (`pasteque-genere "fais-moi une app qui…"`) : génère une app PyQt6 complète (fenêtre, logique, sauvegarde JSON, entrée menu, --smoke), code lisible/modifiable ; démo intégrée (`--smoke`)
- **Panneau 🎨 Personnalisation** : thème, accent, fonds d'écran (3 PNG générés au build, pure Python), disposition panneau, police — via plasma-apply-*/kwriteconfig5 uniquement
- Tests unitaires 13/13 (générateur, wallpapers, personnalisation dry-run en plus des 10 existants)

### Build / boot
- ISO hybride isohybrid (BIOS + UEFI), compatible balenaEtcher (`ETCHER_COMPATIBLE`, `USB_BOOT_OK`, `USB_UEFI_BOOT_OK`)
- Fix boot UEFI depuis clé USB : kernel+initrd+grub.cfg embarqués dans l'efi.img (1 Go)
- **Secure Boot** : shim signé Microsoft + GRUB/noyaux/modules signés (clé MOK embarquée, enrôlement via `pasteque-secureboot`), MokManager embarqué
- **Signature GPG** de l'ISO (`.asc`) + SHA256, outils `tools/sign_iso.sh` / `tools/verify_iso.sh`, secrets CI optionnels
- Noyau **LTS de secours** (2e entrée GRUB/isolinux)
- Build résilient : un paquet renommé/inconnu ne casse plus le build (retry avec filtrage)

### Installateur (Calamares)
- 4 écrans, effacer le disque (confirmation explicite) **ou « Installer à côté » (dual-boot, os-prober)**
- **Chiffrement LUKS** en 1 case (hook `encrypt` + `GRUB_ENABLE_CRYPTODISK` auto)
- finalize : root verrouillé, sudo wheel, pare-feu, pas d'autologin, mkinitcpio -P, extras installés

### Système / no-frustration
- **Mise à jour système en GUI** (bouton « Mettre à jour maintenant », pkexec sans mdp via polkit wheel, statut + snapshots)
- Mises à jour auto au repos, snapshots Btrfs pre/post + rollback auto, corbeille de sauvegarde taille-plafond
- Indexation auto .exe/AppImages (menu KDE + krunner, icônes), gestionnaire d'apps (désinstall 2 clics + résidus)
- **Lanceur de jeux `pasteque-games`** (Steam + jeux locaux indexés, statut anti-cheat, double-clic lance)
- **Tour de bienvenue** au 1er boot ; Proton-GE par défaut pour tous les jeux Steam (1 clic)
- zram + earlyoom (anti-freeze) ; immuabilité /usr réglable 0–5 ; pare-feu ; SSH off ; non-root

### Jeux en ligne
- Fortnite OK via Heroic + Proton-GE (EAC Linux) ; `pasteque-anticheat <jeu>` ; db anti-cheat embarquée (Steam appids + jeux Epic)
- Proton-GE, Wine-GE, Heroic, Teams embarqués hors-ligne (`/opt/pasteque/extras`)

### Apps embarquées (sélection)
KDE Plasma 6 Wayland, Firefox, Thunderbird, LibreOffice FR, Steam, Lutris, Heroic, OBS, VLC/Elisa, Kdenlive/GIMP/Krita/Audacity, codecs complets, Flatpak/Discover, CUPS/SANE, + mpv, strawberry, qbittorrent, keepassxc, veracrypt, warpinator, signal-desktop, gparted, simple-scan, kate, kolourpaint, kdeconnect, blueman, flameshot, gnome-disks, GameMode, MangoHud, CoreCtrl

### Tests
- Unitaires sans root (`tests/test_units.py`, exécutés en CI avant le build) : syntaxe scripts, format signature modules CMS, sign/verify GPG, anti-cheat, lanceur, workflow CI, config Calamares
- VM QEMU : boot BIOS/UEFI CD, boot BIOS/UEFI depuis disque flashé (simulation Etcher), batterie live (~40 checks), install sur disque virtuel btrfs + boot du système installé
- Sous-agents Mistral (`agents/`) : orchestrateur + 4 sub-agents, test local scripté PASS

### Docs
`README.md`, `docs/ARCHITECTURE.md`, `docs/MAINTENANCE.md`, `docs/JEUX_EN_LIGNE.md`, `docs/SECURE_BOOT.md`, `docs/POINTS_A_VALIDER_EN_MATERIEL.md`, `agents/README.md`
