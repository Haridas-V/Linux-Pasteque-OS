#!/usr/bin/env python3
"""Tests unitaires Pastèque (sans root, sans VM) — tournent en CI AVANT le build.

Couvre : syntaxe de tous les scripts, format de signature des modules (Secure Boot),
sign/verify GPG de l'ISO, requêtes anti-cheat, lanceur de jeux --list, config Calamares,
et le workflow GitHub (YAML + script bash embarqué syntaxiquement valide).

Usage : python3 tests/test_units.py
"""
import glob
import importlib.util
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FAIL = []


def t(name, fn):
    try:
        fn()
        print("PASS", name, flush=True)
    except Exception as e:
        print("FAIL", name, "->", repr(e), flush=True)
        FAIL.append(name)


def compile_all():
    pys = glob.glob(os.path.join(REPO, "tools/*.py")) + \
          glob.glob(os.path.join(REPO, "agents/*.py")) + \
          glob.glob(os.path.join(REPO, "tests/*.py"))
    for p in glob.glob(os.path.join(REPO, "profile/airootfs/usr/local/bin/*")):
        if os.path.isfile(p) and open(p, errors="replace").readline().startswith("#!") and "python" in open(p, errors="replace").read(200):
            pys.append(p)
    for p in pys:
        py_compile.compile(p, doraise=True)


