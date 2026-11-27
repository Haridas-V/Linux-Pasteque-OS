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
import re
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
    """Signature module au format sign-file : magic EN DERNIER, header 12o avant
    (algo=0,hash=0,id=2,sig_len BE32), CMS verifiable avec openssl."""
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
        raw = b"\x7fELF" + os.urandom(512)
        with open(ko, "wb") as f:
            f.write(raw)
        sb_sign.sign_module(ko, key, crt, "sha512")
        data = open(ko, "rb").read()
        assert data[-len(sb_sign.MAGIC):] == sb_sign.MAGIC, "magic doit etre le DERNIER bloc"
        hdr = data[-(len(sb_sign.MAGIC) + 12):-len(sb_sign.MAGIC)]
        assert hdr[0] == 0 and hdr[1] == 0 and hdr[2] == 2, "algo=0 hash=0 id_type=2(PKCS7)"
        sig_len = int.from_bytes(hdr[8:12], "big")
        cms = data[-(len(sb_sign.MAGIC) + 12 + sig_len):-(len(sb_sign.MAGIC) + 12)]
        content = data[:-(len(sb_sign.MAGIC) + 12 + sig_len)]
        assert content == raw, "le contenu signe est le module brut"
        sigf = os.path.join(td, "sig.der"); open(sigf, "wb").write(cms)
        rawf = os.path.join(td, "raw.ko"); open(rawf, "wb").write(content)
        v = subprocess.run(["openssl", "cms", "-verify", "-binary", "-noverify", "-inform", "DER",
                            "-in", sigf, "-certfile", crt, "-content", rawf, "-out", os.devnull],
                           capture_output=True)
        assert v.returncode == 0, "CMS non verifiable: " + v.stderr.decode()[-200:]


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


def test_new_apps_smoke():
    import shutil
    apps = {
        "pasteque-hub": [],
        "pasteque-priorites": [],
        "pasteque-benchmark": ["--quick-ok"],  # le smoke fait déjà un mini-bench
        "pasteque-parefeu": [],
        "pasteque-diagnostic": [],
    }
    for name in apps:
        path = os.path.join(REPO, "profile/airootfs/usr/local/bin/" + name)
        assert os.path.exists(path), name
        r = subprocess.run([sys.executable, path, "--smoke"], capture_output=True, text=True, timeout=300)
        assert r.returncode == 0 and "smoke OK" in r.stdout, name + ": " + r.stdout[-200:] + r.stderr[-200:]


