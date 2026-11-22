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

## Flash USB avec balenaEtcher

L'ISO est **hybride (isohybrid MBR + El Torito BIOS/UEFI)** : balenaEtcher la
reconnaît nativement comme image disque.

1. Télécharger `pasteque-*.iso` (build local `out/` ou artifact CI de la PR).
2. Dans balenaEtcher : **Flash from file** → sélectionner l'ISO → choisir la clé USB → **Flash**.
   Aucune option spéciale requise (pas besoin du mode « Unsafe » : l'ISO a une vraie table de partition MBR).
3. Vérifier l'empreinte avant flash : `sha256sum -c pasteque-*.iso.sha256`.
4. Booter la clé USB (UEFI ou BIOS, les deux marchent).

Compatibilité vérifiée automatiquement : `python3 tools/check_isohybrid.py out/pasteque-*.iso`
(signature MBR 0x55AA, partition bootable, El Torito BIOS+UEFI) et
`python3 tests/usb_boot_test.py` (simule le flash Etcher : copie brute de l'ISO
sur disque + boot QEMU depuis ce disque via le MBR).

## Tests en VM (QEMU, sans KVM accepté)

```bash
python3 tests/run_vm_test.py         # boot de l'ISO, log série + captures horodatées
```

Résultats dans `tests/artifacts/<horodatage>/`. Dernier run complet (ISO 5005 Mio) :

```bash
python3 tools/check_isohybrid.py out/pasteque-dev.iso     # ETCHER_COMPATIBLE (MBR 0x55AA, part. 0x17 bootable + part. 0xEF)
python3 tests/live_shell.py out/pasteque-dev.iso           # structure + boot BIOS CD + boot UEFI CD (OVMF) + batterie live 30/30 + install disque + boot installé
python3 tests/usb_boot_test.py --uefi out/pasteque-dev.iso # flash Etcher simulé : boot BIOS + UEFI depuis la clé
```

Résultats vérifiés : `boot-bios-chargeur` PASS, `boot-uefi-chargeur` PASS,
batterie live **30 PASS / 0 FAIL**, `install-finalize-grub` PASS,
`boot-disque-installe` PASS (login depuis /dev/vda), `USB_BOOT_OK` +
`USB_UEFI_BOOT_OK` — voir `tests/artifacts/20261122-174330-liveonly/` et
`tests/artifacts/20261122-182328/`, et le tableau dans
[docs/POINTS_A_VALIDER_EN_MATERIEL.md](docs/POINTS_A_VALIDER_EN_MATERIEL.md).

## Sous-agents (Mistral Agents SDK)

Un orchestrateur + 4 sous-agents dans [`agents/`](agents/) (build ISO, tests VM,
docs, revue de PR). Déployé comme workflow managé Mistral :
`pasteque-orchestrateur` (voir
[Studio](https://console.mistral.ai/build/workflows/deployments/pasteque-orchestrateur)),
build depuis `agents/Dockerfile` sur la branche `vibe/pasteque-os-68736a`.
Test local sans clé API : `cd agents && python3 test_local.py`.

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
