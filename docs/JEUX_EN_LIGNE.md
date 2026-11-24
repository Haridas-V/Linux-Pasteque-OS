# Jeux en ligne sous Pastèque Linux (Fortnite, Apex, …)

Pastèque embarque tout ce qu'il faut pour jouer **en ligne** sans rien installer :
**Heroic** (Epic Games / GOG), **Steam + Proton-GE par défaut**, **Lutris + Wine-GE**,
et un avertisseur anti-cheat (`pasteque-anticheat`).

## Fortnite (Epic Games) — fonctionne en ligne ✅

Easy Anti-Cheat (EAC) est **compatible Linux/Proton depuis décembre 2022** (Epic l'a
activé officiellement ; Fortnite est « Vérifié » Steam Deck).

Étapes :
1. Ouvre **Heroic** (icône bureau) → onglet **Epic** → connecte ton compte Epic.
2. Bibliothèque → **Fortnite** → **Installer** (choisis un dossier avec assez de place, ~30 Go).
3. Clic droit sur Fortnite → **Paramètres** → **Outils de compatibilité** → coche
   « Forcer l'utilisation d'un outil de compatibilité » → choisis **Proton-GE** (déjà embarqué, hors-ligne).
4. **Lancer** : EAC s'installe automatiquement avec le jeu et fonctionne sous Proton.
5. Vérification rapide : `pasteque-anticheat fortnite` → doit afficher `OK`.

> Si Epic te demande de vérifier ton e-mail/appareil, fais-le depuis un navigateur.

## Autres jeux en ligne testés

| Jeu | Lanceur | Anti-cheat | Statut Linux |
|---|---|---|---|
| Fortnite | Heroic (Epic) | EAC | ✅ OK (Proton-GE) |
| Apex Legends | Steam (appid 1172470) | EAC | ✅ OK depuis 2024 |
| Rust | Steam (252490) | EAC | ✅ OK |
| Elden Ring (co-op) | Steam (1245620) | EAC | ✅ OK |
| Rocket League | Steam (252950) | EAC | ✅ OK |
| Fall Guys | Steam (1097150) | EAC | ✅ OK |
| Counter-Strike 2 | Steam (730) | VAC | ✅ OK |
| PUBG | Steam (578080) | BattlEye | ⚠️ KO (sauf option Proton expérimentale) |
| Valorant | Lutris | Vanguard | ❌ KO (kernel-level) |
| Call of Duty | Steam | Ricochet | ❌ KO |
| GTA Online | Heroic/Steam | BattlEye | ❌ KO |

Commande pour vérifier un jeu : `pasteque-anticheat <nom ou appid>` (ex. `pasteque-anticheat 730`).
Source : [areweanticheatyet.com](https://areweanticheatyet.com).

## Avertissements automatiques

Quand un jeu Steam installé a un anti-cheat **KO** sous Linux, Pastèque injecte
automatiquement une option de lancement qui affiche une notification avant le
démarrage (voir `ANTICHEAT_WARNINGS=1` dans `/etc/pasteque/pasteque.conf` pour
désactiver).

## Astuces
- Proton-GE est déjà dans l'ISO (`/opt/pasteque/extras/proton-ge`) : Steam l'utilise
  par défaut, aucune connexion requise au premier lancement.
- Si un jeu Epic ne se lance pas : Heroic → Paramètres du jeu → essaie **Proton-GE**
  puis **Proton Experimental**.
- Performances : MangoHud est actif par défaut (`MANGOHUD=1`) ; GameMode se lance
  automatiquement avec Steam (`gamemoderun`).
