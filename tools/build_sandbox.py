#!/usr/bin/env python3
"""Build the Pastèque Linux ISO WITHOUT root (sandbox / CI path).

Equivalent rootless de build.sh (mkarchiso) :
  1. tools      : fetch Debian build tools (xorriso, grub, mksquashfs, qemu...)
  2. bootstrap  : extract pacman + deps from Arch mirrors into work/rootfs
  3. install    : real pacman inside a user-namespace chroot installs
                  profile/packages.x86_64, then the airootfs overlay is applied
  4. initramfs  : mkinitcpio (archiso preset) inside the chroot
  5. iso        : mksquashfs + isolinux (BIOS) + grub (UEFI) + xorriso -> ISO

Usage: python3 tools/build_sandbox.py [tools|bootstrap|install|initramfs|iso|all]
Env:   ARCH_MIRROR (default http://geo.mirror.pkgbuild.com), EXTRA_CMDLINE
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TOOLS = HERE
TROOT = os.path.join(TOOLS, "root")
WORK = os.path.join(REPO, "work")
OUT = os.path.join(REPO, "out")
PROFILE = os.path.join(REPO, "profile")
ROOTFS = os.path.join(WORK, "rootfs")
CACHE = os.path.join(WORK, "archcache")
MIRROR = os.environ.get("ARCH_MIRROR", "http://geo.mirror.pkgbuild.com")
ISO_LABEL = os.environ.get("ISO_LABEL", "PASTEQUE")
ISO_NAME = os.environ.get("ISO_NAME", "pasteque")
EXTRA_CMDLINE = os.environ.get("EXTRA_CMDLINE", "")

CMDLINE = "archisolabel=%s archisobasedir=arch console=ttyS0,115200 %s" % (ISO_LABEL, EXTRA_CMDLINE)

MKINITCPIO_CONF = """MODULES=()
BINARIES=()
FILES=()
HOOKS=(base udev modconf block keyboard keymap consolefont pasteque_mods archiso filesystems)
COMPRESSION="xz"
"""

# Hook maison : charge explicitement les modules critiques au boot de l'ISO
# (l'autodétection udev par modalias est peu fiable en VM/émulation).
HOOK_INSTALL = r"""#!/usr/bin/bash
# Hook Pasteque (build) : embarque explicitement les modules critiques du boot live
# (CD SATA/IDE, USB, NVMe, squashfs/overlay...). add_module se resout par NOM via
# modinfo : depmod tourne dans la rootfs AVANT mkinitcpio (voir step_initramfs).
build() {
    add_runscript
    add_module sr_mod cdrom scsi_mod ata_piix ata_generic ahci sd_mod nvme loop squashfs isofs overlay vfat fat ext4 btrfs xfs ntfs3 usb-storage uas xhci-pci xhci-hcd ehci-pci uhci-hcd virtio_blk virtio_scsi virtio_net
}
"""

HOOK_RUNTIME = r"""#!/usr/bin/ash
# Hook Pasteque (runtime) : charge explicitement les modules critiques, re-declenche
# udev, puis ATTEND que le medium de boot (CD/USB, label archisolabel) soit visible
# avant le hook archiso (sinon archiso plante : "device did not show up after 30 seconds").
run_hook() {
    local m p kv i lbl
    kv=$(uname -r 2>/dev/null); [ -z "$kv" ] && kv=$(ls /usr/lib/modules 2>/dev/null | head -1)
    # ordre de dependances : core scsi -> cdrom -> controleurs ATA -> sr_mod
    for m in scsi_mod cdrom ahci ata_piix ata_generic sr_mod sd_mod nvme loop squashfs isofs overlay vfat fat ext4 btrfs xfs ntfs3 usb-storage uas xhci-pci xhci-hcd ehci-pci uhci-hcd virtio_blk virtio_scsi virtio_net; do
        modprobe "$m" 2>/dev/null || {
            for p in /usr/lib/modules/$kv/kernel/drivers/*/"$m".ko* /usr/lib/modules/$kv/kernel/drivers/*/*/"$m".ko*; do
                if [ -e "$p" ]; then insmod "$p" 2>/dev/null && break; fi
            done
        }
    done
    # noeuds loop pour le montage de la squashfs (devtmpfs ne les cree pas tous)
    [ -e /dev/loop-control ] || mknod /dev/loop-control c 10 237 2>/dev/null
    i=0
    while [ $i -lt 16 ]; do
        [ -e /dev/loop$i ] || mknod /dev/loop$i b 7 $i 2>/dev/null
        i=$((i+1))
    done
    # le coldplug udev a pu tourner AVANT ces modprobe : re-declenche les uevents
    udevadm trigger --action=add 2>/dev/null
    udevadm settle --timeout=15 2>/dev/null
    # attend que le medium labellise (CD/USB) soit visible pour le hook archiso
    lbl=$(sed -n 's/.*archisolabel=\([^ ]*\).*/\1/p' /proc/cmdline 2>/dev/null)
    [ -z "$lbl" ] && lbl=PASTEQUE
    i=0
    while [ $i -lt 30 ]; do
        [ -e "/dev/disk/by-label/$lbl" ] && break
        [ -b /dev/sr0 ] && break
        sleep 1
        i=$((i+1))
    done
    udevadm settle --timeout=10 2>/dev/null
}
"""

MKINITCPIO_PRESET = """ALL_config='/etc/mkinitcpio.conf'
ALL_kver='/boot/vmlinuz-linux'
PRESETS=('archiso')
archiso_image="/boot/initramfs-linux.img"
archiso_kver="/boot/vmlinuz-linux"
"""

SANDBOX_PACMAN_CONF = """[options]
RootDir = /
DBPath = /var/lib/pacman/
CacheDir = /var/cache/pacman/pkg/
LogFile = /var/log/pacman.log
Architecture = x86_64
CheckSpace
ParallelDownloads = 10
SigLevel = Required DatabaseOptional
LocalFileSigLevel = Optional

[core]
Include = /etc/pacman.d/mirrorlist.build

[extra]
Include = /etc/pacman.d/mirrorlist.build

