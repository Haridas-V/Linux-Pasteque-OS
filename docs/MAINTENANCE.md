# Maintenance de Pastèque Linux

## Personnalisation post-installation

Tout se règle dans **`/etc/pasteque/pasteque.conf`** (fichier texte commenté,
lisible et modifiable par l'utilisateur ou un autre agent) ou via l'application
**Gestionnaire d'applications Pastèque** (menu KDE → « Gestionnaire d'applications
Pastèque », onglet « Réglages »).

| Clé | Défaut | Effet |
|---|---|---|
| `IMMUTABILITY_LEVEL` | `0` | 0 = Arch classique ouvert … 5 = `/usr` en lecture seule (overlayfs, upperdir sur `/var/lib/pasteque/overlay`). Les paquets s'installent quand même via l'overlay. |
| `AUTO_UPDATE` | `1` | mises à jour automatiques en arrière-plan |
| `UPDATE_ONLY_WHEN_IDLE` | `1` | uniquement si la machine est au repos (jamais en pleine partie) |
| `AUTO_ROLLBACK` | `1` | snapshots Btrfs pre/post + rollback auto si le boot échoue |
| `ROTATING_TRASH_GB` | `10` | taille max de la corbeille de sauvegarde rotative (Go) |
| `APP_INDEXER` | `1` | indexation auto des .exe/AppImages dans le menu KDE + krunner |
| `ANTICHEAT_WARNINGS` | `1` | avertissement au lancement des jeux à anti-cheat incompatible |

### Réversibilité

- Toute app est désinstallable (y compris la stack gaming) depuis le gestionnaire
  d'applications, sans casser le système.
- `IMMUTABILITY_LEVEL=0` rend le système complètement ouvert (Arch classique).
- Les services Pastèque se désactivent un par un :
  `systemctl disable --now pasteque-update.timer` etc.

### Fichiers de configuration modifiables

- `/etc/pasteque/pasteque.conf` — config centrale
- `/usr/local/bin/pasteque-*` — scripts de la surcouche (Python/Bash lisibles)
- `/etc/calamares/` — configuration de l'installateur
- `/etc/sddm.conf.d/10-pasteque.conf` — session Wayland
- `~/.local/share/applications/pasteque-*.desktop` — entrées générées par l'indexeur

## Commandes utiles (si besoin)

```bash
sudo python3 /usr/local/bin/pasteque-update        # forcer une mise à jour maintenant
pasteque-trash-restore                             # lister la corbeille de sauvegarde
pasteque-trash-restore <nom>                       # restaurer un fichier supprimé
pasteque-anticheat-setlaunch <appid> unset <fichier>  # retirer un avertissement anti-cheat
```

## Mise à jour de la base anti-cheat

`usr/share/pasteque/anticheat-db.json` est embarquée dans l'ISO et mise à jour
avec les paquets. Sources : areweanticheatyet.com, ProtonDB.

## Rebuild de l'ISO

```bash
sudo ./build.sh                          # hôte Arch
python3 tools/build_sandbox.py all       # sandbox/CI sans root
```
