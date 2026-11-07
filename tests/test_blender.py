"""End-to-end test inside real Blender (headless).

    blender -b --factory-startup --python tests/test_blender.py
or with the `bpy` pip module:
    python tests/test_blender.py

Builds a tiny character (blue body + red nose pointing at -Y) with two
actions, bakes 8 directions and checks files, palette, directions, normals
and that the user's scene settings are restored.
"""
import json
import os
import sys
import tempfile

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f'  PASS  {name}')
    else:
        failed += 1
        print(f'  FAIL  {name}')


def material(name, color, emit=False):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)   # Workbench shows the Viewport Display colour
    if not getattr(m, 'use_nodes', True):
        m.use_nodes = True
    nt = m.node_tree
    if emit:
        nt.nodes.clear()
        e = nt.nodes.new('ShaderNodeEmission')
        e.inputs['Color'].default_value = (*color, 1)
        o = nt.nodes.new('ShaderNodeOutputMaterial')
        nt.links.new(e.outputs[0], o.inputs[0])
    else:
        nt.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*color, 1)
    return m


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, 9
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 4
    sc.cycles.device = 'CPU'
    world = bpy.data.worlds.new('W')
    sc.world = world
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.5))
    body = bpy.context.active_object
    body.name = 'Hero'
    body.data.materials.append(material('Body', (0.1, 0.3, 0.9)))
    bpy.ops.mesh.primitive_cube_add(size=0.35, location=(0, -0.65, 0.6))
    nose = bpy.context.active_object
    nose.name = 'Nose'
    nose.data.materials.append(material('NoseMat', (1, 0, 0.1), emit=True))
    nose.parent = body
    nose.matrix_parent_inverse = body.matrix_world.inverted()
    bpy.ops.object.light_add(type='SUN', location=(2, -3, 5))
    bpy.context.active_object.data.energy = 4

    # two actions: walk (bounce) and attack (lunge)
    body.animation_data_create()
    for name, path, idx, values in (('walk', 'location', 2, [0.5, 0.8, 0.5]),
                                    ('attack', 'location', 1, [0.0, -0.3, 0.0])):
        act = bpy.data.actions.new(name)
        act.use_fake_user = True
        body.animation_data.action = act
        for f, v in zip((1, 5, 9), values):
            loc = list(body.location)
            loc[idx] = v
            body.location = loc
            body.keyframe_insert(path, index=idx, frame=f)
        body.location = (0, 0, 0.5)
    body.animation_data.action = bpy.data.actions['walk']
    return body


def main():
    import pixel_sprite_forge as psf
    from _load import load
    imaging, palettes, packer = load()
    psf.register()
    body = build_scene()
    sc = bpy.context.scene
    s = sc.pixel_forge
    out = tempfile.mkdtemp(prefix='psf_test_')

    s.target = body
    s.directions = '8'
    s.resolution = '32'
    s.supersample = '2'
    s.palette = 'PICO8'
    s.dither = 'BAYER4'
    s.engine = 'CYCLES'
    s.frame_step = 4
    s.output_dir = out + os.sep
    s.base_name = 'hero'
    s.export_normals = True
    bpy.ops.pixel_forge.detect_actions()
    check(len(s.anims) == 2, 'detecta 2 acciones (walk, attack)')
    check(len(s.swatches) == 0 or len(s.swatches) == 16, 'muestras de paleta')

    engine_before = sc.render.engine
    view_before = sc.view_settings.view_transform
    res = bpy.ops.pixel_forge.bake()
    check(res == {'FINISHED'}, 'bake termina')

    files = set(os.listdir(out))
    for f in ('hero.png', 'hero_n.png', 'hero.json', 'hero_frames.tres', 'hero_canvas.tres', 'hero_frames_lit.tres'):
        check(f in files, f'genera {f}')

    doc = json.load(open(os.path.join(out, 'hero.json')))
    n_frames = 2 * 8 * len(range(1, 10, 4))
    check(len(doc['frames']) == n_frames, f'{n_frames} frames en el JSON')
    check(len(doc['animations']) == 16, '16 animaciones (2 acciones x 8 direcciones)')

    sheet = packer.read_png(os.path.join(out, 'hero.png'))
    pal = {tuple(np.round(c * 255).astype(int)) for c in palettes.builtin_palette('PICO8')}
    used = {tuple(np.round(c * 255).astype(int)) for c in sheet[sheet[..., 3] > 0][:, :3]}
    check(used <= pal, f'solo colores PICO-8 ({len(used)} usados)')
    check(sheet.shape[1] == 3 * 33 + 1 and sheet.shape[0] == 16 * 33 + 1, f'tamaño de la hoja {sheet.shape[1]}x{sheet.shape[0]}')

    def cell(anim, d, i=0):
        fr = doc['frames'][f'{anim}_{d}_{i:03d}']['frame']
        return sheet[fr['y']:fr['y'] + fr['h'], fr['x']:fr['x'] + fr['w']]

    red = np.array([1.0, 0.0, 77 / 255])

    def nose_x(c):
        m = (np.abs(c[..., :3] - red).sum(-1) < 0.05) & (c[..., 3] > 0)
        return (np.nonzero(m)[1].mean() if m.any() else None), int(m.sum())

    ex, _ = nose_x(cell('walk', 'E'))
    wx, _ = nose_x(cell('walk', 'W'))
    sx, sn = nose_x(cell('walk', 'S'))
    _, nn = nose_x(cell('walk', 'N'))
    print(f'    nariz x: E={ex} W={wx} S={sx}; pixeles rojos S={sn} N={nn}')
    check(ex is not None and ex > 16, 'E: el personaje mira a la derecha')
    check(wx is not None and wx < 16, 'W: el personaje mira a la izquierda')
    check(sx is not None and 10 < sx < 22 and sn > nn, 'S: mira a la cámara; N: de espaldas')

    nrm = packer.read_png(os.path.join(out, 'hero_n.png'))
    check(np.array_equal(nrm[..., 3] > 0, sheet[..., 3] > 0), 'normal map alineado con el sprite')
    fr = doc['frames']['walk_S_000']['frame']
    blk = nrm[fr['y']:fr['y'] + fr['h'], fr['x']:fr['x'] + fr['w']]
    opaque = blk[blk[..., 3] > 0][:, :3]
    check(opaque[:, 2].mean() > 0.6, f'normales hacia la cámara (z medio {opaque[:, 2].mean():.2f})')

    check(sc.render.engine == engine_before, 'restaura el motor de render')
    check(sc.view_settings.view_transform == view_before, 'restaura la transformación de color')
    check(sc.render.resolution_x == 1920 or sc.render.resolution_x == 32, 'resolución restaurada/definida')

    tres = open(os.path.join(out, 'hero_frames.tres')).read()
    check('&"walk_S"' in tres and '&"attack_NW"' in tres, 'SpriteFrames de Godot con animaciones por dirección')

    s.preview_direction = 'E'
    res = bpy.ops.pixel_forge.preview()
    img = bpy.data.images.get('PSF Preview')
    check(res == {'FINISHED'} and img is not None and img.size[0] >= 32, 'vista previa genera imagen')

    for key in ('GAMEBOY', 'NES', 'PICO8', 'C64', 'MODERN', 'HD'):
        bpy.ops.pixel_forge.apply_preset(preset=key)
    check(s.palette == 'AUTO' and s.resolution == '128', 'presets aplican estilo')

    psf.unregister()
    check(not hasattr(bpy.types.Scene, 'pixel_forge'), 'unregister limpio')
    print(f'\n{passed} PASS, {failed} FAIL  ·  salida en {out}')
    return failed


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
