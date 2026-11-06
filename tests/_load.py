"""Loads the addon's pure-python modules without importing bpy (__init__.py)."""
import importlib.util
import os
import sys
import types

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pixel_sprite_forge')


def load():
    if 'pixel_sprite_forge' not in sys.modules:
        pkg = types.ModuleType('pixel_sprite_forge')
        pkg.__path__ = [ROOT]
        sys.modules['pixel_sprite_forge'] = pkg
    mods = {}
    for name in ('imaging', 'palettes', 'packer'):
        full = f'pixel_sprite_forge.{name}'
        if full not in sys.modules:
            spec = importlib.util.spec_from_file_location(full, os.path.join(ROOT, f'{name}.py'))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[full] = mod
            spec.loader.exec_module(mod)
        mods[name] = sys.modules[full]
    return mods['imaging'], mods['palettes'], mods['packer']
