# calamares (AUR)

Le PKGBUILD n'est pas stocké ici : il est téléchargé depuis l'AUR au moment du
build (`https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h=calamares`)
par `tools/build_sandbox.py` (étape `aur`), compilé en chroot (makepkg) puis
installé dans l'ISO. Calamares n'étant plus dans les dépôts officiels Arch,
c'est la source amont maintenance.
