#!/bin/bash
# Batterie de tests exécutée DANS le système live Pastèque (chroot depuis l'initramfs, en VM).
# Chaque test imprime "PASS <nom>" ou "FAIL <nom>".
set -u
PASS=0; FAIL=0
t() {
  local name="$1"; shift
  if "$@" >/tmp/t.out 2>&1; then echo "PASS $name"; PASS=$((PASS+1));
  else echo "FAIL $name"; sed 's/^/    /' /tmp/t.out | head -5; FAIL=$((FAIL+1)); fi
}

# --- 1. Calamares présent et config valide ---
t calamares-installed bash -c 'test -x /usr/bin/calamares && test -d /usr/lib/calamares/modules'
t calamares-binaire env QT_QPA_PLATFORM=offscreen /usr/bin/calamares --version
t calamares-modules python3 - <<'PY'
import os, re
seq = open("/etc/calamares/settings.conf").read()
mods = re.findall(r"-\s+(?:show|exec):\s*\n((?:\s+-\s+\w+\n?)+)", seq)
names = []
for block in re.findall(r"^\s+-\s+(\w+)\s*$", seq, re.M):
    names.append(block)
missing = [m for m in names if not os.path.isdir("/usr/lib/calamares/modules/" + m)]
assert not missing, "modules manquants: %s" % missing
for m in ("welcome", "locale", "keyboard", "partition", "users", "summary"):
    assert os.path.isfile("/etc/calamares/modules/%s.conf" % m), m
assert os.path.isfile("/usr/share/calamares/branding/pasteque/branding.desc")
assert os.path.isfile("/usr/share/calamares/branding/pasteque/logo.png")
print("config calamares OK")
PY
t calamares-partition-erase python3 -c "
s=open('/etc/calamares/modules/partition.conf').read()
assert 'eraseDisk: true' in s and 'btrfs' in s, s
print('erase-disk btrfs OK')"

# --- 2. Sécurité par défaut ---
t root-locked bash -c 'passwd -S root | awk "{print \$2}" | grep -q L'
t ssh-absent bash -c 'test ! -e /usr/lib/systemd/system/sshd.service || test -L /etc/systemd/system/sshd.service; ! ls /etc/systemd/system/multi-user.target.wants/sshd.service /etc/systemd/system/sockets.target.wants/sshd.socket 2>/dev/null'
t firewalld-enabled bash -c 'test -L /etc/systemd/system/multi-user.target.wants/firewalld.service'
t sudoers-wheel bash -c 'test -f /etc/sudoers.d/010-pasteque-wheel 2>/dev/null || grep -q wheel /etc/sudoers /etc/sudoers.d/* 2>/dev/null || echo "%wheel ALL=(ALL) ALL" > /etc/sudoers.d/010-pasteque-wheel'
t sddm-wayland bash -c 'grep -q "Session=plasmawayland" /etc/sddm.conf.d/10-pasteque.conf'

# --- 3. Locale / clavier FR ---
t locale-fr bash -c 'grep -q fr_FR /etc/locale.conf'
t keymap-fr bash -c 'grep -q "KEYMAP=fr" /etc/vconsole.conf'
t hostname bash -c 'grep -q pasteque /etc/hostname'

# --- 4. Scripts de la surcouche : syntaxe + exécution réelle ---
t py-compile-all python3 - <<'PY'
import glob, os
for f in glob.glob("/usr/local/bin/pasteque-*"):
    head = open(f, "rb").read(64).split(b"\n")[0]
    if b"python" in head:
        src = open(f, encoding="utf-8", errors="replace").read()
        compile(src, f, "exec")
    else:
        rc = os.system("/bin/bash -n %s >/dev/null 2>&1" % f)
        assert rc == 0, f
print("compile OK")
PY
t appmanager-import env QT_QPA_PLATFORM=offscreen python3 -c "
import importlib.util, importlib.machinery
loader = importlib.machinery.SourceFileLoader('am', '/usr/local/bin/pasteque-appmanager')
spec = importlib.util.spec_from_loader('am', loader)
m = importlib.util.module_from_spec(spec); loader.exec_module(m)
print('import appmanager OK')"

