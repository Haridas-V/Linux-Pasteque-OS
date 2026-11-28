"""Outils Python exposés aux sous-agents Pastèque (exécutés dans le process worker)."""
import os
import subprocess
import sys

from mistralai import agents

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(cmd, timeout=7200, cwd=REPO):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return "rc=%d\n--- stdout (fin) ---\n%s\n--- stderr (fin) ---\n%s" % (
            r.returncode, r.stdout[-4000:], r.stderr[-2000:])
    except subprocess.TimeoutExpired:
        return "TIMEOUT après %ds: %s" % (timeout, " ".join(cmd))


@agents.tool
def run_build(target: str = "all") -> str:
    """Construit l'ISO Pastèque Linux (build rootless sandbox). target: all|bootstrap|install|aur|extras|initramfs|iso. Retourne la fin du log + rc."""
    return _run([sys.executable, "tools/build_sandbox.py", target])


@agents.tool
def run_vm_tests(which: str = "all") -> str:
    """Lance les tests QEMU TCG. which: iso|usb|live|isohybrid|all. Jamais de faux 'succès' : relaie tel quel."""
    iso = sorted(__import__("glob").glob(os.path.join(REPO, "out/*.iso")))[-1]
    cmds = {
        "isohybrid": [sys.executable, "tools/check_isohybrid.py", iso],
        "iso": [sys.executable, "tests/run_vm_test.py", iso, "--timeout", "600"],
        "usb": [sys.executable, "tests/usb_boot_test.py", iso, "--timeout", "600"],
        "live": [sys.executable, "tests/live_shell.py", iso],
    }
    sel = list(cmds) if which == "all" else [which]
    out = []
    for k in sel:
        out.append("=== %s ===\n%s" % (k, _run(cmds[k], timeout=3600)))
    return "\n".join(out)


@agents.tool
def pr_report() -> str:
    """Résumé de la PR GitHub du projet (titre, description, commits, statut CI)."""
    return _run(["gh", "pr", "view", "1", "--repo", "Haridas-V/Linux-Pasteque-OS",
                 "--json", "title,body,state,commits,reviews", "--jq",
                 "{title, state, commits: [.commits[].messageHeadline], body: (.body | .[0:3000])}"], timeout=120) + "\n" + \
           _run(["gh", "run", "list", "--repo", "Haridas-V/Linux-Pasteque-OS", "--limit", "5"], timeout=120)


@agents.tool
def repo_tree(max_depth: int = 3) -> str:
    """Arborescence du dépôt (profondeur max)."""
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in (".git", "work", "out", "tools", "__pycache__", ".aptwork", "node_modules")]
        depth = os.path.relpath(root, REPO).count(os.sep)
        if depth >= max_depth:
            dirs[:] = []
        for f in sorted(files):
            out.append(os.path.relpath(os.path.join(root, f), REPO))
    return "\n".join(out[:400])


@agents.tool
def read_repo_file(path: str, max_chars: int = 20000) -> str:
    """Lit un fichier du dépôt (chemin relatif, ex. docs/MAINTENANCE.md)."""
    full = os.path.realpath(os.path.join(REPO, path))
    if not full.startswith(os.path.realpath(REPO)):
        return "REFUSÉ: chemin hors du dépôt"
    with open(full, encoding="utf-8", errors="replace") as f:
        return f.read()[:max_chars]


@agents.tool
def write_doc(path: str, content: str) -> str:
    """Écrit un fichier de documentation (uniquement sous docs/ ou README.md)."""
    full = os.path.realpath(os.path.join(REPO, path))
    if not (full.startswith(os.path.join(os.path.realpath(REPO), "docs")) or full.endswith("README.md")):
        return "REFUSÉ: seuls docs/** et README.md sont modifiables"
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return "écrit: %s (%d octets)" % (path, len(content))