[multilib]
Include = /etc/pacman.d/mirrorlist.build
"""


def tool_env():
    env = dict(os.environ)
    lib = os.path.join(TROOT, "usr/lib/x86_64-linux-gnu") + ":" + os.path.join(TROOT, "lib/x86_64-linux-gnu")
    env["LD_LIBRARY_PATH"] = lib + ":" + env.get("LD_LIBRARY_PATH", "")
    env["PATH"] = os.path.join(TROOT, "usr/bin") + ":" + os.path.join(TROOT, "usr/sbin") + ":" + env["PATH"]
    return env


def run(cmd, **kw):
    print("[build] $ " + " ".join(cmd), flush=True)
    if str(cmd[0]).startswith(TROOT):
        env = tool_env()  # binaire extrait des debs : a besoin de LD_LIBRARY_PATH=tools/root
    else:
        # Binaire host (python, unshare, chroot, bash...) : JAMAIS de LD_LIBRARY_PATH
        # vers tools/root, sinon mélange glibc (ex. Ubuntu 24.04 + libs trixie) -> stack smashing.
        env = dict(os.environ)
    kw.setdefault("check", True)
    return subprocess.run(cmd, env=env, **kw)


def fetch_url_retry(url, dest, tries=5, base=10):
    """Telecharge url -> dest avec retry + backoff exponentiel sur les erreurs
    transitoires (5xx type 503 codeberg, timeouts, rate limit) — vu en CI run
    45995052877. Delegue a tools/netutil.http_get : ecriture atomique via
    dest.part (jamais de fichier partiel) et RuntimeError franche si tous les
    essais echouent."""
    sys.path.insert(0, TOOLS)
    from netutil import http_get
    http_get(url, dest=dest, tries=tries, base=base)   # leve RuntimeError si tout echoue


def chroot(cmd, **kw):
    return run([os.path.join(TOOLS, "chroot.sh"), ROOTFS] + cmd, **kw)


def chroot_out(cmd):
    r = run([os.path.join(TOOLS, "chroot.sh"), ROOTFS, "/bin/bash", "-c", cmd],
            capture_output=True, text=True)
    return r.stdout.strip()


def kernel_versions():
    """Retourne (kver principal non-LTS, kver LTS ou None) presentes dans la rootfs.
    IMPORTANT : ne PAS faire 'ls /usr/lib/modules | head -1' en shell : le tri
    alphabetique met le noyau LTS (6.x) avant le principal (7.x) et on construirait
    une initramfs pour le mauvais noyau (aucun module ne chargerait au boot)."""
    kvs = [l.strip() for l in chroot_out("ls /usr/lib/modules 2>/dev/null").splitlines() if l.strip()]
    main = [k for k in kvs if "-lts" not in k]
    lts = [k for k in kvs if "-lts" in k]
    return (main[0] if main else (kvs[0] if kvs else None), lts[0] if lts else None)


def cpio_files(data):
    """Walk newc cpio archive(s) in data -> {path: content}."""
    out = {}
    pos = 0
    n = len(data)
    while pos + 110 <= n:
        if data[pos:pos + 6] != b"070701":
            nxt = data.find(b"070701", pos + 1)
            if nxt < 0:
                break
            pos = nxt
            continue
        hdr = data[pos:pos + 110]
        try:
            filesize = int(hdr[54:62], 16)
            namesize = int(hdr[94:102], 16)
        except ValueError:
            pos += 1
            continue
        name = data[pos + 110:pos + 110 + namesize - 1].decode("utf-8", "replace")
        off = (pos + 110 + namesize + 3) & ~3
        if name == "TRAILER!!!":
            pos = (off + filesize + 3) & ~3
            continue
        out[name] = data[off:off + filesize]
        pos = (off + filesize + 3) & ~3
    return out


def initramfs_files(img):
    """Tous les fichiers de l'initramfs (cpio early non compressé + streams xz)."""
    import lzma
    raw = open(img, "rb").read()
    magic = b"\xfd7zXZ\x00"
    first = raw.find(magic)
    files = cpio_files(raw[:first] if first >= 0 else raw)
    dec = b""
    pos = 0
    while pos < len(raw):
        i = raw.find(magic, pos)
        if i < 0:
            break
        d = lzma.LZMADecompressor()
        try:
            dec += d.decompress(raw[i:])
        except lzma.LZMAError:
            pass
        if d.eof and d.unused_data:
            pos = len(raw) - len(d.unused_data)
        else:
            break
    files.update(cpio_files(dec))
    return files


def verify_initramfs(img, kv):
    """Lit l'initramfs et VERIFIE que les modules embarques correspondent bien au
    noyau kv et que l'index kmod (modules.dep) est present. Sans cela, au boot :
    'modprobe: FATAL: Module sr_mod not found in directory /lib/modules/<kv>'
    et aucun pilote (CD/USB) ne se charge. Un module compile en dur (=y, listé
    dans modules.builtin) compte comme present."""
    files = initramfs_files(img)
    prefix = "usr/lib/modules/%s/" % kv
    kfiles = [k for k in files if k.startswith(prefix)]
    if not kfiles:
        present = sorted(set(k.split("/")[3] for k in files if k.startswith("usr/lib/modules/")))
        raise RuntimeError("initramfs %s: modules du noyau %s ABSENTS (present: %s)" % (img, kv, present[:5]))
    # modules compiles en dur (=y) : listés dans modules.builtin(.bin) — le format
    # .bin de kmod contient les noms en clair, on cherche la sous-chaîne
    builtin_raw = files.get(prefix + "modules.builtin", files.get(prefix + "modules.builtin.bin", b""))
    have = set()
    for k in kfiles:
        if k.endswith("/"):
            continue
        base = k.rsplit("/", 1)[-1]
        for suf in (".ko.zst", ".ko.xz", ".ko.gz", ".ko"):
            if base.endswith(suf):
                have.add(base[: -len(suf)])
                break
    # modules qui DOIVENT etre embarques comme .ko (=m dans les noyaux Arch) :
    # un module absent de l'initramfs mais aussi absent de la rootfs (ou builtin =y)
    # ne bloque pas le boot -> on ne le considere pas comme manquant
    required = ["sr_mod", "loop", "squashfs", "isofs", "overlay", "vfat", "fat",
                "usb-storage", "uas", "ata_piix", "ata_generic", "nvme", "xhci-hcd"]
    def rootfs_has(name):
        for suf in (".ko.zst", ".ko.xz", ".ko.gz", ".ko"):
            if glob.glob(os.path.join(ROOTFS, "usr/lib/modules", kv, "kernel", "**", name + suf), recursive=True):
                return True
        return False
    missing = [m for m in required
               if m not in have and ("%s.ko" % m).encode() not in builtin_raw and rootfs_has(m)]
    for idx in ("modules.dep", "modules.alias"):
        if prefix + idx not in files and prefix + idx + ".bin" not in files:
            missing.append(idx)
    if missing:
        raise RuntimeError("initramfs %s: elements critiques manquants (ni .ko ni builtin): %s" % (img, missing))
    print("[build] initramfs verifiee pour %s : %d modules .ko, index kmod OK" % (kv, len(have)), flush=True)


