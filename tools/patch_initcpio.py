#!/usr/bin/env python3
"""Patch mkinitcpio's functions file for chroots without /proc/self/fd.

Bash process substitution `< <(cmd)` needs /dev/fd -> /proc/self/fd, unavailable
in our user-namespace chroot. Rewrite to temp files, preserving semantics:
  - single-line `read/mapfile ... < <(cmd)` -> 3 lines with a temp file
  - `done < <(cmd)` (loop redirection)      -> temp file created BEFORE the while
  - the multi-line kver_x86 read and the `if read ... < <(compgen)` case are
    handled explicitly.
Only applied to the BUILD rootfs (sandbox path); temp files work everywhere.
"""
import re
import sys

path = sys.argv[1]
lines = open(path).read().splitlines(keepends=True)
out = []
patched = 0
i = 0
single = re.compile(r'^(\s*)((?:read\b|mapfile\b)[^<]*?) < <\((.*)\)\s*(;.*)?$')
done_pat = re.compile(r'^(\s*)done < <\((.*)\)\s*$')
while_pat = re.compile(r'^\s*while\b')
while i < len(lines):
    line = lines[i].rstrip("\n")
    m = done_pat.match(line)
    if m and "<(" not in m.group(2):
        indent, cmd = m.group(1), m.group(2)
        j = len(out) - 1
        while j >= 0 and not while_pat.match(out[j]):
            j -= 1
        assert j >= 0, "while not found for: " + line
        out[j:j] = ['%s__PSF="$(mktemp)"\n' % indent,
                    '%s( %s ) > "$__PSF"\n' % (indent, cmd)]
        out.append('%sdone < "$__PSF"; rm -f "$__PSF"\n' % indent)
        patched += 1
        i += 1
        continue
    m = single.match(line)
    if m and "<(" not in m.group(3):
        indent, head, cmd, tail = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        out.append('%s__PSF="$(mktemp)"\n' % indent)
        out.append('%s( %s ) > "$__PSF"\n' % (indent, cmd))
        out.append('%s%s < "$__PSF"; rm -f "$__PSF"%s\n' % (indent, head, tail))
        patched += 1
        i += 1
        continue
    out.append(lines[i])
    i += 1
s = "".join(out)
# multi-line kver_x86
old_kver = """    read -r kver _ < \\
        <(dd if="$1" bs=1 count=127 skip=$((offset + 0x200)) 2>/dev/null)
"""
new_kver = """    __PSF="$(mktemp)"
    ( dd if="$1" bs=1 count=127 skip=$((offset + 0x200)) 2>/dev/null ) > "$__PSF"
    read -r kver _ < "$__PSF"; rm -f "$__PSF"
"""
if old_kver in s:
    s = s.replace(old_kver, new_kver)
    patched += 1
# if read ... < <(compgen ...) ; then
old_cg = 'if read -r fwfile < <(compgen -G "${fwpath}/${fw}?(.*)"); then'
new_cg = '__PSF2="$(mktemp)"; compgen -G "${fwpath}/${fw}?(.*)" > "$__PSF2"; if read -r fwfile < "$__PSF2"; then'
if old_cg in s:
    s = s.replace(old_cg, new_cg)
    patched += 1
open(path, "w").write(s)
print("patched %d process substitutions in %s" % (patched, path))
