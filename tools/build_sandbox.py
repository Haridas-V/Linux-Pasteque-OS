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

CMDLINE = "archisolabel=%s archisobasedir=arch %s" % (ISO_LABEL, EXTRA_CMDLINE)

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
    add_module sr_mod cdrom ahci sd_mod nvme loop squashfs isofs overlay vfat fat ext4 btrfs xfs ntfs3 \\
        usb-storage uas xhci-pci xhci-hcd ehci-pci uhci-hcd virtio_blk virtio_scsi virtio_net
}
"""

HOOK_RUNTIME = """#!/usr/bin/ash
run_hook() {
    local m
    for m in sr_mod cdrom ahci sd_mod nvme loop squashfs isofs overlay vfat fat ext4 btrfs xfs ntfs3 \\
        usb-storage uas xhci-pci xhci-hcd ehci-pci uhci-hcd virtio_blk virtio_scsi virtio_net; do
        modprobe "$m" 2>/dev/null
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
    subprocess.run(cmd, check=True, env=tool_env(), **kw)


def chroot(cmd, **kw):
    run([os.path.join(TOOLS, "chroot.sh"), ROOTFS] + cmd, **kw)


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
    chroot(["/usr/bin/pacman", "--config", "/etc/pacman.conf.build",
            "-Sy", "--noconfirm", "--needed", "--overwrite", "*"] + pkgs)
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




def _fetch_aur_pkgbuild(pkgbase, dest):
    url = "https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h=%s" % pkgbase
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "pasteque-build/1.0"})
    data = urllib.request.urlopen(req, timeout=60).read().decode()
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "PKGBUILD"), "w") as f:
        f.write(data)
    return data


def _pkgbuild_deps(pkgbuild_text):
    import re
    deps = []
    for key in ("depends", "makedepends", "checkdepends"):
        for m in re.finditer(r"^%s=\((.*?)\)" % key, pkgbuild_text, re.M | re.S):
            for d in m.group(1).split():
                d = re.split(r"[<>=:]", d, 1)[0].strip().strip("'\"")
                if d:
                    deps.append(d)
    return deps


def step_aur():
    """Compile les paquets AUR (packages-aur/*) en chroot et les installe."""
    aur_root = os.path.join(WORK, "aur-build")
    os.makedirs(aur_root, exist_ok=True)
    for pkgbase in sorted(os.listdir(os.path.join(REPO, "packages-aur"))):
        src_dir = os.path.join(aur_root, pkgbase)
        pb = _fetch_aur_pkgbuild(pkgbase, src_dir)
        deps = _pkgbuild_deps(pb)
        if deps:
            print("[aur] deps de build:", " ".join(deps), flush=True)
            chroot(["/usr/bin/pacman", "--config", "/etc/pacman.conf.build", "-S",
                    "--noconfirm", "--needed", "--overwrite", "*", "--asdeps"] + deps)
        # user builder + makepkg
        chroot(["/bin/bash", "-c",
                "id builder 2>/dev/null || useradd -m builder; "
                "mkdir -p /build/%s && cp /dev/null /build/%s/.keep" % (pkgbase, pkgbase)])
        # copier le PKGBUILD dans le chroot
        shutil.copy2(os.path.join(src_dir, "PKGBUILD"), os.path.join(ROOTFS, "build", pkgbase, "PKGBUILD"))
        chroot(["/bin/bash", "-c",
                "chown -R builder:builder /build/%s && "
                "su builder -c 'cd /build/%s && HOME=/home/builder makepkg -sf --noconfirm -d'" % (pkgbase, pkgbase)])
        built = glob.glob(os.path.join(ROOTFS, "build", pkgbase, "*.pkg.tar.zst"))
        built = [b for b in built if not b.endswith(".src.tar.gz")]
        if not built:
            raise RuntimeError("[aur] aucun paquet compilé pour %s" % pkgbase)
        for b in built:
            chroot(["/usr/bin/pacman", "--config", "/etc/pacman.conf.build", "-U",
                    "--noconfirm", "--overwrite", "*", "/build/%s/%s" % (pkgbase, os.path.basename(b))])
        print("[aur] %s installé: %s" % (pkgbase, [os.path.basename(b) for b in built]), flush=True)

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