def read_packages(path):
    pkgs = []
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                pkgs.append(line)
    return pkgs


def step_tools():
    run([sys.executable, os.path.join(TOOLS, "fetch_deb_tools.py")])


def step_bootstrap():
    sys.path.insert(0, TOOLS)
    import archrepo
    archrepo.MIRROR = MIRROR.replace("https://", "http://")
    archrepo.bootstrap_pacman(ROOTFS, CACHE, extra=["ca-certificates", "archlinux-keyring", "gnupg"])
    os.makedirs(os.path.join(ROOTFS, "etc/pacman.d"), exist_ok=True)
    with open(os.path.join(ROOTFS, "etc/pacman.d/mirrorlist.build"), "w") as f:
        f.write("Server = %s/$repo/os/$arch\n" % MIRROR)
        f.write("Server = http://mirror.rackspace.com/archlinux/$repo/os/$arch\n")
    with open(os.path.join(ROOTFS, "etc/pacman.conf.build"), "w") as f:
        f.write(SANDBOX_PACMAN_CONF)
    # porte-cle Arch peuple (OBLIGATOIRE avec SigLevel=Required) : toute erreur est fatale
    chroot(["/usr/bin/pacman-key", "--init"])
    chroot(["/usr/bin/pacman-key", "--populate", "archlinux"])


def step_install():
    pkgs = read_packages(os.path.join(PROFILE, "packages.x86_64"))
    local = os.path.join(PROFILE, "packages.local.x86_64")
    if os.path.exists(local):
        pkgs += read_packages(local)
    print("[build] installing %d packages ..." % len(pkgs), flush=True)
    # resilient : si un nom de paquet est inconnu du depot, on le retire et on reessaie
    # (un paquet renomme ne doit jamais casser tout le build)
    import re as _re
    for attempt in range(3):
        r = chroot(["/usr/bin/pacman", "--config", "/etc/pacman.conf.build",
                    "-Sy", "--noconfirm", "--needed", "--overwrite", "*"] + pkgs,
                   check=False, capture_output=True, text=True)
        out = (r.stdout or "") + (r.stderr or "")
        missing = sorted(set(_re.findall(r"target not found: (\S+)", out)))
        if r.returncode == 0 or not missing:
            if r.returncode != 0:
                raise RuntimeError("pacman a echoue: " + out[-2000:])
            break
        print("[build] paquets inconnus retires: %s" % missing, flush=True)
        pkgs = [p for p in pkgs if p not in missing]
    else:
        raise RuntimeError("pacman echoue apres 3 essais")
    run([sys.executable, os.path.join(TOOLS, "gen_logo.py")], check=False)
    # fonds d'ecran Pasteque (PNG generes en pure python, aucune dependance)
    run([sys.executable, os.path.join(TOOLS, "gen_wallpapers.py"),
         os.path.join(PROFILE, "airootfs/usr/share/backgrounds/pasteque")], check=False)
    # identite visuelle : logo + fonds d'ecran DOIVENT exister, sinon build ECHOUE
    _logo = os.path.join(PROFILE, "airootfs/usr/share/pasteque/logo.png")
    _wpdir = os.path.join(PROFILE, "airootfs/usr/share/backgrounds/pasteque")
    if not (os.path.exists(_logo) and os.path.isdir(_wpdir) and os.listdir(_wpdir)):
        raise RuntimeError("logo/fonds d'ecran Pastèque manquants après generation -> identité visuelle incomplète, build STOPPE")
    # SSH desactive par defaut : retirer openssh si present, sinon masquer sshd,
    # puis VERIFIER que sshd n'est plus utilisable (promesse sécurité "SSH off")
    chroot(["/bin/bash", "-c",
            "pacman --config /etc/pacman.conf.build -Rns --noconfirm openssh 2>/dev/null; "
            "if [ -e /usr/lib/systemd/system/sshd.service ]; then ln -sf /dev/null /etc/systemd/system/sshd.service; fi; "
            "if [ -e /usr/lib/systemd/system/sshd.service ] && [ ! -L /etc/systemd/system/sshd.service ]; then "
            "echo '[build] ERREUR: sshd.service present et non masque'; exit 1; fi; "
            "if ls /etc/systemd/system/*.wants/ 2>/dev/null | grep -q sshd; then "
            "echo '[build] ERREUR: sshd active via *.wants'; exit 1; fi; true"])
    # overlay airootfs
    airootfs = os.path.join(PROFILE, "airootfs")
    for src, dirs, files in os.walk(airootfs):
        rel = os.path.relpath(src, airootfs)
        dst = os.path.join(ROOTFS, rel) if rel != "." else ROOTFS
        os.makedirs(dst, exist_ok=True)
        for d in dirs:
            os.makedirs(os.path.join(dst, d), exist_ok=True)
        for fn in files:
            s = os.path.join(src, fn)
            d = os.path.join(dst, fn)
            if os.path.islink(s):
                if os.path.lexists(d):
                    os.remove(d)
                os.symlink(os.readlink(s), d)
            else:
                shutil.copy2(s, d)
    print("[build] overlay applied", flush=True)
    # sudoers.d : mode 440 OBLIGATOIRE (git ne stocke que 644/755) — sudo refuse sinon
    _sud = os.path.join(ROOTFS, "etc/sudoers.d/010-pasteque-wheel")
    if os.path.exists(_sud):
        os.chmod(_sud, 0o440)
    else:
        raise RuntimeError("overlay incomplet: etc/sudoers.d/010-pasteque-wheel absent -> sudo wheel sans regle")
    # GPGDir de pacman.conf doit exister dans la rootfs, sinon toute commande pacman
    # echoue dans le systeme live/installe ("failed to resolve path ... GPGDir")
    os.makedirs(os.path.join(ROOTFS, "etc/pacman.d/gnupg"), exist_ok=True)
    # conf pacman de production (celle livrée dans l'ISO)
    shutil.copy2(os.path.join(PROFILE, "pacman.conf"), os.path.join(ROOTFS, "etc/pacman.conf"))
    # locales : locale FR obligatoire dans la live -> ECHEC FATAL (pas de || true)
    chroot(["/bin/bash", "-c", "locale-gen || { echo '[build] ERREUR: locale-gen a echoue (locale FR absente de la live)'; exit 1; }"])
    # sandbox build config (ne pas écraser la conf de production livrée dans l'ISO)
    chroot(["/bin/bash", "-c",
            "cp /etc/pacman.d/mirrorlist.build /etc/pacman.d/mirrorlist.sandbox && true"])




