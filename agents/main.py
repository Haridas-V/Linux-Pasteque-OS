"""Orchestrateur Pastèque Linux + sous-agents (Mistral Agents SDK).

L'agent racine délègue aux sous-agents spécialisés :
  - builder-iso     : build reproductible de l'ISO
  - testeur-vm      : tests QEMU (boot ISO, USB/Etcher, suite live, install disque)
  - redacteur-docs  : doc à jour (MAINTENANCE, POINTS_A_VALIDER_EN_MATERIEL, README)
  - revieweur-pr    : cohérence de la PR #1 (code, docs, CI, tests)

Lancement local :  cd agents && uv run agents chat   (nécessite MISTRAL_API_KEY)
Test sans clé API : python3 test_local.py
"""
from mistralai import agents

from tools_repo import pr_report, read_repo_file, repo_tree, run_build, run_vm_tests, write_doc

agent = agents.Agent(
    name="pasteque-orchestrateur",
    model="mistral-large-latest",
    instructions=(
        "Tu es l'orchestrateur du projet Pastèque Linux (distribution Arch gaming, "
        "dépôt Haridas-V/Linux-Pasteque-OS, PR #1). Tu parles français.\n"
        "Délègue systématiquement aux sous-agents : ne fais toi-même ni build, ni test, "
        "ni rédaction de doc, ni review. Attends TOUS les résultats des sous-agents "
        "avant de répondre, puis synthétise en rapport clair (fait / testé / non testable).\n"
        "Règle d'or : ne déclare jamais un test réussi s'il n'a pas été exécuté ; "
        "distingue 'vérifié', 'testé avec succès' et 'non testable ici'."
    ),
    subagents=[
        agents.Subagent(
            name="builder-iso",
            description="Construit l'ISO Pastèque de façon reproductible (build rootless) et rapporte taille, sha256 et erreurs.",
            instructions=(
                "Tu es le builder du projet Pastèque Linux. Le build complet est "
                "`python3 tools/build_sandbox.py all` (rootless) ou `sudo ./build.sh` "
                "(mkarchiso). Lance le build (ou une étape) avec run_build, vérifie que "
                "out/*.iso + .sha256 existent, rapporte la taille et le sha256. En cas "
                "d'erreur, rapporte la cause exacte (dernier bloc du log) et propose le "
                "correctif le plus petit possible. Ne modifie pas le code toi-même."
            ),
            tools=[run_build, read_repo_file, repo_tree],
            builtins=agents.Builtins(subagents=False),
        ),
        agents.Subagent(
            name="testeur-vm",
            description="Exécute tous les tests QEMU possibles (boot ISO, compat Etcher/USB, suite live + install disque) et rapporte PASS/FAIL brut.",
            instructions=(
                "Tu es le testeur VM du projet Pastèque Linux (QEMU TCG, pas de KVM). "
                "Lance run_vm_tests('all') : isohybrid (compat balenaEtcher), iso "
                "(boot), usb (simulation flash Etcher), live (boot BIOS/UEFI + batterie "
                "chroot + install sur disque + boot installé). Relie les résultats tels "
                "quels (PASS/FAIL, artifacts dans tests/artifacts/). JAMAIS de faux "
                "succès : si un test n'a pas tourné, dis 'non testé'. Liste ce qui "
                "reste à valider en matériel (docs/POINTS_A_VALIDER_EN_MATERIEL.md)."
            ),
            tools=[run_vm_tests, read_repo_file],
            builtins=agents.Builtins(subagents=False),
        ),
        agents.Subagent(
            name="redacteur-docs",
            description="Met à jour la documentation (docs/MAINTENANCE.md, docs/POINTS_A_VALIDER_EN_MATERIEL.md, README.md) à partir des résultats réels.",
            instructions=(
                "Tu es le rédacteur de la doc Pastèque Linux. Lis les fichiers actuels "
                "avec read_repo_file, incorpore les VRAIS résultats des tests (demande-les "
                "au parent), mets à jour docs/POINTS_A_VALIDER_EN_MATERIEL.md (tableau des "
                "tests VM exécutés avec run IDs, et la liste matériel), docs/MAINTENANCE.md "
                "(personnalisation post-installation via /etc/pasteque/pasteque.conf) et "
                "README.md (build, flash Etcher, tests). Écris avec write_doc UNIQUEMENT "
                "sous docs/ ou README.md. Style sobre, français, aucune promesse non tenue."
            ),
            tools=[read_repo_file, write_doc, repo_tree],
            builtins=agents.Builtins(subagents=False),
        ),
        agents.Subagent(
            name="revieweur-pr",
            description="Vérifie la cohérence de la PR #1 (code vs doc vs CI vs tests) et rapporte les écarts.",
            instructions=(
                "Tu es le revieweur de la PR #1 de Pastèque Linux. Utilise pr_report() "
                "et repo_tree() + read_repo_file pour vérifier : (1) la PR décrit bien ce "
                "qui est commité, (2) la CI (.github/workflows/build-iso.yml) couvre build "
                "+ tests + artifact, (3) la doc ne déclare pas de tests non exécutés, "
                "(4) les chemins référencés existent, (5) pas de secret commité. "
                "Rapporte une liste d'écarts classés par gravité, et 'PR cohérente' sinon. "
                "Ne modifie rien."
            ),
            tools=[pr_report, repo_tree, read_repo_file],
            builtins=agents.Builtins(subagents=False),
        ),
    ],
)


if __name__ == "__main__":
    import asyncio

    async def _cli():
        session = await agent.start_session()
        print("Pastèque orchestrateur — sous-agents:",
              [s.name for s in agent.subagents] if hasattr(agent, "subagents") else "?")
        while True:
            try:
                msg = input("> ")
            except EOFError:
                break
            if msg.strip() in ("exit", "quit"):
                break
            state = await session.run(msg)
            print(getattr(state, "text", state))
        await session.cancel()

    asyncio.run(_cli())
