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
HOOK_INSTALL = """#!/usr/bin/bash
build() {
    add_runscript
    add_module sr_mod cdrom ahci sd_mod nvme loop squashfs isofs overlay vfat fat ext4 btrfs xfs ntfs3  usb-storage uas xhci-pci xhci-hcd ehci-pci uhci-hcd virtio_blk virtio_scsi virtio_net
}
"""

HOOK_RUNTIME = """#!/usr/bin/ash
run_hook() {
    local m i
    for m in sr_mod cdrom ahci sd_mod nvme loop squashfs isofs overlay vfat fat ext4 btrfs xfs ntfs3  usb-storage uas xhci-pci xhci-hcd ehci-pci uhci-hcd virtio_blk virtio_scsi virtio_net; do
        modprobe "$m" 2>/dev/null
    done
    # nœuds loop pour le montage de la squashfs (devtmpfs ne les crée pas tous)
    [ -e /dev/loop-control ] || mknod /dev/loop-control c 10 237 2>/dev/null
    i=0
    while [ $i -lt 16 ]; do
        [ -e /dev/loop$i ] || mknod /dev/loop$i b 7 $i 2>/dev/null
        i=$((i+1))
    done
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
SigLevel = Never
LocalFileSigLevel = Never

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


def chroot(cmd, **kw):
    return run([os.path.join(TOOLS, "chroot.sh"), ROOTFS] + cmd, **kw)


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
    archrepo.bootstrap_pacman(ROOTFS, CACHE, extra=["ca-certificates"])
    os.makedirs(os.path.join(ROOTFS, "etc/pacman.d"), exist_ok=True)
    with open(os.path.join(ROOTFS, "etc/pacman.d/mirrorlist.build"), "w") as f:
        f.write("Server = %s/$repo/os/$arch\n" % MIRROR)
        f.write("Server = http://mirror.rackspace.com/archlinux/$repo/os/$arch\n")
    with open(os.path.join(ROOTFS, "etc/pacman.conf.build"), "w") as f:
        f.write(SANDBOX_PACMAN_CONF)


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
    # SSH desactive par defaut : retirer openssh si present, sinon masquer sshd
    chroot(["/bin/bash", "-c",
            "pacman --config /etc/pacman.conf.build -Rns --noconfirm openssh 2>/dev/null; "
            "if [ -e /usr/lib/systemd/system/sshd.service ]; then ln -sf /dev/null /etc/systemd/system/sshd.service; fi; true"])
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
    # conf pacman de production (celle livrée dans l'ISO)
    shutil.copy2(os.path.join(PROFILE, "pacman.conf"), os.path.join(ROOTFS, "etc/pacman.conf"))
    # locales
    chroot(["/bin/bash", "-c", "locale-gen 2>/dev/null || true"])
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
            req = urllib.request.Request(spec["src"], headers={"User-Agent": "pasteque-build/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r, open(tarball, "wb") as f:
                shutil.copyfileobj(r, f)
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
    chroot(["/bin/bash", "-c",
            "kv=$(ls /usr/lib/modules | head -1); ln -sf /usr/lib/modules/$kv/vmlinuz /boot/vmlinuz-linux"])
    # chroot sans /proc/self/fd : patch des substitutions de processus de mkinitcpio
    run([sys.executable, os.path.join(TOOLS, "patch_initcpio.py"),
         os.path.join(ROOTFS, "usr/lib/initcpio/functions")])
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
    chroot(["/usr/bin/mkinitcpio", "-c", "/etc/mkinitcpio.conf", "-k", "/boot/vmlinuz-linux", "-g", "/boot/initramfs-linux.img"])
    img = os.path.join(ROOTFS, "boot/initramfs-linux.img")
    assert os.path.exists(img), "initramfs manquante"
    print("[build] initramfs OK:", os.path.getsize(img) // 1024 // 1024, "MiB", flush=True)
    # noyau LTS de secours : symlink + initramfs dediee (entree GRUB de secours)
    chroot(["/bin/bash", "-c",
            "kvl=$(ls /usr/lib/modules | grep -i lts | head -1); "
            "if [ -n \"$kvl\" ]; then ln -sf /usr/lib/modules/$kvl/vmlinuz /boot/vmlinuz-lts; "
            "mkinitcpio -c /etc/mkinitcpio.conf -k /boot/vmlinuz-lts -g /boot/initramfs-lts.img; fi"])
    lts_img = os.path.join(ROOTFS, "boot/initramfs-lts.img")
    if os.path.exists(lts_img):
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


def step_iso():
    iso = os.path.join(WORK, "iso")
    sfs = os.path.join(iso, "arch/x86_64/airootfs.sfs")
    if not os.path.exists(sfs):
        shutil.rmtree(iso, ignore_errors=True)
    for d in ["arch/x86_64", "boot/x86_64", "boot/isolinux", "boot/grub"]:
        os.makedirs(os.path.join(iso, d), exist_ok=True)
    kver_dir = sorted(glob.glob(os.path.join(ROOTFS, "usr/lib/modules/*")))[-1]
    kernel_src = os.path.join(ROOTFS, "boot/vmlinuz-linux")
    if not os.path.exists(kernel_src):
        kernel_src = os.path.join(kver_dir, "vmlinuz")
    shutil.copy2(kernel_src, os.path.join(iso, "boot/x86_64/vmlinuz-linux"))
    initrd_src = os.path.join(ROOTFS, "boot/initramfs-linux.img")
    assert os.path.exists(initrd_src), "initramfs manquante: lancez d'abord l'étape initramfs"
    shutil.copy2(initrd_src, os.path.join(iso, "boot/x86_64/initramfs-linux.img"))
    # noyau LTS de secours dans l'ISO aussi
    lts_kernel = os.path.join(ROOTFS, "boot/vmlinuz-lts")
    lts_initrd = os.path.join(ROOTFS, "boot/initramfs-lts.img")
    have_lts = os.path.exists(lts_kernel) and os.path.exists(lts_initrd)
    if have_lts:
        shutil.copy2(lts_kernel, os.path.join(iso, "boot/x86_64/vmlinuz-lts"))
        shutil.copy2(lts_initrd, os.path.join(iso, "boot/x86_64/initramfs-lts.img"))

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
    run([os.path.join(TROOT, "usr/bin/grub-mkimage"), "-O", "x86_64-efi",
         "-d", os.path.join(TROOT, "usr/lib/grub/x86_64-efi"),
         "-o", os.path.join(efiwork, "EFI/BOOT/BOOTX64.EFI"),
         "-c", early,
         "-p", "(cd0)/boot/grub"] + modules)
    # signe le grub EFI (l'etape secureboot a pu tourner avant la creation d'efiwork)
    if os.path.exists(os.path.join(WORK, "sb", "sb.key")):
        run([sys.executable, os.path.join(TOOLS, "sb_sign.py"), "--efi-only"], check=False)
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
    r = run([sys.executable, os.path.join(TOOLS, "fetch_shim.py")], check=False)
    if r.returncode != 0 or not os.path.exists(os.path.join(WORK, "shim", "shimx64.efi")):
        print("[build] shim indisponible (reseau ?) -> mode sans shim, SB off requis", flush=True)
    r = run([sys.executable, os.path.join(TOOLS, "sb_sign.py")], check=False)
    if r.returncode != 0:
        print("[build] sb_sign a echoue (non bloquant) -> ISO sans signature SB", flush=True)


STEPS = {
    "tools": step_tools,
    "bootstrap": step_bootstrap,
    "install": step_install,
    "extras": step_extras,
    "aur": step_aur,
    "initramfs": step_initramfs,
    "iso": step_iso,
    "secureboot": step_secureboot,
    "all": lambda: [step_tools(), step_bootstrap(), step_install(), step_aur(), step_extras(), step_initramfs(), step_secureboot(), step_iso()],
}

if __name__ == "__main__":
    steps = sys.argv[1:] or ["all"]
    for s in steps:
        STEPS[s]()