AUR_PACKAGES = {
    "calamares": {
        "version": "3.4.2-2",
        "src": "https://codeberg.org/Calamares/calamares/releases/download/v3.4.2/calamares-3.4.2.tar.gz",
        "build_deps": ["base-devel", "cmake", "extra-cmake-modules", "ninja",
                       "qt6-base", "qt6-declarative", "qt6-svg", "qt6-tools",
                       "kpmcore", "libpwquality", "yaml-cpp", "polkit-qt6",
                       "kcoreaddons", "kconfig", "ki18n", "boost", "python", "pybind11"],
        "cmake_opts": ["-DCMAKE_INSTALL_PREFIX=/usr", "-DCMAKE_BUILD_TYPE=Release",
                       "-DWITH_PYTHONQT=OFF", "-DWITH_PYTHON=ON",
                       "-DWITH_TESTS=OFF", "-DCMAKE_INSTALL_LIBDIR=lib"],
        "depends": ["qt6-base", "qt6-declarative", "qt6-svg", "kpmcore", "libpwquality",
                    "yaml-cpp", "polkit-qt6", "kcoreaddons", "kconfig", "ki18n",
                    "boost", "appstream-qt", "kio", "kparts", "solid", "python"],
        "desc": "Installeur graphique modulaire (Pastèque Linux)",
    },
}


def step_aur():
    """Compile les paquets AUR (calamares) en chroot : cmake + paquet pacman manuel."""
    import urllib.request
    import tarfile as _tf
    import zstandard as _z
    for pkgbase, spec in AUR_PACKAGES.items():
        build = os.path.join(WORK, "aur-build", pkgbase)
        os.makedirs(build, exist_ok=True)
        tarball = os.path.join(build, os.path.basename(spec["src"]))
        if not os.path.exists(tarball):
            print("[aur] download", spec["src"], flush=True)
            fetch_url_retry(spec["src"], tarball)   # retry/backoff : 503 transitoires vus en CI
        # deps de build
        chroot(["/usr/bin/pacman", "--config", "/etc/pacman.conf.build", "-S",
                "--noconfirm", "--needed", "--overwrite", "*", "--asdeps"] + spec["build_deps"])
        # sources dans le chroot
        srcdir = os.path.join(ROOTFS, "build", pkgbase + "-src")
        shutil.rmtree(srcdir, ignore_errors=True)
        os.makedirs(srcdir, exist_ok=True)
        with _tf.open(tarball, "r:gz") as tf:
            tf.extractall(srcdir, filter="fully_trusted")
        srcdir = os.path.join(srcdir, os.listdir(srcdir)[0])
        bdir = os.path.join(ROOTFS, "build", pkgbase + "-build")
        pkgroot = os.path.join(ROOTFS, "build", pkgbase + "-pkg")
        shutil.rmtree(bdir, ignore_errors=True)
        shutil.rmtree(pkgroot, ignore_errors=True)
        print("[aur] cmake configure %s ..." % pkgbase, flush=True)
        chroot(["/usr/bin/cmake", "-S", "/build/%s-src/%s" % (pkgbase, os.path.basename(srcdir)),
                "-B", "/build/%s-build" % pkgbase, "-G", "Ninja"] + spec["cmake_opts"])
        print("[aur] build %s (compilation, plusieurs minutes) ..." % pkgbase, flush=True)
        chroot(["/usr/bin/cmake", "--build", "/build/%s-build" % pkgbase, "--parallel", str(os.cpu_count() or 4)])
        chroot(["/usr/bin/cmake", "--install", "/build/%s-build" % pkgbase, "--prefix", "/build/%s-pkg/usr" % pkgbase])
        # .PKGINFO + paquet .pkg.tar.zst
        pkginfo = os.path.join(ROOTFS, "build", pkgbase + "-pkg", ".PKGINFO")
        with open(pkginfo, "w") as f:
            f.write("pkgname = %s\npkgver = %s\npkgdesc = %s\narch = x86_64\n" % (pkgbase, spec["version"], spec["desc"]))
            for d in spec["depends"]:
                f.write("depends = %s\n" % d)
            f.write("packager = Pasteque Linux\n")
        pkgfile = os.path.join(ROOTFS, "build", "%s-%s-x86_64.pkg.tar.zst" % (pkgbase, spec["version"]))
        chroot(["/bin/bash", "-c",
                "cd /build/%s-pkg && /usr/bin/tar --zstd -cf /build/%s-%s-x86_64.pkg.tar.zst .PKGINFO usr" % (pkgbase, pkgbase, spec["version"])])
        chroot(["/usr/bin/pacman", "--config", "/etc/pacman.conf.build", "-U",
                "--noconfirm", "--overwrite", "*", "/build/%s-%s-x86_64.pkg.tar.zst" % (pkgbase, spec["version"])])
        print("[aur] %s %s installé dans l'ISO" % (pkgbase, spec["version"]), flush=True)


