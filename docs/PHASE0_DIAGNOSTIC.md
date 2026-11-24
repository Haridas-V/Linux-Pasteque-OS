# Phase 0 — Diagnostic honnête de Pastèque Linux (commit 614a2a6)

Date : 2026-11-24. Aucune correction de code pendant cette phase.

## 1. Ce qui MARCHE (vérifié, preuves dans l'historique CI)

- **Build rootless complet** (`tools/build_sandbox.py all`) : bootstrap pacman réel, install 181 paquets, initramfs custom (hook `pasteque_mods`), ISO hybride.
- **Tests VM (QEMU, sans KVM)** sur le run vert `45449110516` :
  `ETCHER_COMPATIBLE`, `BOOT_OK` (CD BIOS+UEFI), `USB_BOOT_OK` + `USB_UEFI_BOOT_OK` (disque flashé façon Etcher), batterie live ~40 checks PASS, **install sur disque virtuel btrfs + boot du système installé jusqu'au login**.
- **Tests unitaires** (`tests/test_units.py`, 10 tests) : PASS en local **et** en CI (étape rapide avant le build, run `45497164054`).
- **Signature** : GPG sign/verify de l'ISO testé localement (rc=0, empreinte OK) ; format de signature CMS des modules testé (openssl parse OK).
- **Sous-agents** (`agents/`) : 4 sub-agents, test scripté local PASS.
- **Hygiène repo** : 146 fichiers / 1,1 Mo ; `.gitignore` couvre `work/`, `out/`, `tools/root/`, `tests/artifacts/`, `__pycache__/` (0 pycache commité).

## 2. Ce qui CASSE (au HEAD 614a2a6)

| # | Symptôme | Cause racine | Statut |
|---|---|---|---|
| 1 | CI `45497164054` échoue dans `step_install` : `'NoneType' object has no attribute 'stdout'` | `chroot()` n'a pas de `return` → la résilience ajoutée (retry paquets inconnus) lit `r.stdout` sur None | **à corriger Phase 1** (1 ligne : `return run(...)`) |
| 2 | CI `42c39be` : syntax error bash dans le workflow | apostrophe dans un commentaire (`l'ISO`) à l'intérieur du `bash -c '...'` du docker run | **corrigé** dans 614a2a6 + garde-fou : test unitaire `bash -n` du script embarqué |
| 3 | CI `fc8fb88` : `target not found: kdeconnect-kde` | paquet renommé en `kdeconnect` côté Arch | **corrigé** dans 614a2a6 + retry auto |
| 4 | CI `178f8d7` : extras manquants (tests FAIL) | rate limit API GitHub 403 sans token | **corrigé** (GITHUB_TOKEN + retry/backoff) |
| 5 | Boot UEFI depuis clé USB : `grub rescue: file not found` (constaté sur matériel réel) | efi.img ne contenait que le bootloader | **corrigé** (kernel+initrd+grub.cfg embarqués dans efi.img 1 Go) — à revalider sur le prochain run vert |
| 6 | `pasteque-bootcheck` : comparaison chaînée `not in (...) is False` (branche morte) | bug de logique | **corrigé localement, PAS encore commité** (à pousser en Phase 1) |
| 7 | `pasteque-steamlibs` : `is False` anti-pattern | style/robustesse | **corrigé localement, PAS commité** |

Historique CI : 15 runs, 2 verts complets, échecs tous expliqués ci-dessus (les 8 premiers = ère apt/SIGABRT du fetcher, remplacé par un fetcher 100 % Python).

## 3. Ce qui est MORT / orphelin (à nettoyer Phase 1)

- `tools/euid_shim.c` / `tools/euid_shim.so` : **aucune référence** dans le repo (vestige de la tentative makepkg).
- `packages-aur/calamares/etc-calamares-reference/` : répertoire vide (seul `README.md` reste).
- `__pycache__/` locaux dans `tools/`, `tests/`, `agents/` (gitignored, à nettoyer du disque).
- `build.sh` (chemin mkarchiso) ne couvre **pas** l'étape `secureboot` → écart de parité build rootless vs mkarchiso (à documenter ou couvrir).

## 4. Ce qui est RÉUTILISABLE tel quel

- `tools/build_sandbox.py` + `chroot.sh` + `archrepo.py` + `fetch_deb_tools.py` : chaîne de build rootless éprouvée.
- `tools/fetch_extras.py` / `fetch_shim.py` / `sb_sign.py` / `sign_iso.sh` / `verify_iso.sh`.
- `tests/test_units.py`, `tests/run_vm_test.py`, `tests/usb_boot_test.py`, `tests/live_shell.py` + `tests/live_tests.sh`.
- Surcouche `profile/airootfs/usr/local/bin/pasteque-*` (23 scripts) : appmanager, appindexer, rotating-trash, update/bootcheck/grub-snapshots, anticheat, steamlibs, games, welcome, secureboot, proton-default, finalize-install.
- Configs Calamares + branding, `agents/` (orchestrateur + 4 sub-agents), `docs/*`.

## 5. Liens symboliques « morts » en checkout = FAUX POSITIFS

Les `.wants/*.service` pointent vers `/usr/lib/systemd/system/...` (peuplé à l'install des paquets) : cassés dans le repo, valides dans l'ISO. À vérifier dans la batterie live (déjà couvert par `systemd-units`).

## 6. Non testable ici (environnement sans GPU/KVM) → liste matériel

`docs/POINTS_A_VALIDER_EN_MATERIEL.md` (session Plasma Wayland réelle, Fortnite/EAC, dual-boot, LUKS, Secure Boot MOK, manettes BT, perfs…).

## 7. Dette technique / risques

- Le build dépend de miroirs externes au moment du build (Arch, Ubuntu shim, GitHub releases) — mitigé : retry/backoff + shim non bloquant + extras skippables.
- La chaîne Secure Boot (shim + MOK + modules signés) est **construite et testée unitairement, mais jamais bootée avec SB réellement actif** (OVMF SB non testé) → à valider en matériel / OVMF avec clé enrôlée.
- `live_shell.py` a eu des FAIL anciens (live-mount, boot-uefi-chargeur) corrigés depuis ; le prochain run vert dira si tout tient.
- Pas de lockfile de dépendances Python des agents (`mistralai-agents>=1.1.0` non épinglé) → à épingler (Phase 1).

## 8. Recommandation pour la suite du sprint

Phase 1 (stabiliser) : corriger #1, commit #6/#7, épingler `mistralai-agents`, nettoyer #3, couvrir build.sh/secureboot, attendre un run CI 100 % vert (build + VM + install + boot installé) comme **non-régression minimale** (boot OK, session OK, appmanager/games se lancent — testables en VM via live_shell).
