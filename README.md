# 🍉 Pastèque Linux — édition « No Frustration »

Distribution Linux **installable (ISO complète)**, dérivée d'Arch Linux, orientée
**gaming + usage quotidien**, pensée pour être installée **une seule fois** et ne
plus jamais nécessiter de terminal.

- **Base** : Arch Linux (dépôts officiels + AUR préconfiguré), 100 % hors-ligne après installation.
- **GPU** : stack AMD complète (Mesa RADV, Vulkan, VA-API). Pas de pilotes propriétaires NVIDIA.
- **Session** : KDE Plasma 6 sous Wayland, préconfigurée (thème sombre, polices, icônes).
- **Installateur** : Calamares, 4 écrans, français, clavier détecté automatiquement, effacement du disque avec confirmation explicite.
- **Mises à jour** : silencieuses, uniquement quand la machine est au repos, avec snapshots Btrfs et rollback automatique.
- **Surcouche anti-frustration** : indexation auto des .exe/AppImages dans le menu KDE, gestionnaire d'applications unique (retrait en 2 clics), corbeille de sauvegarde rotative, anti-cheat, bibliothèques Steam sur disques externes auto-détectées.

## Build de l'ISO (une commande)

Sur un hôte Arch (ou automatiquement via Docker) :

```bash
sudo ./build.sh        # -> out/pasteque-*.iso
```

Sans root (sandbox / CI), le même résultat est produit par :

```bash
python3 tools/build_sandbox.py all   # -> out/pasteque-*.iso + .sha256
```

## Tests en VM (QEMU, sans KVM accepté)

```bash
python3 tests/run_vm_test.py         # boot de l'ISO, log série + captures horodatées
```

Résultats dans `tests/artifacts/<horodatage>/`. Voir le dernier run : `BOOT_OK`
(base ISO) — la suite (SDDM, Calamares, système installé) est testée de la même
manière quand la VM est disponible.

## Arborescence

```
build.sh                  # build reproductible en UNE commande (mkarchiso)
profile/                  # profil archiso : packages.x86_64, pacman.conf, airootfs/ (tout le système)
packages-aur/             # paquets AUR embarqués (calamares compilé au build)
calamares/                # référence de la config Calamares (aussi dans profile/airootfs/etc/calamares)
tools/                    # build_sandbox.py (build rootless), fetch_deb_tools.py, archrepo.py, chroot.sh,
                          # patch_initcpio.py, fetch_extras.py (Proton-GE, Wine-GE, Heroic, Teams)
tests/                    # run_vm_test.py + artifacts/
docs/                     # ARCHITECTURE.md, MAINTENANCE.md, POINTS_A_VALIDER_EN_MATERIEL.md
.github/workflows/        # CI : build de l'ISO en artifact
```

## Personnalisation post-installation

Tout est réversible et documenté dans [docs/MAINTENANCE.md](docs/MAINTENANCE.md),
via le fichier central **`/etc/pasteque/pasteque.conf`** (niveau d'immuabilité,
comportement des mises à jour, taille de la corbeille de sauvegarde, indexation,
anti-cheat) et l'application **Gestionnaire d'applications Pastèque** (curseur
d'immuabilité inclus).

## Licence

Code : MIT. Les logiciels embarqués gardent leurs licences respectives.