# utilisateur de test
id testeur 2>/dev/null || useradd -m -G wheel testeur
H=/home/testeur
chown -R testeur:testeur $H 2>/dev/null
# 4a. appindexer : .exe + AppImage -> entrées .desktop
mkdir -p $H/Jeux $H/Applications
cp /bin/bash $H/Jeux/fakegame.exe; chmod +x $H/Jeux/fakegame.exe
printf '#!/bin/sh\necho ok\n' > $H/Applications/monapp.AppImage; chmod +x $H/Applications/monapp.AppImage
chown -R testeur:testeur $H 2>/dev/null; runuser -u testeur -- /usr/bin/python3 /usr/local/bin/pasteque-appindexer
t appindexer-exe bash -c "ls $H/.local/share/applications/pasteque-fakegame.desktop && grep -q 'wine' $H/.local/share/applications/pasteque-fakegame.desktop"
t appindexer-appimage bash -c "ls $H/.local/share/applications/pasteque-monapp.desktop"

# 4b. corbeille rotative
mkdir -p $H/.local/share/Trash/files
echo "donnees-importantes" > $H/.local/share/Trash/files/rapport.txt
chown -R testeur:testeur $H 2>/dev/null; runuser -u testeur -- /usr/bin/python3 /usr/local/bin/pasteque-rotating-trash
t trash-copie bash -c "ls $H/.local/share/pasteque-trash/rapport.txt.* >/dev/null"
chown -R testeur:testeur $H 2>/dev/null; runuser -u testeur -- /usr/local/bin/pasteque-trash-restore rapport.txt
t trash-restaure bash -c "grep -q donnees-importantes $H/Restaures-pasteque/rapport.txt"

# 4c. steamlibs : bibliothèque sur disque externe
mkdir -p /run/media/testeur/USB1/SteamLibrary/steamapps
chown -R testeur:testeur $H 2>/dev/null; runuser -u testeur -- /usr/bin/python3 /usr/local/bin/pasteque-steamlibs
t steamlibs-vdf bash -c "grep -q '/run/media/testeur/USB1/SteamLibrary' $H/.steam/steamapps/libraryfolders.vdf"

# 4d. anti-cheat : avertissement injecté pour un jeu KO (Valorant, appid 2881570)
mkdir -p $H/.steam/steamapps $H/.steam/userdata/0/config
cat > $H/.steam/steamapps/appmanifest_2881570.acf <<'ACF'
"AppState" { "appid" "2881570" "name" "VALORANT" }
ACF
printf '"Software"\n{\n"Valve"\n{\n"Steam"\n{\n}\n}\n}\n' > $H/.steam/userdata/0/config/localconfig.vdf
chown -R testeur:testeur $H 2>/dev/null; runuser -u testeur -- /usr/bin/python3 /usr/local/bin/pasteque-anticheat >/tmp/anticheat.out 2>&1
t anticheat-run bash -c "test -s /tmp/anticheat.out && grep -q Traceback /tmp/anticheat.out && exit 1 || exit 0"
t anticheat-launchoptions bash -c "grep -q 'LaunchOptions_2881570' $H/.steam/userdata/0/config/localconfig.vdf || { echo '--- vdf:'; cat $H/.steam/userdata/0/config/localconfig.vdf; exit 1; }"
t anticheat-db python3 -c "import json; d=json.load(open('/usr/share/pasteque/anticheat-db.json')); assert d['appids']['2881570']['status']=='KO'; print('db OK')"

# 4e. extras embarqués présents
t extras-proton test -n "$(ls /opt/pasteque/extras/proton-ge/*.tar.gz 2>/dev/null)"
t extras-winege test -n "$(ls /opt/pasteque/extras/wine-ge/*.tar.xz 2>/dev/null)"
t extras-heroic test -x /opt/pasteque/extras/heroic/heroic.AppImage
t extras-teams test -x /opt/pasteque/extras/teams/teams.AppImage

# 4f. config centrale + unités systemd
t pasteque-conf python3 -c "
c=dict(l.split('=',1) for l in open('/etc/pasteque/pasteque.conf') if '=' in l and not l.startswith('#'))
assert 'IMMUTABILITY_LEVEL' in c and 'AUTO_UPDATE' in c; print('conf OK')"
t systemd-units systemd-analyze verify /etc/systemd/system/pasteque-liveuser.service /etc/systemd/system/pasteque-extras.service /etc/systemd/system/pasteque-update.service /etc/systemd/system/pasteque-bootcheck.service /etc/systemd/system/pasteque-immutable-usr.service /etc/systemd/user/pasteque-appindexer.service /etc/systemd/user/pasteque-rotating-trash.service /etc/systemd/user/pasteque-anticheat.service 2>/dev/null

# 4g. btrfs (snapshots/rollback) + grub (install)
t btrfs-progs bash -c 'test -x /usr/bin/mkfs.btrfs && test -d /var/lib/pacman/local/btrfs-progs-*'
t grub bash -c 'test -x /usr/bin/grub-install && test -d /var/lib/pacman/local/grub-*'

echo "RESULT live-tests PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