def step_extras():
    extras_src = os.path.join(WORK, "extras")
    run([sys.executable, os.path.join(TOOLS, "fetch_extras.py"), extras_src])
    dest_root = os.path.join(ROOTFS, "opt/pasteque/extras")
    for prefix in ("proton-ge", "wine-ge", "heroic", "teams"):
        src = os.path.join(extras_src, prefix)
        dst = os.path.join(dest_root, prefix)
        if not os.path.isdir(src) or not os.listdir(src):
            print("[extras] %s absent (build dégradé)" % prefix, flush=True)
            continue
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(src):
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    print("[extras] copiés dans l'airootfs", flush=True)


def step_initramfs():
    # index kmod (depmod) dans la rootfs AVANT mkinitcpio : indispensable pour
    # add_module/modinfo/udev quand le hook pacman 'depmod' ne tourne pas en chroot
    # depmod AVANT mkinitcpio, en VISIBLE : toute erreur est logguee et fatale
    r = chroot(["/bin/bash", "-c",
                "rc=0; for kv in $(ls /usr/lib/modules 2>/dev/null); do depmod -a \"$kv\" || rc=1; done; exit $rc"],
               check=False, capture_output=True, text=True)
    logpath = os.path.join(WORK, "depmod-build.log")
    with open(logpath, "w") as f:
        f.write((r.stdout or "") + (r.stderr or ""))
    n_err = (r.stderr or "").count("ERROR")
    print("[build] depmod: rc=%d, %d lignes ERROR (log: %s)" % (r.returncode, n_err, logpath), flush=True)
    if r.returncode != 0 or n_err:
        print((r.stderr or "")[-2000:], flush=True)
        raise RuntimeError("depmod a echoue (%d erreurs) -> index modules inutilisable, build STOPPE" % n_err)
    for _f in ("usr/lib/initcpio/functions", "usr/bin/mkinitcpio"):
        _p = os.path.join(ROOTFS, _f)
        if os.path.exists(_p):
            run([sys.executable, os.path.join(TOOLS, "patch_initcpio.py"), _p])
    # hook maison de chargement explicite des modules
    os.makedirs(os.path.join(ROOTFS, "usr/lib/initcpio/install"), exist_ok=True)
    os.makedirs(os.path.join(ROOTFS, "usr/lib/initcpio/hooks"), exist_ok=True)
    with open(os.path.join(ROOTFS, "usr/lib/initcpio/install/pasteque_mods"), "w") as f:
        f.write(HOOK_INSTALL)
    with open(os.path.join(ROOTFS, "usr/lib/initcpio/hooks/pasteque_mods"), "w") as f:
        f.write(HOOK_RUNTIME)
    with open(os.path.join(ROOTFS, "etc/mkinitcpio.conf"), "w") as f:
        f.write(MKINITCPIO_CONF)
    os.makedirs(os.path.join(ROOTFS, "etc/mkinitcpio.d"), exist_ok=True)
    with open(os.path.join(ROOTFS, "etc/mkinitcpio.d/archiso.preset"), "w") as f:
        f.write(MKINITCPIO_PRESET)
    # noyau explicite (PAS 'ls | head -1' : le LTS se trie avant le principal et on
    # construirait une initramfs pour le mauvais noyau -> aucun module au boot)
    kv, kvl = kernel_versions()
    assert kv, "aucun noyau dans la rootfs"
    print("[build] noyaux: principal=%s lts=%s" % (kv, kvl), flush=True)
    chroot(["/bin/bash", "-c",
            "ln -sf /usr/lib/modules/%s/vmlinuz /boot/vmlinuz-linux; "
            "if [ -n '%s' ]; then ln -sf /usr/lib/modules/%s/vmlinuz /boot/vmlinuz-lts; fi" % (kv, kvl or "", kvl or "")])
    chroot(["/usr/bin/mkinitcpio", "-c", "/etc/mkinitcpio.conf", "-k", kv, "-g", "/boot/initramfs-linux.img"])
    img = os.path.join(ROOTFS, "boot/initramfs-linux.img")
    assert os.path.exists(img), "initramfs manquante"
    verify_initramfs(img, kv)   # leve une erreur si modules != noyau kv
    print("[build] initramfs OK:", os.path.getsize(img) // 1024 // 1024, "MiB", flush=True)
    # noyau LTS de secours : symlink + initramfs dediee (entree GRUB de secours)
    if kvl:
        chroot(["/usr/bin/mkinitcpio", "-c", "/etc/mkinitcpio.conf", "-k", kvl, "-g", "/boot/initramfs-lts.img"])
        lts_img = os.path.join(ROOTFS, "boot/initramfs-lts.img")
        if os.path.exists(lts_img):
            verify_initramfs(lts_img, kvl)
            print("[build] initramfs LTS OK:", os.path.getsize(lts_img) // 1024 // 1024, "MiB", flush=True)
    else:
        print("[build] pas de noyau LTS, entree de secours ignoree", flush=True)


def add_efi_mbr_partition(iso_path, efi_img):
    """Ajoute une partition MBR type 0xEF (ESP) couvrant l'image El Torito EFI,
    pour que la cle USB flashee avec Etcher boot aussi en UEFI (comme isohybrid --uefi)."""
    import struct
    with open(iso_path, "r+b") as f:
        f.seek(17 * 2048)
        brvd = f.read(2048)
        if brvd[0] != 0:
            raise RuntimeError("pas de Boot Record Volume Descriptor en secteur 17")
        cat_lba = struct.unpack("<I", brvd[71:75])[0]
        f.seek(cat_lba * 2048)
        cat = f.read(2048)
        lba = count = None
        off = 32
        while off + 32 <= len(cat):
            hdr = cat[off]
            if hdr in (0x90, 0x91):
                platform = cat[off + 1]
                n = cat[off + 2]
                if platform == 0xEF:
                    e = cat[off + 32: off + 64]
                    count = struct.unpack("<H", e[6:8])[0]
                    lba = struct.unpack("<I", e[8:12])[0]
                off += 32 + 32 * n
            else:
                off += 32
        if lba is None:
            raise RuntimeError("pas d'entree El Torito EFI dans le catalogue")
        if count in (0, 0xFFFF):
            count = os.path.getsize(efi_img) // 2048
        lba512, count512 = lba * 4, count * 4  # El Torito: secteurs 2048 o, MBR: 512 o
        f.seek(0)
        mbr = bytearray(f.read(512))
        ent = struct.pack("<B3sB3sII", 0x00, b"\x00" * 3, 0xEF, b"\x00" * 3, lba512, count512)
        mbr[446 + 16: 446 + 32] = ent
        f.seek(0)
        f.write(mbr)
    print("[build] partition MBR 0xEF ajoutee: LBA %d, %d secteurs (512 o)" % (lba512, count512), flush=True)


def require_signed_iso_kernel(path):
    """INVARIANT Secure Boot : si la chaine SB est active (shim dans work/shim), le noyau
    embarque dans l'ISO DOIT etre signe avec la cle de build (work/sb/sb.crt) — sinon grub
    via shim_lock le rejette au boot ('error: bad shim signature', reproduit en local).
    -> le build ECHOUE ici, jamais de boot SB annonce avec un noyau non signe."""
    if not os.path.exists(os.path.join(WORK, "shim", "shimx64.efi")):
        return  # pas de chaine SB (shim absent) : rien a exiger
    sys.path.insert(0, TOOLS)
    from fetch_shim import pe_signed
    if not pe_signed(open(path, "rb").read()):
        raise RuntimeError("noyau NON SIGNE embarque dans l'ISO (%s) alors que la chaine Secure Boot "
                           "est active -> boot SB impossible (bad shim signature)" % path)
    sbv = os.path.join(TROOT, "usr/bin/sbverify")
    crt = os.path.join(WORK, "sb", "sb.crt")
    if os.path.exists(sbv) and os.path.exists(crt):
        r = run([sbv, "--cert", crt, path], check=False, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("signature de %s non verifiable avec work/sb/sb.crt: %s"
                               % (path, (r.stderr or "")[-300:]))
    print("[build] noyau ISO verifie signe:", path, flush=True)


def step_iso():
    iso = os.path.join(WORK, "iso")
    sfs = os.path.join(iso, "arch/x86_64/airootfs.sfs")
    if not os.path.exists(sfs):
        shutil.rmtree(iso, ignore_errors=True)
    for d in ["arch/x86_64", "boot/x86_64", "boot/isolinux", "boot/grub"]:
        os.makedirs(os.path.join(iso, d), exist_ok=True)
    # noyau de l'ISO = noyau principal (non-LTS) de la rootfs, explicitement
    kv, kvl = kernel_versions()
    assert kv, "aucun noyau dans la rootfs"
    kernel_src = os.path.join(ROOTFS, "usr/lib/modules", kv, "vmlinuz")
    assert os.path.exists(kernel_src), "noyau %s introuvable" % kv
    shutil.copy2(kernel_src, os.path.join(iso, "boot/x86_64/vmlinuz-linux"))
    require_signed_iso_kernel(os.path.join(iso, "boot/x86_64/vmlinuz-linux"))
    initrd_src = os.path.join(ROOTFS, "boot/initramfs-linux.img")
    assert os.path.exists(initrd_src), "initramfs manquante: lancez d'abord l'étape initramfs"
    verify_initramfs(initrd_src, kv)   # coherence noyau <-> initramfs, sinon boot sans pilotes
    shutil.copy2(initrd_src, os.path.join(iso, "boot/x86_64/initramfs-linux.img"))
    # noyau LTS de secours dans l'ISO aussi
    have_lts = False
    if kvl:
        lts_kernel = os.path.join(ROOTFS, "usr/lib/modules", kvl, "vmlinuz")
        lts_initrd = os.path.join(ROOTFS, "boot/initramfs-lts.img")
        if os.path.exists(lts_kernel) and os.path.exists(lts_initrd):
            verify_initramfs(lts_initrd, kvl)
            shutil.copy2(lts_kernel, os.path.join(iso, "boot/x86_64/vmlinuz-lts"))
            require_signed_iso_kernel(os.path.join(iso, "boot/x86_64/vmlinuz-lts"))
            shutil.copy2(lts_initrd, os.path.join(iso, "boot/x86_64/initramfs-lts.img"))
            have_lts = True

    # restaure le helper setuid de dbus (illisible sinon depuis le cache pacman)
    import tarfile as _tf
    for _pkg in glob.glob(os.path.join(ROOTFS, "var/cache/pacman/pkg/dbus-*.pkg.tar.zst")):
        try:
            with open(_pkg, "rb") as _f:
                import zstandard as _z
                _raw = _z.ZstdDecompressor().stream_reader(_f)
                with _tf.open(fileobj=_raw, mode="r|") as _t:
                    for _m in _t:
                        if _m.name.endswith("usr/lib/dbus-daemon-launch-helper"):
                            _p = os.path.join(ROOTFS, "usr/lib/dbus-daemon-launch-helper")
                            if os.path.lexists(_p):
                                os.remove(_p)
                            _t.extract(_m, ROOTFS, filter="fully_trusted")
                            os.chmod(_p, 0o4755)
        except Exception as e:
            print("[iso] dbus helper:", e, flush=True)
    # filet de securite : tous les scripts maison doivent etre EXECUTABLES dans l'ISO
    # (un oubli de chmod +x en git rendrait l'app invisible au lancement)
    chroot(["/bin/bash", "-c", "chmod +x /usr/local/bin/* || { echo '[build] ERREUR: chmod +x /usr/local/bin/*'; exit 1; }"])
    # squashfs de l'airootfs (réutilisé si déjà présent et FORCE_SQUASHFS unset)
    if not os.path.exists(sfs) or os.environ.get("FORCE_SQUASHFS"):
        if os.path.exists(sfs):
            os.remove(sfs)
        excl = ["-e", "boot", "dev", "proc", "sys", "tmp", "run", "mnt", "media",
            "var/cache/pacman", "var/log", "root", "home",
            "etc/mtab"]
        run([os.path.join(TROOT, "usr/bin/mksquashfs"), ROOTFS, sfs,
             "-comp", "xz", "-b", "1M", "-Xbcj", "x86",
             "-processors", str(os.cpu_count() or 4), "-noappend", "-no-progress", "-all-root"] + excl)
    else:
        print("[build] squashfs réutilisé:", sfs, flush=True)

    # isolinux (BIOS)
    isolinux_bin = os.path.join(TROOT, "usr/lib/ISOLINUX/isolinux.bin")
    ldlinux = None
    for cand in glob.glob(os.path.join(TROOT, "usr/lib/syslinux/modules/bios/ldlinux.c32")):
        ldlinux = cand
    shutil.copy2(isolinux_bin, os.path.join(iso, "boot/isolinux/isolinux.bin"))
    if ldlinux:
        shutil.copy2(ldlinux, os.path.join(iso, "boot/isolinux/ldlinux.c32"))
    with open(os.path.join(iso, "boot/isolinux/isolinux.cfg"), "w") as f:
        f.write("DEFAULT pasteque\nTIMEOUT 30\n"
                "LABEL pasteque\n  KERNEL /boot/x86_64/vmlinuz-linux\n"
                "  APPEND initrd=/boot/x86_64/initramfs-linux.img %s\n" % CMDLINE)
        if have_lts:
            f.write("LABEL pasteque-lts\n  KERNEL /boot/x86_64/vmlinuz-lts\n"
                    "  APPEND initrd=/boot/x86_64/initramfs-lts.img %s\n" % CMDLINE)

    # grub (UEFI)
    with open(os.path.join(iso, "boot/grub/grub.cfg"), "w") as f:
        f.write("set default=0\nset timeout=5\n"
                "menuentry 'Pasteque Linux (live)' {\n"
                "  linux /boot/x86_64/vmlinuz-linux %s\n"
                "  initrd /boot/x86_64/initramfs-linux.img\n}\n" % CMDLINE)
        if have_lts:
            f.write("menuentry 'Pasteque Linux (live, noyau LTS de secours)' {\n"
                    "  linux /boot/x86_64/vmlinuz-lts %s\n"
                    "  initrd /boot/x86_64/initramfs-lts.img\n}\n" % CMDLINE)
    efiwork = os.path.join(WORK, "efiwork")
    shutil.rmtree(efiwork, ignore_errors=True)
    os.makedirs(os.path.join(efiwork, "EFI/BOOT"), exist_ok=True)
    modules = ("part_msdos part_gpt iso9660 fat ext2 normal configfile linux echo "
               "search search_fs_file loopback gzio all_video test halt reboot "
               "memdisk tar ls cat help").split()
    early = os.path.join(efiwork, "early.cfg")
    with open(early, "w") as f:
        f.write("search --set=root --file /boot/grub/grub.cfg\nset prefix=($root)/boot/grub\n")
    # SBAT OBLIGATOIRE : shim 15.8+ REJETTE un grubx64.efi sans section .sbat
    # (verifie en local : "No .sbat section data" -> Security Violation)
    sbat_csv = os.path.join(WORK, "sbat.csv")
    with open(sbat_csv, "w") as f:
        f.write("sbat,1,SBAT Version,sbat,1,https://github.com/rhboot/shim/blob/main/SBAT.md\n"
                "grub,5,Free Software Foundation,grub,2.12,https://www.gnu.org/software/grub/\n"
                "grub.pasteque,1,Pasteque Linux,grub,2.12,https://github.com/Haridas-V/Linux-Pasteque-OS\n")
    run([os.path.join(TROOT, "usr/bin/grub-mkimage"), "-O", "x86_64-efi",
         "-d", os.path.join(TROOT, "usr/lib/grub/x86_64-efi"),
         "-o", os.path.join(efiwork, "EFI/BOOT/BOOTX64.EFI"),
         "-c", early,
         "--sbat", sbat_csv,
         "-p", "(cd0)/boot/grub"] + modules)
    # le grub produit DOIT contenir une section .sbat, sinon shim le rejette sous SB
    _grub = open(os.path.join(efiwork, "EFI/BOOT/BOOTX64.EFI"), "rb").read()
    if b".sbat" not in _grub:
        raise RuntimeError("grubx64.efi sans section .sbat -> shim 15.8+ le rejetterait sous Secure Boot")
    # signe le grub EFI (l'etape secureboot a pu tourner avant la creation d'efiwork)
    if os.path.exists(os.path.join(WORK, "sb", "sb.key")):
        run([sys.executable, os.path.join(TOOLS, "sb_sign.py"), "--efi-only"], check=True)
        if not os.path.exists(os.path.join(WORK, "efiwork", "EFI/BOOT/grubx64.efi")):
            raise RuntimeError("grubx64.efi non signe -> Secure Boot incomplet")
    # Secure Boot : si le shim MS-signe est present, BOOTX64.EFI = shim (1er etage),
    # grub signe devient grubx64.efi (2e etage verifie contre MOK), mmx64.efi = MokManager
    shim = os.path.join(WORK, "shim", "shimx64.efi")
    mokmgr = os.path.join(WORK, "shim", "mmx64.efi")
    have_shim = os.path.exists(shim) and os.path.exists(os.path.join(WORK, "efiwork", "EFI/BOOT/grubx64.efi"))
    if have_shim:
        shutil.copy2(shim, os.path.join(efiwork, "EFI/BOOT/BOOTX64.EFI"))
        shutil.copy2(mokmgr, os.path.join(efiwork, "EFI/BOOT/mmx64.efi"))
        print("[build] Secure Boot: shim MS + grubx64.efi signe + MokManager embarques", flush=True)
    else:
        print("[build] shim absent ou grub non signe -> BOOTX64.EFI = grub direct (SB off requis)", flush=True)
    efi_img = os.path.join(iso, "boot/efi.img")
    # 1024 MiB : un FAT32 (noyau + initrd principal ET LTS embarques) valide exige >= 65525 clusters, sinon le pilote FAT d'EDK II refuse de monter l'image.
    # On y embarque kernel + initrd + grub.cfg : au boot UEFI depuis une cle USB flashee (Etcher/dd),
    # le firmware ne voit que la partition MBR 0xEF (cette image FAT) ; sans ces fichiers embarques,
    # grub tombe en "grub rescue: file '/boot/grub/grub.cfg' not found" sur certains firmwares.
    run(["dd", "if=/dev/zero", "of=" + efi_img, "bs=1M", "count=1024"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run([os.path.join(TROOT, "usr/sbin/mkfs.vfat"), "-F", "32", "-n", ISO_LABEL + "EFI", efi_img])
    run([os.path.join(TROOT, "usr/bin/mmd"), "-i", efi_img, "::/EFI", "::/EFI/BOOT",
         "::/boot", "::/boot/x86_64", "::/boot/grub"])
    run([os.path.join(TROOT, "usr/bin/mcopy"), "-i", efi_img,
         os.path.join(efiwork, "EFI/BOOT/BOOTX64.EFI"), "::/EFI/BOOT/BOOTX64.EFI"])
    for extra in ["grubx64.efi", "mmx64.efi"]:
        ep = os.path.join(efiwork, "EFI/BOOT", extra)
        if os.path.exists(ep):
            run([os.path.join(TROOT, "usr/bin/mcopy"), "-i", efi_img, ep, "::/EFI/BOOT/" + extra])
    for src, dst in [
        (os.path.join(iso, "boot/x86_64/vmlinuz-linux"), "::/boot/x86_64/vmlinuz-linux"),
        (os.path.join(iso, "boot/x86_64/initramfs-linux.img"), "::/boot/x86_64/initramfs-linux.img"),
        (os.path.join(iso, "boot/grub/grub.cfg"), "::/boot/grub/grub.cfg"),
    ] + ([
        (os.path.join(iso, "boot/x86_64/vmlinuz-lts"), "::/boot/x86_64/vmlinuz-lts"),
        (os.path.join(iso, "boot/x86_64/initramfs-lts.img"), "::/boot/x86_64/initramfs-lts.img"),
    ] if have_lts else []):
        run([os.path.join(TROOT, "usr/bin/mcopy"), "-i", efi_img, src, dst])

    # arbre EFI à la racine de l'ISO (boot USB hybride)
    shutil.copytree(os.path.join(WORK, "efiwork", "EFI"), os.path.join(iso, "EFI"), dirs_exist_ok=True)
    # ISO hybride
    os.makedirs(OUT, exist_ok=True)
    iso_out = os.path.join(OUT, "%s-%s.iso" % (ISO_NAME, os.environ.get("ISO_VERSION", "1.0")))
    if os.path.exists(iso_out):
        os.remove(iso_out)
    run([os.path.join(TROOT, "usr/bin/xorriso"), "-as", "mkisofs",
         "-iso-level", "3", "-r", "-J", "-joliet-long", "-V", ISO_LABEL,
         "-o", iso_out,
         "-eltorito-boot", "boot/isolinux/isolinux.bin",
         "-eltorito-catalog", "boot/isolinux/boot.cat",
         "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table",
         "-eltorito-alt-boot", "-e", "boot/efi.img", "-no-emul-boot",
         "-isohybrid-mbr", os.path.join(TROOT, "usr/lib/ISOLINUX/isohdpfx.bin"),
         iso])
    add_efi_mbr_partition(iso_out, efi_img)
    import hashlib
    h = hashlib.sha256()
    with open(iso_out, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    with open(iso_out + ".sha256", "w") as f:
        f.write("%s  %s\n" % (h.hexdigest(), os.path.basename(iso_out)))
    print("[build] ISO OK:", iso_out, os.path.getsize(iso_out) // 1024 // 1024, "MiB", flush=True)


def step_secureboot():
    """Secure Boot : shim signe Microsoft + grub/noyaux/modules signes (cle MOK embarquee).
    Non bloquant : si le shim ne peut pas etre telecharge, on signe quand meme
    grub/noyaux/modules et on retombe sur BOOTX64.EFI = grub (Secure Boot off requis)."""
    # STRICT : Secure Boot est une fonction annoncee -> tout composant doit etre
    # present et signe, sinon le build ECHOUE (pas de "succes" partiel).
    r = run([sys.executable, os.path.join(TOOLS, "fetch_shim.py")], check=False)
    if r.returncode != 0 or not os.path.exists(os.path.join(WORK, "shim", "shimx64.efi")):
        raise RuntimeError("shim Microsoft (shim-signed) introuvable -> impossible de produire une ISO Secure Boot")
    # VERIF : le shim DOIT etre signe (table de certificats PE non vide), sinon le
    # firmware le rejette sous Secure Boot (Access Denied au chargement de Boot0001)
    sys.path.insert(0, TOOLS)
    from fetch_shim import pe_signed
    if not pe_signed(open(os.path.join(WORK, "shim", "shimx64.efi"), "rb").read()):
        raise RuntimeError("shimx64.efi NON SIGNE (mauvaise variante du paquet) -> rejete sous Secure Boot")
    if not os.path.exists(os.path.join(WORK, "shim", "mmx64.efi")):
        raise RuntimeError("MokManager (mmx64.efi) introuvable avec le shim")
    run([sys.executable, os.path.join(TOOLS, "sb_sign.py")], check=True)   # exit 1 si signature incomplete
    for f in ("usr/share/pasteque/mok/Pasteque.der", "usr/share/pasteque/mok/FINGERPRINT.txt"):
        if not os.path.exists(os.path.join(ROOTFS, f)):
            raise RuntimeError("cle MOK non embarquee: " + f)
    print("[build] Secure Boot: shim+MokManager presents, EFI/noyaux/modules signes, MOK embarque", flush=True)


STEPS = {
    "tools": step_tools,
    "bootstrap": step_bootstrap,
    "install": step_install,
    "extras": step_extras,
    "aur": step_aur,
    "initramfs": step_initramfs,
    "iso": step_iso,
    "secureboot": step_secureboot,
    "all": lambda: [step_tools(), step_bootstrap(), step_install(), step_aur(), step_extras(), step_secureboot(), step_initramfs(), step_iso()],
}

if __name__ == "__main__":
    steps = sys.argv[1:] or ["all"]
    for s in steps:
        STEPS[s]()
