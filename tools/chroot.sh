#!/usr/bin/env bash
# Run a command inside an Arch rootfs as (mapped) root, without real root.
# Usage: tools/chroot.sh <rootfs> <command...>
# Requires: unshare with user namespaces enabled.
set -euo pipefail
ROOTFS="$(readlink -f "$1")"
shift
[ -x "$ROOTFS/usr/bin/pacman" ] || { echo "rootfs not bootstrapped: $ROOTFS" >&2; exit 1; }
mkdir -p "$ROOTFS"/{dev,proc,tmp,var/lib/pacman,var/cache/pacman/pkg,var/log,etc}
cp -f /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
rm -f "$ROOTFS/etc/mtab"; cp /proc/mounts "$ROOTFS/etc/mtab"
[ -e "$ROOTFS/etc/nsswitch.conf" ] || printf 'passwd: files\ngroup: files\nshadow: files\nhosts: files dns\n' > "$ROOTFS/etc/nsswitch.conf"

exec unshare -rmpf bash -c '
  set -e
  R="$1"; shift
  mount -t tmpfs tmpfs "$R/proc"
  # /proc réel impossible en userns ici -> fichiers factices suffisants pour
  # les vérifications `mountpoint` de mkinitcpio & co.
  mkdir -p "$R/proc/self/fd"
  printf "29 0 0:29 / /dev rw,nosuid - tmpfs tmpfs rw\n30 0 0:30 / /proc rw,nosuid,nodev,noexec,relatime - proc proc rw\n31 0 0:31 / /sys rw,nosuid,nodev,noexec - sysfs sysfs rw\n" > "$R/proc/self/mountinfo"
  cp "$R/proc/self/mountinfo" "$R/proc/mounts"
  printf "BOOT_IMAGE=/boot/vmlinuz-linux\n" > "$R/proc/cmdline"
  printf "nodev\tsysfs\nnodev\tproc\n\text4\n\tbtrfs\n\tvfat\n\tiso9660\n\tsquashfs\n\toverlay\n" > "$R/proc/filesystems"
  printf "Linux version 6.12 (pasteque) #1 SMP\n" > "$R/proc/version"
  # /dev en tmpfs "nodev" en userns -> fichiers reguliers writables suffisants
  mount -t tmpfs tmpfs "$R/dev"
  for f in null zero full random urandom tty ptmx stdin stdout stderr; do
    rm -f "$R/dev/$f"; touch "$R/dev/$f"; chmod 666 "$R/dev/$f"
  done
  mkdir -p "$R/dev/pts" "$R/dev/shm" "$R/dev/fd"
  mount -t tmpfs tmpfs "$R/dev/shm"
  chmod 1777 "$R/tmp"
  exec chroot "$R" "$@"
' _ "$ROOTFS" "$@"
