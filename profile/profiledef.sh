#!/usr/bin/env bash
# Profil archiso de Pastèque Linux (édition No Frustration)

iso_name="pasteque"
iso_label="PASTEQUE"
iso_publisher="Pasteque Linux <https://github.com/Haridas-V/Linux-Pasteque-OS>"
iso_application="Pasteque Linux - edition No Frustration"
iso_version="$(date +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
# BIOS (syslinux, MBR hybride + El Torito) + UEFI (grub, ESP)
bootmodes=('bios.syslinux.mbr' 'bios.syslinux.eltorito' 'uefi-x64.grub.esp')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'xz' '-b' '1M' '-Xbcj' 'x86')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/etc/gshadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/usr/local/bin/pasteque-*"]="0:0:755"
)
