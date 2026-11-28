# Contribuer à Pastèque Linux

## Workflow
1. Fork / branche `vibe/<sujet>-68736a` depuis `vibe/pasteque-os-68736a`.
2. Chaque commit = un changement focalisé. Push → CI build automatiquement l'ISO + tests VM + upload artifact.
3. PR vers `vibe/pasteque-os-68736a` (draft d'abord), description remplie (voir template implicite de la PR #1).

## Avant de push (obligatoire)
```bash
python3 tests/test_units.py     # tests unitaires rapides (syntaxe, signatures, configs, workflow)
```
Le CI les rejoue en premier ; s'ils sont rouges, le build ne part pas.

## Règles
- **Jamais de faux résultats de test** : si un test ne peut pas tourner ici (VM/GPU/matériel), il va dans `docs/POINTS_A_VALIDER_EN_MATERIEL.md`.
- Tout ce qui touche l'ISO doit rester **hors-ligne** (extras téléchargés au build, embarqués dans `/opt/pasteque/extras`).
- Les scripts embarqués dans l'ISO (`profile/airootfs/usr/local/bin/`) doivent rester **réversibles** et documentés dans `docs/MAINTENANCE.md`.
- Pas de dépendance dure à un service externe au build sauf avec repli (ex: shim Secure Boot non bloquant).
- Français dans l'UI et la doc utilisateur ; commentaires de code en français OK.

## Où ajouter quoi
- Nouveau paquet embarqué → `profile/packages.x86_64` (le build filtre les noms inconnus, mais teste)
- Nouvel extra téléchargé au build (AppImage/tarball) → `tools/fetch_extras.py` + install dans `pasteque-install-extras`
- Nouvelle app custom → `profile/airootfs/usr/local/bin/pasteque-*` (PyQt6 GUI ou CLI avec `--list` testable) + `.desktop` dans `usr/share/applications` + test dans `tests/live_tests.sh`
- Nouvelle option utilisateur → `etc/pasteque/pasteque.conf` + case dans le gestionnaire (onglet Réglages)
- Test VM → `tests/live_shell.py` / `tests/usb_boot_test.py` / `tests/run_vm_test.py`

## Sous-agents
`agents/` : orchestrateur + 4 sub-agents (builder, testeur VM, rédacteur docs, revieweur PR).
Test local sans clé API : `cd agents && python3 test_local.py` (venv + `mistralai-agents`).
Déploiement managé (`agents deploy`) : demander au propriétaire du dépôt (nécessite approbation).
