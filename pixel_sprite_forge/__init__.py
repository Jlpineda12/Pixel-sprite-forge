# SPDX-License-Identifier: GPL-3.0-or-later
"""Pixel Sprite Forge — convierte modelos 3D animados en sprite sheets de pixel art.

Instalación (Blender 4.2+): Editar > Preferencias > Extensiones/Add-ons >
"Instalar desde disco" y elige el .zip. Panel: Vista 3D > barra lateral (N) >
pestaña "Pixel Forge".
"""

bl_info = {
    'name': 'Pixel Sprite Forge',
    'author': 'Jose Luis Pineda (Jlpineda12)',
    'version': (1, 0, 0),
    'blender': (4, 2, 0),
    'location': 'Vista 3D > Barra lateral (N) > Pixel Forge',
    'description': '3D animado → sprite sheets de pixel art en 8 direcciones con paletas, dithering, '
                   'contornos, normal maps y exportación a Godot / Unity / Phaser / PixiJS',
    'category': 'Render',
    'doc_url': 'https://github.com/Jlpineda12/pixel-sprite-forge',
}

if 'bpy' in locals():  # support "Reload Scripts"
    import importlib
    from . import palettes, imaging, packer, properties, rig, baker, operators, ui
    for m in (palettes, imaging, packer, properties, rig, baker, operators, ui):
        importlib.reload(m)

import bpy  # noqa: E402

from . import operators, properties, ui  # noqa: E402


def register():
    properties.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    properties.unregister()