def step_iso():
    iso = os.path.join(WORK, "iso")
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
                            _t.extract(_m, ROOTFS, filter="fully_trusted")
                            _p = os.path.join(ROOTFS, "usr/lib/dbus-daemon-launch-helper")
                            os.chmod(_p, 0o4755)
        except Exception as e:
            print("[iso] dbus helper:", e, flush=True)
    # squashfs de l'airootfs
    excl = ["-e", "boot", "dev", "proc", "sys", "tmp", "run", "mnt", "media",
            "var/cache/pacman", "var/lib/pacman", "var/log", "root", "home",
            "etc/mtab"]
    run([os.path.join(TROOT, "usr/bin/mksquashfs"), ROOTFS,
         os.path.join(iso, "arch/x86_64/airootfs.sfs"),
         "-comp", "xz", "-b", "1M", "-Xbcj", "x86",
         "-processors", str(os.cpu_count() or 4), "-noappend", "-no-progress", "-all-root"] + excl)

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

    # grub (UEFI)
    with open(os.path.join(iso, "boot/grub/grub.cfg"), "w") as f:
        f.write("set default=0\nset timeout=5\n"
                "menuentry 'Pasteque Linux (live)' {\n"
                "  linux /boot/x86_64/vmlinuz-linux %s\n"
                "  initrd /boot/x86_64/initramfs-linux.img\n}\n" % CMDLINE)
    efiwork = os.path.join(WORK, "efiwork")
    shutil.rmtree(efiwork, ignore_errors=True)
    os.makedirs(os.path.join(efiwork, "EFI/BOOT"), exist_ok=True)
    modules = ("part_msdos part_gpt iso9660 fat ext2 normal configfile linux echo "
               "search search_fs_file loopback gzio all_video test halt reboot "
               "memdisk tar ls cat help").split()
    run([os.path.join(TROOT, "usr/bin/grub-mkimage"), "-O", "x86_64-efi",
         "-d", os.path.join(TROOT, "usr/lib/grub/x86_64-efi"),
         "-o", os.path.join(efiwork, "EFI/BOOT/BOOTX64.EFI"),
         "-p", "(cd0)/boot/grub"] + modules)
    efi_img = os.path.join(iso, "boot/efi.img")
    run(["dd", "if=/dev/zero", "of=" + efi_img, "bs=1M", "count=16"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run([os.path.join(TROOT, "usr/sbin/mkfs.vfat"), "-F", "32", "-n", ISO_LABEL + "EFI", efi_img])
    run([os.path.join(TROOT, "usr/bin/mmd"), "-i", efi_img, "::/EFI", "::/EFI/BOOT"])
    run([os.path.join(TROOT, "usr/bin/mcopy"), "-i", efi_img,
         os.path.join(efiwork, "EFI/BOOT/BOOTX64.EFI"), "::/EFI/BOOT/BOOTX64.EFI"])

    # ISO hybride
    os.makedirs(OUT, exist_ok=True)
    iso_out = os.path.join(OUT, "%s-%s.iso" % (ISO_NAME, os.environ.get("ISO_VERSION", "dev")))
    run([os.path.join(TROOT, "usr/bin/xorriso"), "-as", "mkisofs",
         "-r", "-J", "-joliet-long", "-V", ISO_LABEL,
         "-o", iso_out,
         "-eltorito-boot", "boot/isolinux/isolinux.bin",
         "-eltorito-catalog", "boot/isolinux/boot.cat",
         "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table",
         "-eltorito-alt-boot", "-e", "boot/efi.img", "-no-emul-boot",
         "-isohybrid-mbr", os.path.join(TROOT, "usr/lib/ISOLINUX/isohdpfx.bin"),
         iso])
    import hashlib
    h = hashlib.sha256()
    with open(iso_out, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    with open(iso_out + ".sha256", "w") as f:
        f.write("%s  %s\n" % (h.hexdigest(), os.path.basename(iso_out)))
    print("[build] ISO OK:", iso_out, os.path.getsize(iso_out) // 1024 // 1024, "MiB", flush=True)


STEPS = {
    "tools": step_tools,
    "bootstrap": step_bootstrap,
    "install": step_install,
    "extras": step_extras,
    "aur": step_aur,
    "initramfs": step_initramfs,
    "iso": step_iso,
    "all": lambda: [step_tools(), step_bootstrap(), step_install(), step_aur(), step_extras(), step_initramfs(), step_iso()],
}

if __name__ == "__main__":
    steps = sys.argv[1:] or ["all"]
    for s in steps:
        STEPS[s]()
