# Sous-agents Pastèque (Mistral Agents SDK)

Un orchestrateur + 4 sous-agents spécialisés, en Python (`from mistralai import agents`) :

| Sous-agent | Rôle | Outils |
|---|---|---|
| `builder-iso` | build reproductible de l'ISO, rapport taille/sha256/erreurs | run_build, read_repo_file, repo_tree |
| `testeur-vm` | tous les tests QEMU (boot ISO, compat Etcher/USB, suite live, install disque) | run_vm_tests, read_repo_file |
| `redacteur-docs` | doc à jour (docs/, README) depuis les résultats réels | read_repo_file, write_doc (docs/ + README seulement) |
| `revieweur-pr` | cohérence de la PR #1 (code/doc/CI/tests, pas de secrets) | pr_report, repo_tree, read_repo_file |

## Utilisation

```bash
cd agents
uv sync                 # ou: pip install mistralai-agents
uv run agents chat      # session interactive (nécessite MISTRAL_API_KEY)
```

Test local **sans clé API** (modèle scripté) :

```bash
python3 test_local.py   # PASS config (4 sous-agents) + PASS tour scripté
```

## Déploiement (managed)

Le déploiement managé construit l'image à partir du commit pushé :
contexte = racine du dépôt, Dockerfile = `agents/Dockerfile` (voir `.dockerignore`
à la racine). Équivalent MCP :

```json
{
  "deployment_name": "pasteque-orchestrateur",
  "github_url": "https://github.com/Haridas-V/Linux-Pasteque-OS",
  "revision": "vibe/pasteque-os-68736a",
  "build_directory": ".",
  "dockerfile_path": "agents/Dockerfile",
  "hardened": true
}
```

L'agent déployé s'appelle `pasteque-orchestrateur` (`name=` dans `main.py`).
Les 4 sous-agents tournent dans le même arbre de sessions. Les outils du worker
utilisent `git`/`gh` (installés dans l'image ; dépôt public → appels anonymes).
