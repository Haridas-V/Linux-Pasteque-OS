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

## Tests réalisés en VM (référence)

Voir `tests/artifacts/` : boot de l'ISO en QEMU (TCG) avec log série et
captures d'écran horodatées. Statut actuel : **BOOT_OK** sur la base ISO
(atteinte de la cible multi-user/graphical, `pasteque login:`).
