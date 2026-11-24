# Points à valider en matériel (non testables en VM/sandbox)

Chaque point indique : quoi tester, comment, résultat attendu. Les tests VM
(boot ISO, session SDDM) sont dans `tests/artifacts/` ; tout ce qui suit
nécessite une vraie machine AMD.

| # | Point | Comment tester | Résultat attendu |
|---|---|---|---|
| 1 | Boot UEFI réel (USB/DVD) | Créer la clé USB (`dd` l'ISO), booter en UEFI sur PC AMD | Menu GRUB → session live SDDM Wayland |
| 2 | Boot BIOS réel | Booter en legacy BIOS | Menu isolinux → session live |
| 3 | GPU AMD (RADV/Vulkan/VA-API) | `vulkaninfo --summary`, `vainfo`, jeu Vulkan (ex. via Proton) | RADV détecté, décodage vidéo HW OK |
| 4 | Wayland KDE Plasma 6 | Session live puis installée | Bureau Plasma 6 Wayland fonctionnel, thème sombre Papirus |
| 5 | Calamares : install complète | Depuis la live, lancer l'installateur, 4 écrans, effacer disque | Système installé, boot sur disque, SDDM sans autologin, compte créé |
| 6 | Confirmation effacement disque | Tenter l'install sans cocher la confirmation | Refus explicite, aucun disque touché |
| 7 | Proton-GE par défaut | Steam → installer un jeu Windows, propriétés | Proton-GE proposé/sélectionné, jeu lancé |
| 8 | Heroic (Epic/GOG) | Lancer Heroic, login Epic/GOG | Bibliothèque affichée, jeu téléchargé et lancé |
| 9 | Lutris + Wine-GE | Lutris → runner wine-ge présent | Jeu Windows lancé via Wine-GE |
| 10 | GameMode + MangoHud | Lancer un jeu Steam | Overlay MangoHud visible (FPS), gamemode actif (`gamemoded -s`) |
| 11 | CoreCtrl | Lancer CoreCtrl | GPU AMD détecté, profils applicables |
| 12 | OBS | Capturer l'écran/une fenêtre | Vidéo/enregistrement OK, VA-API dispo |
| 13 | Manette | Brancher une manette (Xbox/PS) | Détectée, Steam Input actif, test dans Steam |
| 14 | App indexer | Placer un .exe dans ~/Jeux et un AppImage dans ~/Applications | Entrées visibles dans le menu KDE + krunner avec icône, lançables |
| 15 | Désinstallation 2 clics | Gestionnaire d'apps → retirer une app | App retirée, résidus nettoyés, système stable |
| 16 | Corbeille rotative | Supprimer un fichier, attendre 5 min, le restaurer | Fichier restauré dans ~/Restaures-pasteque ; taille plafonnée |
| 17 | Update idle + rollback | Forcer `pasteque-update` en pleine session (doit reporter), puis en idle | Report si active ; snapshots Btrfs créés ; rollback testable en cassant volontairement un paquet |
| 18 | Immuabilité | Curseur à 5, reboot | `/usr` en lecture seule (mount | grep /usr → overlay), install de paquet OK via overlay ; retour à 0 possible |
| 19 | Anti-cheat | Installer un jeu listé KO (ex. PUBG) | Avertissement affiché au lancement |
| 20 | Disque externe / 2e SSD | Brancher un SSD USB avec SteamLibrary | Bibliothèque ajoutée automatiquement à Steam |
| 21 | Impression / scanner | Imprimante USB + scanner | Détectés automatiquement (CUPS/sane), test page OK |
| 22 | Audio PipeWire | Casque USB + enceintes HDMI | Son OK, switch automatique, pas de config |
| 23 | Codecs | Lire une vidéo H.264/HEVC/AV1 dans VLC et Firefox (YouTube 4K) | Lecture fluide sans rien installer |
| 24 | Sécurité | `sudo -l` en user, `passwd -S root`, `systemctl status firewalld sshd` | sudo OK pour wheel, root verrouillé, firewalld actif, sshd absent/inactif |
| 25 | Hors-ligne | Couper le réseau, installer depuis l'ISO, utiliser le système | Tout fonctionne sans réseau |

## Tests réalisés en VM (référence) — vérifiés ici, reproductibles

Voir `tests/artifacts/` : boot de l'ISO en QEMU (TCG, sans KVM) avec log série
et captures d'écran horodatées.

| Run | ISO | Résultat | Preuve |
|---|---|---|---|
| `20261121-230859` | base (867 MiB) | **BOOT_OK** — cible multi-user/graphical atteinte, `pasteque login:` | serial.log + result.txt |
| `20261122-031341` | complète (4926 MiB, KDE+gaming+Calamares) | **BOOT_OK** — SDDM démarré, service `pasteque-liveuser` OK, cible graphical atteinte | serial.log (`Started Simple Desktop Display Manager`) + result.txt |
| `20261122-095851` | complète (4976 MiB) | **BOOT BIOS CD OK** + **BOOT UEFI CD OK** (OVMF/pflash → grub → noyau → systemd), sha256 OK, El Torito BIOS+UEFI OK | `serial-bios.log`, `serial-uefi.log`, `report.md` |
| `20261122-0952xx` (manuel) | 4976 MiB | **BOOT UEFI depuis clé USB flashée (dd brut, comme Etcher)** OK — partition MBR 0xEF → grub → noyau → systemd | `/tmp/uefi-usb3.log` ; check `tools/check_isohybrid.py` = ETCHER_COMPATIBLE (MBR 0x55AA, part. bootable 0x17, part. 0xEF) |
| `20261122-123324` | complète (5005 MiB, db pacman embarquée) | **Batterie live 30 PASS / 0 FAIL** en chroot (Calamares 60 modules, sécurité, FR, surcouche anti-frustration : appindexer, corbeille, steamlibs, anti-cheat, extras, unités systemd, btrfs-progs, grub) | `tests/artifacts/20261122-123324-liveonly/live-tests.txt` |
| `20261122-082724` | 4926 MiB | **USB_BOOT_OK** — copie brute de l'ISO sur disque + boot MBR isohybrid (simulation flash Etcher, BIOS) | `tests/artifacts/20261122-082724/` |
| `20261122-182328` | 5005 MiB | **USB_BOOT_OK + USB_UEFI_BOOT_OK** — copie brute (flash Etcher) puis boot BIOS (MBR isohybrid) **et** UEFI (OVMF, partition MBR 0xEF) depuis le disque flashé | `tests/artifacts/20261122-182328/result.txt`, `serial-usb-bios.log`, `serial-usb-uefi.log` |
| `20261122-174330-liveonly` | 5005 MiB | **FAILS=0** — batterie live 30/30 + install sur disque virtuel btrfs (mkinitcpio -P, grub-install i386-pc) + **boot du système installé depuis /dev/vda jusqu'au login** + session sudo | `tests/artifacts/20261122-174330-liveonly/report.md`, `serial-installed.log` |

**Non testé en VM** (émulation TCG sans GPU) : la session Plasma Wayland elle-même
après autologin SDDM → à valider en matériel (point 4 ci-dessus).

## Ajout (jeux en ligne)

- [ ] **Fortnite via Heroic + Proton-GE** : install depuis Epic, EAC doit se lancer (compatible Linux depuis déc. 2022). Vérifier `pasteque-anticheat fortnite` → OK. Non testable en VM (besoin compte Epic + GPU).
- [ ] **Apex Legends / CS2** (Steam, EAC/VAC) : lancement en ligne réel.

- [ ] **Bouton « Mettre à jour maintenant »** (GUI) : pkexec sans mot de passe (règle polkit wheel), snapshot + pacman -Syu + flatpak update.
- [ ] **Tour de bienvenue** affiché une seule fois au 1er boot de la session installée.
- [ ] **Proton-GE par défaut** : lancer un jeu Steam non vérifié → Proton-GE utilisé.
- [ ] **Noyau LTS** : entrée GRUB « noyau LTS de secours » bootable (utile si mise à jour du noyau principal casse).
- [ ] **zram** : `swapon --show` montre /dev/zram0 ; earlyoom actif (`systemctl status earlyoom`).

- [ ] **Dual-boot réel** : installer à côté de Mint/Windows → option « Installer à côté » visible, GRUB liste l'autre OS.
- [ ] **LUKS** : cocher « Chiffrer le système » → boot demande la passphrase (GRUB cryptodisk), système démarre.
- [ ] **KDE Connect** : appairage téléphone Android/iOS.
- [ ] **Blueman** : appairage manette Bluetooth/PS5/DualSense.

- [ ] **Secure Boot** : activer SB dans le BIOS, enrôler la clé MOK (`pasteque-secureboot`), booter la clé → doit passer (sinon « Secure Boot violation » = clé non enrôlée).
- [ ] **Signature ISO** : `tools/verify_iso.sh pasteque-1.0.iso <empreinte>` → OK.
