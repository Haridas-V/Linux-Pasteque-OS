# Apps natives Pastèque, générateur d'apps (FR) et personnalisation

## Apps intégrées (Phase 2) — toutes testées (`--smoke`, headless)

| App | Icône menu | Fonction | Données |
|---|---|---|---|
| `pasteque-notes` | 📝 Notes rapides | liste de notes, autosave | `~/.local/share/pasteque/notes.json` |
| `pasteque-minuteur` | ⏱️ Minuteur | compte à rebours + presets + notification | `~/.local/share/pasteque/minuteur.json` |
| `pasteque-snake` | 🐍 Snake | jeu arcade (flèches, Espace=rejouer) | record dans `~/.local/share/pasteque/scores/snake.json` |
| `pasteque-monitor` | 📊 Monitoring | CPU/RAM/disque/temp en direct (barres colorées) | lecture seule /proc, /sys |
| `pasteque-games` | 🎮 Lanceur de jeux | Steam + .exe/AppImages indexés, statut anti-cheat | — |

Test : `QT_QPA_PLATFORM=offscreen pasteque-snake --smoke` (idem pour chaque app).

## Générateur d'apps en français (Phase 3)

```bash
pasteque-genere "fais-moi une app qui note mes courses"
pasteque-genere "une app pour compter mes parties de cartes"
pasteque-genere "un minuteur pour les pâtes"
pasteque-genere --smoke     # démo : génère 2 apps et les exécute (smoke)
```

- Détection d'intention en français : liste / compteur / minuteur / calculatrice / notes / fiche générique.
- Chaque app générée : fenêtre PyQt6 native, logique complète, **sauvegarde JSON automatique**,
  entrée dans le menu KDE, code **lisible et modifiable à la main**, `--smoke` intégré.
- Sortie : `~/Applications/pasteque-gen/<slug>.py` + `~/.local/share/applications/pasteque-gen-<slug>.desktop`.

## Personnalisation (Phase 4) — panneau visible : 🎨 Personnalisation

- Thème Breeze **sombre (défaut, sobre)** / clair → `plasma-apply-lookandfeel`
- Couleur d'accent (sélecteur) → `plasma-apply-colorscheme`
- Fond d'écran parmi les 3 fonds Pastèque générés au build (+ fonds système) → `plasma-apply-wallpaperimage`
- Disposition du panneau (bas / gauche) + taille de police → `kwriteconfig5`

On réutilise **uniquement** les outils KDE officiels ; aucun réinvente. Test : `pasteque-personnalise --dry-run`.