def bash_n_all():
    shs = glob.glob(os.path.join(REPO, "tools/*.sh")) + \
          glob.glob(os.path.join(REPO, "profile/airootfs/usr/local/bin/*")) + \
          glob.glob(os.path.join(REPO, "tests/*.sh"))
    for p in shs:
        if not os.path.isfile(p):
            continue
        head = open(p, errors="replace").read(200)
        if p.endswith(".sh") or (head.startswith("#!") and "bash" in head):
            r = subprocess.run(["bash", "-n", p], capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError("%s: %s" % (p, r.stderr))


def test_sb_module_signature():
    if not shutil.which("openssl"):
        print("  (openssl absent, test saute)")
        return
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import sb_sign
    sb_sign.OPENSSL = shutil.which("openssl")
    with tempfile.TemporaryDirectory() as td:
        key = os.path.join(td, "k.pem"); crt = os.path.join(td, "c.pem")
        subprocess.run(["openssl", "req", "-new", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", key, "-out", crt, "-days", "1", "-subj", "/CN=Test SB"],
                       check=True, capture_output=True)
        ko = os.path.join(td, "dummy.ko")
        with open(ko, "wb") as f:
            f.write(b"\x7fELF" + os.urandom(512))
        sb_sign.sign_module(ko, key, crt)
        data = open(ko, "rb").read()
        assert sb_sign.MAGIC in data[-64:], "magic absent"
        # le CMS doit se parser et sa longueur matcher l'en-tête
        idx = data.rindex(sb_sign.MAGIC)
        hdr = data[idx + len(sb_sign.MAGIC):]
        sig_len = int.from_bytes(hdr[8:12], "big")
        cms = data[idx - sig_len:idx]
        der = os.path.join(td, "sig.der")
        open(der, "wb").write(cms)
        r = subprocess.run(["openssl", "cms", "-cmsout", "-inform", "DER", "-in", der, "-print"],
                           capture_output=True, text=True)
        assert r.returncode == 0, "CMS illisible: " + r.stderr[-200:]
        assert b"Test SB" in r.stdout.encode() or "Test SB" in r.stdout
        # re-signer ne doit pas doubler la signature
        size1 = len(data)
        sb_sign.sign_module(ko, key, crt)
        assert len(open(ko, "rb").read()) == size1, "double signature"


def test_iso_sign_verify():
    if not shutil.which("gpg"):
        print("  (gpg absent, test saute)")
        return
    with tempfile.TemporaryDirectory() as td:
        gnupg = os.path.join(td, "gnupg")
        os.makedirs(gnupg)
        env = dict(os.environ, GNUPGHOME=gnupg)
        subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "t",
                        "--quick-gen-key", "Test <t@t>", "rsa2048", "sign", "0"],
                       check=True, capture_output=True, env=env)
        iso = os.path.join(td, "x.iso")
        open(iso, "wb").write(b"fake iso" * 1000)
        r = subprocess.run(["bash", os.path.join(REPO, "tools/sign_iso.sh"), iso],
                           env=dict(env, SIGNING_KEY="t@t", PASTEQUE_GPG_PASSPHRASE="t"),
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert os.path.exists(iso + ".asc") and os.path.exists(iso + ".sha256")
        fpr = subprocess.run(["gpg", "--list-keys", "--with-colons", "t@t"],
                             capture_output=True, text=True, env=env).stdout
        fpr = [l.split(":")[9] for l in fpr.splitlines() if l.startswith("fpr")][0]
        r = subprocess.run(["bash", os.path.join(REPO, "tools/verify_iso.sh"), iso, fpr],
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0, "verify bon fpr a echoue: " + r.stdout + r.stderr
        r = subprocess.run(["bash", os.path.join(REPO, "tools/verify_iso.sh"), iso, "0" * 40],
                           capture_output=True, text=True, env=env)
        assert r.returncode == 1, "verify mauvais fpr aurait dû échouer"


def test_anticheat_query():
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("pac", os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-anticheat"))
    spec = importlib.util.spec_from_loader("pac", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    m.DB = os.path.join(REPO, "profile/airootfs/usr/share/pasteque/anticheat-db.json")
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = m.query("fortnite")
    assert rc == 0 and "OK" in buf.getvalue(), buf.getvalue()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = m.query("valorant")
    assert rc == 2 and "KO" in buf.getvalue(), buf.getvalue()


def test_games_list():
    with tempfile.TemporaryDirectory() as h:
        os.makedirs(os.path.join(h, ".steam/steamapps"))
        os.makedirs(os.path.join(h, ".local/share/applications"))
        open(os.path.join(h, ".steam/steamapps/appmanifest_730.acf"), "w").write('"appid" "730"\n"name" "CS2"\n')
        open(os.path.join(h, ".local/share/applications/pasteque-x.desktop"), "w").write(
            "[Desktop Entry]\nName=JeuX\nExec=wine x.exe\n")
        env = dict(os.environ, HOME=h)
        r = subprocess.run([sys.executable, os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-games"), "--list"],
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0 and "CS2" in r.stdout and "JeuX" in r.stdout, r.stdout + r.stderr


def test_workflow_yaml_and_bash():
    import yaml
    wf = yaml.safe_load(open(os.path.join(REPO, ".github/workflows/build-iso.yml")))
    step = [s for s in wf["jobs"]["build"]["steps"] if "run" in s and "docker run" in s["run"]][0]
    script = step["run"]
    # le bloc est passe a bash -c '...' dans docker : le reconstituer et bash -n
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write("bash -c '" + script.replace("'", "'\\''") + "'\n")
        path = f.name
    r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    os.unlink(path)
    assert r.returncode == 0, "script workflow invalide: " + r.stderr


def test_calamares_config():
    import yaml
    base = os.path.join(REPO, "profile/airootfs/etc/calamares")
    settings = yaml.safe_load(open(os.path.join(base, "settings.conf")))
    assert "sequence" in settings, "settings.conf sans sequence"
    seq = settings["sequence"]
    shown = [x for e in seq if isinstance(e, dict) and "show" in e for x in e["show"]]
    execs = [x for e in seq if isinstance(e, dict) and "exec" in e for x in e["exec"]]
    assert "partition" in shown and "users" in shown, shown
    # chaque viewmodule de la sequence doit avoir un .conf
    confs = os.listdir(os.path.join(base, "modules"))
    for name in ("partition", "users", "keyboard", "locale", "welcome", "summary", "shellprocess"):
        assert name + ".conf" in confs, name + ".conf manquant"
    pc = open(os.path.join(base, "modules/partition.conf")).read()
    assert "eraseDisk: true" in pc and "enableLuksAutomatedPartitioning: true" in pc


def test_anticheat_db():
    d = json.load(open(os.path.join(REPO, "profile/airootfs/usr/share/pasteque/anticheat-db.json")))
    assert d["games"]["fortnite"]["status"] == "OK"
    assert d["appids"]["2881570"]["status"] == "KO"
    for k, v in d["appids"].items():
        assert v.get("status") in ("OK", "KO", "?"), k


def test_packages_no_comments_break():
    # read_packages equivalent : lignes vides/ commentaires ne doivent pas casser
    for line in open(os.path.join(REPO, "profile/packages.x86_64")):
        line = line.split("#", 1)[0].strip()
        if line:
            assert " " not in line or line.startswith("#"), "nom de paquet avec espace: " + line


def test_generateur_fr():
    gen = os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-genere")
    with tempfile.TemporaryDirectory() as h:
        env = dict(os.environ, HOME=h)
        for desc in ["fais-moi une app qui note mes courses",
                     "une app pour compter mes parties de cartes"]:
            r = subprocess.run([sys.executable, gen, desc], capture_output=True, text=True, env=env)
            assert r.returncode == 0, r.stderr
        apps = glob.glob(os.path.join(h, "Applications/pasteque-gen/*.py"))
        desks = glob.glob(os.path.join(h, ".local/share/applications/pasteque-gen-*.desktop"))
        assert len(apps) == 2 and len(desks) == 2, (apps, desks)
        for a in apps:
            py_compile.compile(a, doraise=True)
            head = open(a).read()
            assert "--smoke" in head and "TITRE" in head


def test_wallpapers():
    import struct
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, os.path.join(REPO, "tools/gen_wallpapers.py"), td],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        pngs = glob.glob(os.path.join(td, "*.png"))
        assert len(pngs) == 3
        for p in pngs:
            d = open(p, "rb").read()
            assert d[:8] == b"\x89PNG\r\n\x1a\n"
            w, h = struct.unpack(">II", d[16:24])
            assert (w, h) == (1920, 1080)


def test_personnalise_dryrun():
    r = subprocess.run([sys.executable,
                        os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-personnalise"),
                        "--dry-run"], capture_output=True, text=True)
    assert r.returncode == 0 and "dry-run OK" in r.stdout, r.stdout + r.stderr
    assert "kwriteconfig5" in r.stdout or "plasma-apply" in r.stdout


def test_fortnite_app():
    import json as _json
    app = os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-fortnite")
    db = os.path.join(REPO, "profile/airootfs/usr/share/pasteque/anticheat-db.json")
    env = dict(os.environ, PASTEQUE_ANTICHEAT_DB=db)
    r = subprocess.run([sys.executable, app, "--smoke"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "smoke OK" in r.stdout, r.stdout + r.stderr
    r = subprocess.run([sys.executable, app, "status"], capture_output=True, text=True, env=env)
    st = _json.loads(r.stdout)
    assert st["anticheat_ok"] is True


if __name__ == "__main__":
    t("py_compile tous les scripts", compile_all)
    t("bash -n tous les scripts shell", bash_n_all)
    t("signature module Secure Boot (format CMS)", test_sb_module_signature)
    t("sign/verify GPG de l ISO", test_iso_sign_verify)
    t("requete anti-cheat (fortnite OK / valorant KO)", test_anticheat_query)
    t("lanceur de jeux --list", test_games_list)
    t("workflow CI : YAML + bash -n du script embarque", test_workflow_yaml_and_bash)
    t("config Calamares coherente", test_calamares_config)
    t("base anti-cheat valide", test_anticheat_db)
    t("packages.x86_64 sans paquets mal formes", test_packages_no_comments_break)
    t("generateur d'apps FR (2 apps generees + compilees)", test_generateur_fr)
    t("fonds d'ecran PNG valides (1920x1080)", test_wallpapers)
    t("panneau personnalisation --dry-run", test_personnalise_dryrun)
    t("app Fortnite 1-clic (smoke + status)", test_fortnite_app)
    print()
    if FAIL:
        print("ECHECS:", FAIL)
        sys.exit(1)
    print("TOUS LES TESTS UNITAIRES PASSENT")