def test_games_profiles():
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("pg", os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-games"))
    spec = importlib.util.spec_from_loader("pg", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    import tempfile
    with tempfile.TemporaryDirectory() as h:
        m.PROFILES = os.path.join(h, "profiles")
        m.save_profile("730", {"env": {"DXVK_HUD": "1"}, "gamemode": True, "nice": 5})
        p = m.load_profile("730")
        assert p["env"]["DXVK_HUD"] == "1" and p["gamemode"] and p["nice"] == 5
        assert m.load_profile("999") == {}


def test_grub_theme_and_logo():
    base = os.path.join(REPO, "profile/airootfs")
    assert os.path.exists(os.path.join(base, "usr/share/grub/themes/pasteque/theme.txt"))
    d = open(os.path.join(base, "usr/share/pasteque/logo.png"), "rb").read()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    grub = open(os.path.join(base, "etc/default/grub")).read()
    assert "GRUB_THEME=/usr/share/grub/themes/pasteque/theme.txt" in grub
    assert "GRUB_DISABLE_OS_PROBER=false" in grub and "GRUB_ENABLE_CRYPTODISK=y" in grub


def test_conf_manual_updates_default():
    c = open(os.path.join(REPO, "profile/airootfs/etc/pasteque/pasteque.conf")).read()
    assert re.search(r"(?m)^AUTO_UPDATE=0", c), "les mises à jour doivent être manuelles par défaut"


def test_initramfs_hooks_cd_boot():
    """Le boot live depuis CD/USB exige ahci/sr_mod/cdrom/virtio dans l'initramfs,
    un index kmod (depmod) et l'attente du medium labellisé avant le hook archiso."""
    hooks = ["profile/airootfs/usr/lib/initcpio/install/pasteque_mods",
             "profile/airootfs/usr/lib/initcpio/hooks/pasteque_mods"]
    for rel in hooks:
        p = os.path.join(REPO, rel)
        r = subprocess.run(["bash", "-n", p], capture_output=True, text=True)
        assert r.returncode == 0, "%s: %s" % (rel, r.stderr)
        content = open(p, encoding="utf-8").read()
        for mod in ("ahci", "ata_piix", "sr_mod", "cdrom", "scsi_mod", "virtio_blk",
                    "usb-storage", "squashfs", "isofs", "overlay"):
            assert mod in content, "%s: module %s absent du hook" % (rel, mod)
    rt = open(os.path.join(REPO, hooks[1]), encoding="utf-8").read()
    assert "archisolabel" in rt and "by-label" in rt, "le hook runtime doit attendre le medium labellisé"
    assert "insmod" in rt, "fallback insmod par chemin .ko manquant"
    inst = open(os.path.join(REPO, hooks[0]), encoding="utf-8").read()
    assert "add_module sr_mod" in inst, "add_module par nom requis (les chemins .ko font échouer mkinitcpio)"
    src = open(os.path.join(REPO, "tools/build_sandbox.py"), encoding="utf-8").read()
    assert "depmod -a" in src, "depmod doit tourner dans la rootfs avant mkinitcpio (index kmod)"
    # regression: l'initramfs doit etre construite pour le MEME noyau que celui de l'ISO
    # (avant: 'ls | head -1' prenait le LTS -> initramfs/modules pour le mauvais noyau
    #  -> 'modprobe: FATAL: Module sr_mod not found' -> pas de CD au boot)
    assert "def kernel_versions" in src and '"-lts" not in k' in src
    assert "def verify_initramfs" in src, "verification noyau<->initramfs manquante"
    assert "verify_initramfs(initrd_src, kv)" in src, "step_iso doit verifier la coherence noyau/initramfs"


def test_live_tests_no_unbound_vars():
    """live_tests.sh tourne sous 'set -u' : un $var non echappe dans un bash -c "..."
    est developpé par le PARENT -> 'unbound variable' et la batterie s'arrete.
    (bug reel attrape en CI : '$a' dans la boucle apps-smoke)."""
    path = os.path.join(REPO, "tests/live_tests.sh")
    lines = open(path, encoding="utf-8").read().splitlines()
    # variables definies dans le script (parent) -> autorisees dans les "..."
    defined = set(re.findall(r"(?m)^([A-Z_a-z][A-Za-z0-9_]*)=", "\n".join(lines)))
    bad = []
    for i, line in enumerate(lines, 1):
        # greedy : capture tout le corps meme s'il contient des \" echappes
        for m in re.finditer(r'bash -c "(.*)"\s*$', line):
            body = m.group(1)
            for v in re.finditer(r'(?<!\\)\$([A-Za-z_][A-Za-z0-9_]*)', body):
                if v.group(1) not in defined:
                    bad.append("ligne %d: $%s non defini dans le parent" % (i, v.group(1)))
    assert not bad, "variables non echappees dans bash -c \"...\": " + "; ".join(bad)


def test_local_bin_all_executable():
    """Tout script de profile/airootfs/usr/local/bin doit etre mode 100755 dans git,
    sinon il n'est pas executable dans l'ISO (bug reel attrape en CI : pasteque-hub
    en 100644 -> 'Permission denied' au lancement)."""
    r = subprocess.run(["git", "-C", REPO, "ls-files", "-s", "profile/airootfs/usr/local/bin/"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    bad = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and "pasteque-" in parts[3] and parts[0] != "100755":
            bad.append("%s mode=%s" % (parts[3], parts[0]))
    assert not bad, "scripts non executables en git: " + "; ".join(bad)


def test_exit_flag_idiom():
    """L'idiome 'bad=0; cmd || bad=1; ...; exit $bad' doit renvoyer 0 quand tout passe
    et 1 quand quelque chose echoue (bug reel CI : 'exit $ok' avec ok=1 -> exit 1
    meme en cas de succes, ce qui faisait echouer util-apps/gamescope-test)."""
    r = subprocess.run(["bash", "-c", "bad=0; true || bad=1; exit $bad"])
    assert r.returncode == 0, "idiome exit $bad: tout OK doit -> rc 0"
    r = subprocess.run(["bash", "-c", "bad=0; false || bad=1; exit $bad"])
    assert r.returncode == 1, "idiome exit $bad: echec doit -> rc 1"
    src = open(os.path.join(REPO, "tests/live_tests.sh"), encoding="utf-8").read()
    assert "exit $ok" not in src, "anti-regression: ne plus utiliser 'exit $ok' (inversion)"


def test_workflow_strict_no_set_plus_e():
    """Le workflow ne doit PAS masquer les echecs des tests obligatoires :
    pas de 'set +e' dans le bloc build/tests, uploads en if: always(),
    et les 4 suites de tests appelees (vm, usb, live, secure boot OVMF)."""
    import yaml
    wf = yaml.safe_load(open(os.path.join(REPO, ".github/workflows/build-iso.yml"), encoding="utf-8"))
    run = next(st["run"] for st in wf["jobs"]["build"]["steps"] if "build_sandbox.py" in st.get("run", ""))
    assert "set -e" in run and "set +e" not in run, "set +e interdit dans le bloc build/tests"
    for suite in ("run_vm_test.py", "usb_boot_test.py", "live_shell.py", "sb_boot_test.py"):
        assert suite in run, "suite de tests manquante dans le workflow: " + suite
    steps = wf["jobs"]["build"]["steps"]
    uploads = [st for st in steps if st.get("uses", "").startswith("actions/upload-artifact")]
    assert uploads and all(st.get("if") == "always()" for st in uploads), \
        "les uploads d'artefacts doivent etre if: always() (logs meme si test echoue)"


def test_no_siglevel_never():
    """Plus aucun SigLevel = Never dans le depot : verification crypto des paquets."""
    bad = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in (".git", "work", "out", "__pycache__", "node_modules")]
        for fn in files:
            fp = os.path.join(root, fn)
            try:
                txt = open(fp, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            if re.search(r"(?m)^\s*SigLevel\s*=\s*Never", txt):
                bad.append(fp)
    assert not bad, "SigLevel = Never encore present: " + ", ".join(bad)
    conf = open(os.path.join(REPO, "profile/pacman.conf"), encoding="utf-8").read()
    assert "Required" in conf, "pacman.conf de production doit exiger les signatures"


def test_sb_sign_format_sign_file():
    """sb_sign.py doit produire EXACTEMENT le format de scripts/sign-file du noyau :
    [data][CMS][header 12o: algo=0,hash=0,id=2,sig_len BE32][magic EN DERNIER],
    CMS detached NOCERTS NOATTR, hash lu depuis IKCONFIG, modules compresses
    decompresses+resignes en .ko, et echec franc si incomplet."""
    src = open(os.path.join(REPO, "tools/sb_sign.py"), encoding="utf-8").read()
    assert "f.write(data + cms + header + MAGIC)" in src, "magic doit etre ecrit EN DERNIER"
    assert "bytes([0, 0, 2, 0, 0, 0, 0, 0])" in src, "header: algo=0 hash=0 id_type=2(PKCS7)"
    assert '"-nocerts", "-noattr", "-nosmimecap"' in src, "CMS doit etre detached NOCERTS NOATTR"
    assert "kernel_sig_hash" in src and "IKCFG_ST" in src, "hash du noyau lu via IKCONFIG"
    assert "strip_appended_sig" in src, "l'ancienne signature Arch doit etre strippee avant re-signation"
    assert 'raise RuntimeError' in src or "sys.exit(1)" in src, "echec franc si signature incomplete"
    m = re.search(r"def ensure_tools\(\).*?(?=\ndef )", src, re.S)
    assert m and "sys.exit(1)" in m.group(0), "sbsign/openssl manquants = exit 1 (strict)"


def test_sb_module_sign_roundtrip():
    """Round-trip reel : un .ko.zst signe -> .ko avec magic terminal + CMS verifiable
    avec openssl (sha512), et l'ancienne signature est remplacee."""
    import subprocess, tempfile
    openssl = shutil.which("openssl")
    if not openssl:
        print("SKIP (openssl absent)"); return
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import sb_sign
    sb_sign.OPENSSL = openssl
    with tempfile.TemporaryDirectory() as td:
        # cle test
        key = os.path.join(td, "k.pem"); crt = os.path.join(td, "c.pem")
        subprocess.run([openssl, "req", "-new", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", key, "-out", crt, "-days", "1", "-subj", "/CN=unit-test"],
                       check=True, capture_output=True)
        # faux module compressé : contenu brut + ANCIENNE signature (style Arch) dans le .zst
        import gzip
        raw = b"\x7fELF" + os.urandom(500)
        old_sig = b"X" * 263 + bytes([0, 0, 2, 0, 0, 0, 0, 0]) + (263).to_bytes(4, "big") + sb_sign.MAGIC
        comp = subprocess.run(["gzip", "-c"], input=raw + old_sig, capture_output=True, check=True).stdout
        mod = os.path.join(td, "fake.ko.gz")
        open(mod, "wb").write(comp)
        out = sb_sign.sign_module(mod, key, crt, "sha512")
        assert out.endswith(".ko") and os.path.exists(out) and not os.path.exists(mod), "gz -> .ko"
        data = open(out, "rb").read()
        assert data[-len(sb_sign.MAGIC):] == sb_sign.MAGIC, "magic terminal"
        hdr = data[-(len(sb_sign.MAGIC) + 12):-len(sb_sign.MAGIC)]
        assert hdr[0] == 0 and hdr[1] == 0 and hdr[2] == 2, "algo=0 hash=0 id=2"
        sig_len = int.from_bytes(hdr[8:12], "big")
        cms = data[-(len(sb_sign.MAGIC) + 12 + sig_len):-(len(sb_sign.MAGIC) + 12)]
        content = data[:-(len(sb_sign.MAGIC) + 12 + sig_len)]
        assert content == raw, "contenu signe = module brut SANS l'ancienne signature"
        sigf = os.path.join(td, "s.der"); open(sigf, "wb").write(cms)
        rawf = os.path.join(td, "r.ko"); open(rawf, "wb").write(content)
        v = subprocess.run([openssl, "cms", "-verify", "-binary", "-noverify", "-inform", "DER",
                            "-in", sigf, "-certfile", crt, "-content", rawf, "-out", os.devnull],
                           capture_output=True)
        assert v.returncode == 0, "CMS non verifiable: " + v.stderr.decode()[-200:]


def test_hook_kernel_version_uname():
    """Le hook pasteque_mods runtime doit prendre la version du noyau en cours
    (uname -r), jamais 'ls /usr/lib/modules | head -1' (tri alphabetique faux)."""
    src = open(os.path.join(REPO, "tools/build_sandbox.py"), encoding="utf-8").read()
    hook = src[src.find("HOOK_RUNTIME ="):src.find("MKINITCPIO_PRESET")]
    assert "kv=$(uname -r" in hook, "le hook doit utiliser uname -r"
    assert hook.count("head -1") <= 1, "ls|head -1 ne doit subsister qu en repli"
    assert hook.count("head -1") <= 1, "ls|head -1 ne doit subsister qu en repli"


def test_labels_harmonises():
    """Plus de PASTEQUEZZZ nulle part ; le label de test est NOMOUNT_LABEL explicite,
    et le label reel de l'ISO est PASTEQUE partout."""
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in (".git", "work", "out", "__pycache__")]
        for fn in files:
            fp = os.path.join(root, fn)
            if fn == "test_units.py":
                continue  # ce fichier cite volontairement l'ancien label dans son test
            if fn.endswith((".py", ".yml", ".sh", ".cfg")):
                txt = open(fp, encoding="utf-8", errors="replace").read()
                assert "PASTEQUEZZZ" not in txt, "PASTEQUEZZZ dans " + fp
    ls = open(os.path.join(REPO, "tests/live_shell.py"), encoding="utf-8").read()
    assert "NOMOUNT_LABEL" in ls
    bs = open(os.path.join(REPO, "tools/build_sandbox.py"), encoding="utf-8").read()
    assert 'ISO_LABEL = os.environ.get("ISO_LABEL", "PASTEQUE")' in bs and "archisolabel=%s" in bs, "label ISO = PASTEQUE"


def test_finalize_install_loud():
    """pasteque-finalize-install : mkinitcpio/grub-mkconfig/pacman-key en fatals,
    preset LTS present, plus de '|| true' sur les commandes critiques."""
    src = open(os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-finalize-install"), encoding="utf-8").read()
    assert "mkinitcpio -P ||" in src and "exit 1" in src, "mkinitcpio -P doit etre fatal"
    assert "grub-mkconfig -o /boot/grub/grub.cfg ||" in src, "grub-mkconfig doit etre fatal"
    assert "pacman-key --populate archlinux; then" in src, "pacman-key populate doit etre fatal"
    assert "linux-lts.preset" in src, "preset LTS manquant"
    assert "mkinitcpio -P 2>/dev/null || true" not in src


def test_depmod_build_loud():
    """Le build ne doit plus appeler depmod avec stderr jette : log + fatal si erreurs."""
    src = open(os.path.join(REPO, "tools/build_sandbox.py"), encoding="utf-8").read()
    assert "depmod-build.log" in src, "depmod build doit logger dans work/depmod-build.log"
    assert 'depmod -a \"$kv\" 2>/dev/null' not in src, "depmod 2>/dev/null encore present"
    assert "patch_initcpio.py" in src and "usr/bin/mkinitcpio" in src, "mkinitcpio principal aussi patché (/dev/fd)"


def test_sb_boot_test_real():
    """tests/sb_boot_test.py existe et fait un VRAI test OVMF secboot :
    positif (cle en db via virt-fw-vars -> boot OK) + negatif (sans cle -> bloque)."""
    p = os.path.join(REPO, "tests/sb_boot_test.py")
    assert os.path.exists(p)
    src = open(p, encoding="utf-8").read()
    assert "secboot" in src and "virt-fw-vars" in src and "--add-db" in src
    assert "NEGATIF" in src and "BLOCKED" in src, "controle negatif requis"
    assert "module verification failed" in src, "doit verifier l'absence d'erreurs de verification modules"
    # anti test-vide : SB doit etre activee EXPLICITEMENT dans le varstore et re-lue
    assert "--secure-boot" in src, "Secure Boot doit etre activee explicitement (--secure-boot), pas supposee"
    assert "OVMF_VARS_4M.ms.fd" in src, "template MS requis (le shim signe MS doit verifier contre db)"
    assert "verify_sb_on" in src, "le varstore doit etre re-lu pour exiger SecureBoot=ON (anti varstore vide)"
    assert '"--add-db", DB_GUID, der' in src, "virt-fw-vars 24.x exige --add-db GUID FILE (nargs=2)"
    assert '"--add-mok", SHIM_GUID, der' in src, "cle Pastèque aussi dans MokList (shim -> grub -> noyau via shim_lock)"
    assert "enroll-redhat" in src, "repli varstore vierge: cles MS enroulees automatiquement"
    # regression reproduite en local : sans -L, qemu meurt apres avoir cree le socket
    # serial (roms introuvables) -> RuntimeError socket indisponible en CI
    assert '"-L", qemu_data' in src, "sb_boot_test doit passer -L <datadir qemu> (roms kvmvapic/efi-*)"
    assert "q35,smm=on" in src, "machine q35 avec SMM requis par OVMF secboot"
    assert "cfi.pflash01,property=secure,value=on" in src, "pflash secure requis par OVMF secboot"
    # boot en disque RAW (chemin Etcher), pas en -cdrom (El Torito + OVMF secboot casse cote firmware)
    assert "if=none,id=sbdisk" in src and "virtio-blk-pci" in src, "boot SB en disque raw (partition MBR 0xEF), pas en cdrom"
    assert '"-cdrom"' not in src, "plus de boot SB en -cdrom (El Torito + secboot non fiable)"


def test_test_suites_exit_nonzero_on_failure():
    """Les 4 suites de tests VM doivent echouer (exit != 0) quand un critere echoue."""
    for f, pat in (("tests/run_vm_test.py", "sys.exit(0 if ok else 2)"),
                   ("tests/usb_boot_test.py", "else 2"),
                   ("tests/live_shell.py", "sys.exit(1 if rep.fails else 0)"),
                   ("tests/sb_boot_test.py", "else 2")):
        src = open(os.path.join(REPO, f), encoding="utf-8").read()
        assert pat in src, "pattern de sortie non trouve dans %s: %s" % (f, pat)


def test_grub_snapshots_bootable():
    """Les entrees de menu snapshots doivent etre bootables : vrai UUID de /,
    pas de PLACEHOLDER, et grub-mkconfig non masque."""
    src = open(os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-grub-snapshots"), encoding="utf-8").read()
    assert "UUID=PLACEHOLDER" not in src, "entree snapshot non bootable (PLACEHOLDER)"
    assert "findmnt -n -o UUID /" in src, "UUID reel de / requis"
    assert "grub-mkconfig -o /boot/grub/grub.cfg 2>/dev/null || true" not in src, "grub-mkconfig masque"


def test_finalize_extras_loud():
    """install-extras a l'install : echec = fatal (applis offline = promesse centrale)."""
    src = open(os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-finalize-install"), encoding="utf-8").read()
    assert "install-extras 2>/dev/null || true" not in src, "echec install-extras masque"
    assert "install-extras ||" in src and "exit 1" in src, "install-extras doit etre fatal"


def test_no_masked_critical_commands():
    """MISSION: aucun '|| true' / stderr jette sur les commandes qui compromettent
    le systeme : root verrouille, pare-feu, sddm, locale FR, services pasteque,
    creation user live, sha256 de l'ISO, import cle GPG quand une cle est fournie."""
    fin = open(os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-finalize-install"), encoding="utf-8").read()
    assert "depmod -a ||" in fin, "finalize-install doit regenerer l'index kmod (modules .ko.zst->.ko signes) en FATAL"
    # /boot est exclu du squashfs : finalize doit recreer les liens noyaux dans /boot
    # de la cible, sinon mkinitcpio -P echoue en install reelle ("must be readable")
    assert "/boot/vmlinuz-linux" in fin and "ln -sfn" in fin and "/usr/lib/modules" in fin, \
        "finalize-install doit recreer /boot/vmlinuz-linux et /boot/vmlinuz-lts dans la cible (/boot exclu du squashfs)"
    assert "non recree" in fin, "finalize-install doit echouer si le noyau n'est pas recreable"
    for bad in ("passwd -l root || true",
                "systemctl enable firewalld 2>/dev/null || true",
                "systemctl enable sddm 2>/dev/null || true",
                "locale-gen 2>/dev/null || true",
                "pasteque-bootcheck 2>/dev/null || true",
                "pasteque-steamlibs.timer 2>/dev/null || true",
                "os-prober >/dev/null 2>&1 || true"):
        assert bad not in fin, "commande critique masquee dans finalize-install: %r" % bad
    for good in ("passwd -l root ||", "systemctl enable firewalld ||", "systemctl enable sddm ||",
                 "locale-gen ||", "pasteque-bootcheck ||", "exit 1"):
        assert good in fin, "commande critique non rendue fatale: %r" % good
    liv = open(os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-liveuser"), encoding="utf-8").read()
    assert "|| true" not in liv, "liveuser masque encore une erreur (|| true)"
    sig = open(os.path.join(REPO, "tools/sign_iso.sh"), encoding="utf-8").read()
    assert "sha256 a echoue" in sig and "exit 1" in sig, "sign_iso.sh doit echouer si sha256 echoue"
    assert "PASTEQUE_GPG_KEY fournie mais import impossible" in sig, "sign_iso.sh doit echouer si la cle CI est invalide"
    # plus de '|| true' du tout dans les scripts systeme shell (hors tests/harnais)
    import glob
    for f in glob.glob(os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-*")):
        if open(f, "rb").read(64).startswith(b"#!") and b"python" in open(f, "rb").read(64):
            continue
        src = open(f, encoding="utf-8", errors="replace").read()
        if "os-prober" in src or "update-desktop-database" in src:
            continue  # cas documentes : retour non-nul legitime / purement cosm\u00e9tique
        assert "|| true" not in src, "|| true restant dans %s" % os.path.basename(f)


def test_build_strict_assets_and_ssh():
    """build_sandbox.py : logo/fonds d'ecran verifies (fatal si absents), locale-gen
    fatal dans la live, sshd verifie desactive (pas de '|| true' silencieux), chmod +x fatal."""
    src = open(os.path.join(REPO, "tools/build_sandbox.py"), encoding="utf-8").read()
    assert "logo/fonds d'ecran" in src and "RuntimeError" in src, "assets visuels non verifies"
    assert "locale-gen || {" in src and "locale-gen 2>/dev/null || true" not in src, "locale-gen build masque"
    assert "sshd.service present et non masque" in src, "pas de verification sshd off"
    assert "chmod +x /usr/local/bin/* ||" in src, "chmod +x /usr/local/bin/* doit etre fatal"


def test_sudoers_overlay_and_pure_live_tests():
    """L'overlay doit contenir la règle sudo wheel (sinon le test live s'auto-mutait
    pour passer = faux positif), le build doit chmod 440, et AUCUN test live ne doit
    modifier le système dans sa condition (pure vérification)."""
    import re
    p = os.path.join(REPO, "profile/airootfs/etc/sudoers.d/010-pasteque-wheel")
    assert os.path.exists(p), "sudoers wheel absent de l'overlay (la live n'aurait pas sudo)"
    assert "%wheel ALL=(ALL) ALL" in open(p, encoding="utf-8").read()
    src = open(os.path.join(REPO, "tools/build_sandbox.py"), encoding="utf-8").read()
    assert "0o440" in src, "build doit chmod 440 le sudoers.d"
    lt = open(os.path.join(REPO, "tests/live_tests.sh"), encoding="utf-8").read()
    for m in re.finditer(r'^t (\S+) bash -c [\'"](.*)[\'"]$', lt, re.M):
        body = m.group(2)
        assert not re.search(r"\|\| *(echo|touch|mkdir|cp|ln|tee|sed -i)\b", body), \
            "test live auto-mutant (faux positif): %s" % m.group(1)


def test_shim_signed_and_grub_sbat():
    """Regressions reproduites en local avec de vrais binaires :
    - le paquet shim-signed contient shimx64.efi NON SIGNE et shimx64.efi.signed.latest
      SIGNE : il faut choisir la variante signée et verifier la table de certificats PE
      (sinon le firmware rejette Boot0001 sous SB : 'Access Denied').
    - grub-mkimage doit embarquer --sbat : shim 15.8+ rejette un grub sans .sbat
      ('No .sbat section data' -> Security Violation), meme correctement signe."""
    import importlib.util
    fs = open(os.path.join(REPO, "tools/fetch_shim.py"), encoding="utf-8").read()
    assert "def pe_signed" in fs and "shimx64.efi.signed.latest" in fs, "fetch_shim doit preferer la variante .signed.latest"
    assert "pe_signed(cand[key][pref])" in fs, "fetch_shim doit verifier la signature PE"
    bs = open(os.path.join(REPO, "tools/build_sandbox.py"), encoding="utf-8").read()
    assert '"--sbat", sbat_csv' in bs, "grub-mkimage doit recevoir --sbat (sinon shim rejette le grub)"
    assert 'b".sbat" not in _grub' in bs, "build doit verifier la presence de .sbat dans le grub"
    assert "pe_signed" in bs and "NON SIGNE" in bs, "step_secureboot doit verifier que le shim est signe"
    # test fonctionnel de pe_signed sur un faux PE
    spec = importlib.util.spec_from_file_location("fetch_shim", os.path.join(REPO, "tools/fetch_shim.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    fake = bytearray(0x200)
    fake[0x3C:0x40] = (0x80).to_bytes(4, "little")
    fake[0x80:0x84] = b"PE\0\0"
    fake[0x80 + 24:0x80 + 26] = (0x20B).to_bytes(2, "little")  # PE32+
    assert not m.pe_signed(bytes(fake)), "PE sans cert table doit etre detecte non signe"
    ddoff = 0x80 + 24 + 112
    fake2 = bytearray(fake)
    fake2[ddoff + 4 * 8 + 4:ddoff + 4 * 8 + 8] = (1234).to_bytes(4, "little")
    assert m.pe_signed(bytes(fake2)), "PE avec cert table doit etre detecte signe"


def test_kernel_signed_real_path_and_iso_guard():
    """Regression reproduite en local avec vrais binaires : sbverify --list sur le noyau
    de l'ISO -> 'No signature table present' ; boot SB -> 'error: bad shim signature'.
    Cause : sb_sign signait /boot/vmlinuz-* (symlink, absent a l'etape secureboot dans
    'all') au lieu de usr/lib/modules/<kv>/vmlinuz, que step_iso copie dans l'ISO.
    -> sb_sign doit signer les chemins REELS (realpath) et echouer si aucun noyau ;
    -> step_iso doit refuser un noyau non signe quand la chaine SB est active."""
    import importlib.util
    import tempfile
    ss = open(os.path.join(REPO, "tools/sb_sign.py"), encoding="utf-8").read()
    assert "def kernel_targets" in ss and "os.path.realpath" in ss, \
        "sb_sign doit resoudre les vrais chemins de noyaux (realpath, anti-symlink)"
    assert "aucun noyau" in ss and "sys.exit(1)" in ss, \
        "sb_sign doit echouer (exit 1) si aucun noyau a signer — pas de succes masque"
    assert "pe_signed" in ss, "sb_sign doit re-verifier la table de certs PE apres signature"
    assert "usr/lib/modules/*/**/*.ko*" in ss, \
        "le glob des modules doit couvrir kernel/ + updates/ + extra/ (sinon depmod .ko.zst dans le systeme installe)"
    # test fonctionnel de kernel_targets : symlink /boot/vmlinuz-linux -> cible reelle
    spec = importlib.util.spec_from_file_location("sb_sign_mod", os.path.join(REPO, "tools/sb_sign.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    with tempfile.TemporaryDirectory() as d:
        kvdir = os.path.join(d, "usr/lib/modules/9.9.9-test/vmlinuz")
        os.makedirs(os.path.dirname(kvdir))
        open(kvdir, "wb").write(b"MZ" + b"\0" * 100)
        bdir = os.path.join(d, "boot")
        os.makedirs(bdir)
        os.symlink("/usr/lib/modules/9.9.9-test/vmlinuz", os.path.join(bdir, "vmlinuz-linux"))
        tgts = m.kernel_targets(d)
        assert tgts == [os.path.realpath(kvdir)], \
            "kernel_targets doit retourner la cible reelle dedupliquee, pas le symlink: %r" % (tgts,)
        assert os.path.islink(os.path.join(bdir, "vmlinuz-linux")), "le symlink ne doit pas etre casse"
        with tempfile.TemporaryDirectory() as d2:
            assert m.kernel_targets(d2) == [], "kernel_targets vide si aucun noyau (main fera exit 1)"
    bs = open(os.path.join(REPO, "tools/build_sandbox.py"), encoding="utf-8").read()
    assert "def require_signed_iso_kernel" in bs, "step_iso doit avoir un garde 'noyau signe'"
    assert bs.count("require_signed_iso_kernel(os.path.join(iso,") >= 2, \
        "le garde doit couvrir vmlinuz-linux ET vmlinuz-lts embarques dans l'ISO"
    assert "bad shim signature" in bs and "pe_signed" in bs and "sbverify" in bs, \
        "le garde doit verifier la table de certs PE + sbverify --cert avec la cle de build"


def test_sb_console_marker():
    """Le test SB positif a besoin d'une preuve fiable que Secure Boot est actif :
    les 1ers messages noyau partent avant la console serie -> le systeme live doit
    imprimer lui-meme l'etat lu depuis le firmware (PASTEQUE-SECUREBOOT via securityfs),
    et sb_boot_test.py doit lire ce marqueur."""
    lu = open(os.path.join(REPO, "profile/airootfs/usr/local/bin/pasteque-liveuser"), encoding="utf-8").read()
    assert "PASTEQUE-SECUREBOOT" in lu and "/sys/kernel/security/secureboot" in lu, \
        "pasteque-liveuser doit imprimer l'etat REEL du Secure Boot (securityfs) sur /dev/console"
    assert "modprobe securityfs" in lu, "securityfs doit etre chargee avant le mount (sinon point de montage inexistant)"
    assert "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c" in lu, \
        "repli sur l'efivar EFI SecureBoot requis si securityfs indisponible"
    assert "> /dev/console" in lu, "le marqueur doit aller sur la console (visible en serie)"
    st = open(os.path.join(REPO, "tests/sb_boot_test.py"), encoding="utf-8").read()
    assert "pasteque-secureboot: 1" in st, "sb_boot_test doit accepter le marqueur PASTEQUE-SECUREBOOT: 1"
    assert "pasteque-secureboot:" in st.split("sb_enabled")[0], "boot_once doit attendre le marqueur (grace)"


def test_fetch_url_retry():
    """step_aur doit telecharger via fetch_url_retry (run CI 45995052877: HTTP 503
    codeberg au fetch du tarball Calamares, sans retry). Test fonctionnel reel avec
    serveur HTTP local : succes apres 503 transitoires, et RuntimeError franche si
    le serveur reste indisponible (jamais de fichier partiel annonce OK)."""
    import importlib.util
    import threading
    import http.server
    import socketserver
    import tempfile
    spec = importlib.util.spec_from_file_location("bs_mod", os.path.join(REPO, "tools/build_sandbox.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    payload = b"pasteque-test-payload" * 100

    class H(http.server.BaseHTTPRequestHandler):
        hits = {"n": 0}
        fail_first = {"n": 2}   # 2 premieres reponses = 503
        def do_GET(self):
            H.hits["n"] += 1
            if H.hits["n"] <= H.fail_first["n"]:
                self.send_response(503)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "f.bin")
            m.fetch_url_retry("http://127.0.0.1:%d/f" % port, dest, tries=5, base=0)
            assert open(dest, "rb").read() == payload, "contenu telecharge incorrect"
            assert H.hits["n"] == 3, "le retry apres 503 a du servir (hits=%d)" % H.hits["n"]
            assert not os.path.exists(dest + ".part"), "fichier partiel restant apres succes"
            # serveur indisponible -> RuntimeError franche, pas de fichier
            srv.shutdown()
            srv.server_close()
            dest2 = os.path.join(d, "g.bin")
            try:
                m.fetch_url_retry("http://127.0.0.1:%d/g" % port, dest2, tries=2, base=0)
                raise AssertionError("fetch_url_retry aurait du echouer franchement")
            except RuntimeError:
                pass
            assert not os.path.exists(dest2) and not os.path.exists(dest2 + ".part"), \
                "aucun fichier (meme .part) ne doit rester apres echec total"
    finally:
        try:
            srv.server_close()
        except Exception:
            pass
    bs = open(os.path.join(REPO, "tools/build_sandbox.py"), encoding="utf-8").read()
    assert "fetch_url_retry(spec[\"src\"], tarball)" in bs, "step_aur doit utiliser fetch_url_retry"
    # tous les fetchs HTTP du build passent par netutil (retry+backoff) :
    # plus aucun urlopen brut hors netutil.py et le wrapper retry de fetch_extras.py
    assert os.path.exists(os.path.join(REPO, "tools/netutil.py")), "tools/netutil.py requis"
    for tool in ("archrepo.py", "fetch_deb_tools.py", "fetch_shim.py"):
        src = open(os.path.join(REPO, "tools", tool), encoding="utf-8").read()
        assert "import netutil" in src, "%s doit utiliser netutil (retry+backoff)" % tool
    for tool in ("archrepo.py", "fetch_deb_tools.py", "fetch_shim.py"):
        src = open(os.path.join(REPO, "tools", tool), encoding="utf-8").read()
        # plus de definition locale d'un http_get/fetch avec urlopen brut
        assert "urllib.request.urlopen" not in src, \
            "%s a encore un urlopen brut sans retry" % tool


def test_wait_sock_call_sites_compat():
    """Regression : sb_boot_test appelait wait_sock(..., timeout=60) alors que la
    signature n'avait que tries= -> TypeError en CI. Verifie que CHAQUE appel
    de wait_sock dans tests/ n'utilise que des kwargs presents dans la signature."""
    import inspect
    import re
    sys.path.insert(0, os.path.join(REPO, "tests"))
    import live_shell
    params = set(inspect.signature(live_shell.wait_sock).parameters)
    assert "timeout" in params, "wait_sock doit accepter timeout= (secondes)"
    tdir = os.path.join(REPO, "tests")
    for fn in sorted(os.listdir(tdir)):
        if not fn.endswith(".py"):
            continue
        src = open(os.path.join(tdir, fn), encoding="utf-8").read()
        for m in re.finditer(r"wait_sock\(([^)]*)\)", src):
            args = m.group(1)
            if "import" in args or "def " in args:
                continue
            for kw in re.findall(r"(\w+)\s*=", args):
                assert kw in params, "%s: wait_sock appele avec kwarg inconnu %r (params=%s)" % (fn, kw, params)


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
    t("nouveaux outils --smoke (hub, priorites, benchmark, parefeu, diagnostic)", test_new_apps_smoke)
    t("profils par jeu (pasteque-games)", test_games_profiles)
    t("thème GRUB Pastèque + logo PNG + conf grub", test_grub_theme_and_logo)
    t("mises à jour manuelles par défaut (AUTO_UPDATE=0)", test_conf_manual_updates_default)
    t("hooks initramfs : modules boot CD/USB + depmod + attente medium", test_initramfs_hooks_cd_boot)
    t("live_tests.sh : pas de $var non echappe dans bash -c (set -u)", test_live_tests_no_unbound_vars)
    t("usr/local/bin : tous les scripts pasteque-* en mode 755 dans git", test_local_bin_all_executable)
    t("idiome exit \$bad (pas exit \$ok inverse) dans live_tests.sh", test_exit_flag_idiom)
    t("workflow CI strict : pas de set +e, uploads if:always(), 4 suites de tests", test_workflow_strict_no_set_plus_e)
    t("plus aucun SigLevel = Never dans le depot", test_no_siglevel_never)
    t("sb_sign.py : format sign-file exact (magic dernier, algo=0/hash=0/id=2, IKCONFIG)", test_sb_sign_format_sign_file)
    t("round-trip signature module .ko.gz -> .ko signe verifiable (sha512)", test_sb_module_sign_roundtrip)
    t("hook pasteque_mods : version noyau via uname -r", test_hook_kernel_version_uname)
    t("labels harmonises : plus de PASTEQUEZZZ, NOMOUNT_LABEL explicite, ISO=PASTEQUE", test_labels_harmonises)
    t("finalize-install : mkinitcpio/grub-mkconfig/pacman-key fatals + preset LTS", test_finalize_install_loud)
    t("build : depmod loud (log+fatal) + mkinitcpio principal patché", test_depmod_build_loud)
    t("sb_boot_test.py : vrai test OVMF secboot positif+negatif", test_sb_boot_test_real)
    t("suites VM : exit non nul si echec", test_test_suites_exit_nonzero_on_failure)
    t("entrees snapshots GRUB bootables (UUID reel, grub-mkconfig non masque)", test_grub_snapshots_bootable)
    t("finalize-install : install-extras en fatal", test_finalize_extras_loud)
    t("wait_sock : tous les appels dans tests/ utilisent des kwargs valides (regression timeout=)", test_wait_sock_call_sites_compat)
    t("aucun || true sur commandes critiques (finalize/liveuser/sign_iso)", test_no_masked_critical_commands)
    t("build strict : assets visuels verifies, locale-gen fatal, sshd off verifie, chmod fatal", test_build_strict_assets_and_ssh)
    t("sudoers wheel dans l'overlay + tests live 100% purs (pas d'auto-mutation)", test_sudoers_overlay_and_pure_live_tests)
    t("shim signe (variante .signed.latest + pe_signed) + grub-mkimage --sbat (anti rejet shim)", test_shim_signed_and_grub_sbat)
    t("noyaux signes sur le chemin REEL (anti-symlink) + guard ISO : noyau non signe = build fail", test_kernel_signed_real_path_and_iso_guard)
    t("marqueur console PASTEQUE-SECUREBOOT (securityfs) lu par sb_boot_test", test_sb_console_marker)
    t("fetch_url_retry : retry 503 + echec franc (test fonctionnel serveur HTTP local)", test_fetch_url_retry)
    print()
    if FAIL:
        print("ECHECS:", FAIL)
        sys.exit(1)
    print("TOUS LES TESTS UNITAIRES PASSENT")
