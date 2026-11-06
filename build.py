#!/usr/bin/env python3
"""Builds dist/pixel_sprite_forge-<version>.zip, installable in Blender 4.2+
(Preferences > Add-ons > Install from Disk) as an extension or legacy add-on."""
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(ROOT, 'pixel_sprite_forge')
version = re.search(r'^version = "([^"]+)"', open(os.path.join(PKG, 'blender_manifest.toml')).read(), re.M).group(1)
os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
out = os.path.join(ROOT, 'dist', f'pixel_sprite_forge-{version}.zip')
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for name in sorted(os.listdir(PKG)):
        if name.endswith(('.py', '.toml')):
            z.write(os.path.join(PKG, name), f'pixel_sprite_forge/{name}')
    z.write(os.path.join(ROOT, 'LICENSE'), 'pixel_sprite_forge/LICENSE')
print(out)
