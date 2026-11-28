#!/usr/bin/env python3
"""Validation locale SANS clé API : importe l'agent, vérifie la config des
sous-agents, et fait tourner un tour avec un modèle scripté (ScriptedModel).

Usage: python3 test_local.py   (depuis agents/, avec mistralai-agents installé)
"""
import asyncio
import sys

from mistralai import agents

import main


def test_config():
    a = main.agent
    assert a.name == "pasteque-orchestrateur", a.name
    subs = {s.name for s in a.subagents}
    attendu = {"builder-iso", "testeur-vm", "redacteur-docs", "revieweur-pr", "auditeur-qa"}
    assert attendu <= subs, "sous-agents manquants: %s" % (attendu - subs)
    for s in a.subagents:
        assert s.instructions and s.description, s.name
        assert s.builtins.subagents is False, "un sous-agent ne doit pas spawner d'autres sous-agents"
    print("PASS config: 5 sous-agents déclarés, builtins(subagents=False) OK")


async def test_scripted_turn():
    model = agents.testing.ScriptedModel([agents.testing.reply("rapport simulé OK")])
    async with agents.local_runtime():
        a = main.agent.override(model=model)
        state = await a.run("donne-moi le rapport")
        assert isinstance(state, agents.Completed), state
        assert "rapport simulé" in state.text
    print("PASS tour scripté (ScriptedModel, sans API):", state.text[:60])


if __name__ == "__main__":
    test_config()
    asyncio.run(test_scripted_turn())
    print("TOUS LES TESTS LOCAL OK")
    sys.exit(0)
