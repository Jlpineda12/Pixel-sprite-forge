"""Real-world use cases, baked end to end in headless Blender.

    blender -b --factory-startup --python tests/test_use_cases.py
    python tests/test_use_cases.py            # with the `bpy` pip module

UC1  RPG hero with an ARMATURE: idle / walk / attack, 8 directions, mirror,
     PICO-8, packed sheet, normal map, GIFs, feet pivot.
UC2  Side-scroller: 2 directions, side view, custom Lospec .hex palette,
     Floyd–Steinberg.
UC3  Root motion: a runner that travels 4 m; "follow target" keeps it centered.
UC4  Isometric static prop: 8 views of a house, NES palette, grid layout.
UC5  Previews: live-preview path with the attack action selected.

Pass --keep to copy the generated GIFs into docs/use-cases/.
"""
import json
import os
import shutil
import sys
import tempfile
import time

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, HERE, os.path.join(HERE, 'use_cases')]

import pixel_sprite_forge as psf  # noqa: E402
import scenes  # noqa: E402
from _load import load  # noqa: E402
from pixel_sprite_forge import baker  # noqa: E402

_, palettes, packer = load()
results = []
KEEP = '--keep' in sys.argv
DOCS = os.path.join(ROOT, 'docs', 'use-cases')


def check(cond, name):
    results.append((bool(cond), name))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")


def bake(s, name):
    out = tempfile.mkdtemp(prefix=f'psf_{name}_')
    s.output_dir = out + os.sep
    s.base_name = name
    calls = {'n': 0}
    real = baker.render_color

    def counting(scene, path):
        calls['n'] += 1
        return real(scene, path)
    baker.render_color = counting
    t = time.time()
    try:
        res = bpy.ops.pixel_forge.bake()
    finally:
        baker.render_color = real
    dt = time.time() - t
    doc = json.load(open(os.path.join(out, f'{name}.json'))) if os.path.exists(os.path.join(out, f'{name}.json')) else None
    sheet = packer.read_png(os.path.join(out, f'{name}.png')) if doc else None
    print(f'    → {calls["n"]} renders, {dt:.1f}s, salida {out}')
    return res, out, doc, sheet, calls['n']


def cell(doc, sheet, key):
    """Rebuilds the full (untrimmed) cell of a frame from the JSON metadata."""
    f = doc['frames'][key]
    fr, src, size = f['frame'], f['spriteSourceSize'], f['sourceSize']
    out = np.zeros((size['h'], size['w'], 4), np.float32)
    out[src['y']:src['y'] + src['h'], src['x']:src['x'] + src['w']] = \
        sheet[fr['y']:fr['y'] + fr['h'], fr['x']:fr['x'] + fr['w']]
    return out


RED = np.array([1.0, 0.0, 77 / 255])  # PICO-8 red, where the emissive "nose" lands


def red_pixels(c, tol=0.25):
    m = (np.abs(c[..., :3] - RED).sum(-1) < tol) & (c[..., 3] > 0)
    return m


def centroid(c):
    ys, xs = np.nonzero(c[..., 3] > 0)
    return (xs.mean(), ys.mean()) if len(xs) else (np.nan, np.nan)


def keep(src, dst):
    if KEEP:
        os.makedirs(DOCS, exist_ok=True)
        shutil.copy(src, os.path.join(DOCS, dst))


# ---------------------------------------------------------------------------
def uc1_armature_rpg():
    print('\nUC1 · Héroe RPG con armature (idle / walk / attack, 8 dir, espejo)')
    arm = scenes.armature_hero()
    s = bpy.context.scene.pixel_forge
    s.target = arm
    bpy.ops.pixel_forge.apply_preset(preset='PICO8')
    s.resolution, s.supersample, s.engine = '48', '2', 'CYCLES'
    s.directions, s.mirror_directions = '8', True
    s.frame_step, s.fps = 4, 10
    s.layout, s.export_normals, s.export_gifs, s.gif_scale = 'PACKED', True, True, 3
    bpy.ops.pixel_forge.detect_actions()
    names = sorted(a.name for a in s.anims)
    check(names == ['attack', 'idle', 'walk'], f'detecta las 3 acciones del armature {names}')
    res, out, doc, sheet, renders = bake(s, 'hero')
    check(res == {'FINISHED'}, 'horneado completo')
    expected = (5 + 5 + 4) * 8
    check(len(doc['frames']) == expected, f'{expected} frames (3 acciones × 8 direcciones)')
    check(renders == (5 + 5 + 4) * 5, f'espejo: solo {renders} renders para {expected} frames')
    check(len(doc['animations']) == 24, '24 animaciones acción_dirección')

    w0, w2 = cell(doc, sheet, 'walk_S_000'), cell(doc, sheet, 'walk_S_002')
    check(not np.array_equal(w0[..., 3], w2[..., 3]), 'walk: las piernas se mueven entre frames')
    a1, i0 = cell(doc, sheet, 'attack_E_001'), cell(doc, sheet, 'idle_E_000')
    check(not np.array_equal(a1[..., 3], i0[..., 3]), 'attack: el brazo cambia la silueta')

    e, wv = cell(doc, sheet, 'walk_E_000'), cell(doc, sheet, 'walk_W_000')
    check(np.array_equal(e[..., 3] > 0, (wv[..., 3] > 0)[:, ::-1]), 'W es el espejo exacto de E (silueta)')
    ex = np.nonzero(red_pixels(e))[1]
    sx_n = red_pixels(cell(doc, sheet, 'walk_N_000')).sum()
    sx_s = red_pixels(cell(doc, sheet, 'walk_S_000')).sum()
    check(len(ex) and ex.mean() > 24, 'E: la nariz apunta a la derecha')
    check(sx_s > sx_n, 'S de frente / N de espaldas')

    piv = [f['pivot'] for f in doc['frames'].values()]
    ys = [p['y'] for p in piv]
    check(0.6 < np.mean(ys) < 1.0 and np.ptp(ys) < 0.02, f'pivote de los pies estable (y≈{np.mean(ys):.2f})')

    gifs = sorted(os.listdir(os.path.join(out, 'hero_gifs')))
    check(len(gifs) == 24, f'{len(gifs)} GIF animados')
    from PIL import Image
    g = Image.open(os.path.join(out, 'hero_gifs', 'walk_SE.gif'))
    check(g.n_frames == 5 and g.size == (48 * 3, 48 * 3), f'GIF walk_SE: {g.n_frames} frames, {g.size[0]}px')
    nrm = packer.read_png(os.path.join(out, 'hero_n.png'))
    check(np.array_equal(nrm[..., 3] > 0, sheet[..., 3] > 0), 'normal map alineado')
    check(arm.animation_data.action.name == 'idle', 'restaura la acción original del armature')
    keep(os.path.join(out, 'hero_gifs', 'walk_SE.gif'), 'rpg-walk-SE.gif')
    keep(os.path.join(out, 'hero_gifs', 'attack_E.gif'), 'rpg-attack-E.gif')
    keep(os.path.join(out, 'hero_gifs', 'idle_S.gif'), 'rpg-idle-S.gif')
    keep(os.path.join(out, 'hero.png'), 'rpg-sheet-packed.png')

    # UC5 rides on this scene: preview with the attack action selected
    print('\nUC5 · Vista previa con la acción "attack" seleccionada')
    s.anims_index = [a.name for a in s.anims].index('attack')
    bpy.context.scene.frame_set(5)
    s.preview_direction = 'E'
    res = bpy.ops.pixel_forge.preview()
    img = bpy.data.images.get('PSF Preview')
    check(res == {'FINISHED'} and img is not None, 'vista previa del ataque generada')


def uc2_side_scroller():
    print('\nUC2 · Plataformas: 2 direcciones, vista lateral, paleta .hex de Lospec')
    arm = scenes.armature_hero()
    s = bpy.context.scene.pixel_forge
    s.target = arm
    pal_path = os.path.join(tempfile.mkdtemp(), 'ice-cream-gb.hex')
    open(pal_path, 'w').write('7c3f58\neb6b6f\nf9a875\nfff6d3\n')  # 4-color Lospec-style palette
    s.palette, s.palette_file = 'FILE', pal_path
    s.dither, s.dither_strength = 'FLOYD', 0.8
    s.resolution, s.supersample, s.engine = '32', '2', 'CYCLES'
    s.directions, s.camera_view = '2', 'SIDE'
    s.anim_source, s.scene_anim_name = 'SCENE', 'walk'
    arm.animation_data.action = bpy.data.actions['walk']
    s.frame_step, s.layout, s.export_normals = 4, 'GRID', False
    s.export_gifs, s.gif_scale = True, 4
    check(len(s.swatches) == 4, 'carga la paleta .hex (4 muestras en el panel)')
    res, out, doc, sheet, _ = bake(s, 'side')
    check(set(doc['animations']) == {'walk_E', 'walk_W'}, 'solo E y W')
    pal = {tuple(np.round(c * 255).astype(int)) for c in palettes.load_palette_file(pal_path)}
    used = {tuple(np.round(c * 255).astype(int)) for c in sheet[sheet[..., 3] > 0][:, :3]}
    check(used <= pal, f'solo los 4 colores del archivo ({len(used)} usados)')
    n = len(range(1, bpy.context.scene.frame_end + 1, 4))
    check(sheet.shape[:2] == (2 * 33 + 1, n * 33 + 1), f'cuadrícula {n}×2 ({sheet.shape[1]}×{sheet.shape[0]})')
    keep(os.path.join(out, 'side_gifs', 'walk_E.gif'), 'side-walk-E.gif')


def uc3_root_motion():
    print('\nUC3 · Root motion: corredor que avanza 4 m')
    stats = {}
    for follow in (False, True):
        body = scenes.moving_cube()
        s = bpy.context.scene.pixel_forge
        s.target = body
        s.palette, s.dither = 'PICO8', 'NONE'
        s.resolution, s.supersample, s.engine = '32', '1', 'CYCLES'
        s.directions, s.camera_view = '2', 'SIDE'
        s.follow_target, s.frame_step = follow, 4
        s.export_normals, s.export_gifs, s.gif_scale = False, True, 4
        res, out, doc, sheet, _ = bake(s, 'runner')
        cx = [centroid(cell(doc, sheet, f'anim_E_{i:03d}'))[0] for i in range(5)]
        stats[follow] = (np.ptp(cx), s.ortho_scale)
        keep(os.path.join(out, 'runner_gifs', 'anim_E.gif'), f'runner-follow-{"on" if follow else "off"}.gif')
        print(f'    follow={follow}: centroide x {np.round(cx, 1)} · escala orto {s.ortho_scale:.2f}')
    check(stats[True][0] <= 1.0, f'con "seguir": queda centrado (variación {stats[True][0]:.1f}px)')
    check(stats[False][0] > 8, f'sin "seguir": se sale del centro ({stats[False][0]:.1f}px)')
    check(stats[True][1] < stats[False][1] / 2, 'con "seguir": encuadre mucho más ajustado (sprite más grande)')


def uc4_iso_prop():
    print('\nUC4 · Prop isométrico estático (casa) en 8 vistas')
    house = scenes.iso_prop()
    s = bpy.context.scene.pixel_forge
    s.target = house
    bpy.ops.pixel_forge.apply_preset(preset='NES')
    s.resolution, s.supersample, s.engine = '48', '2', 'CYCLES'
    s.directions, s.camera_view, s.mirror_directions = '8', 'ISOMETRIC', False
    s.anim_source, s.scene_anim_name = 'SCENE', 'idle'
    s.layout, s.export_normals, s.light_bands = 'GRID', False, 0
    res, out, doc, sheet, _ = bake(s, 'house')
    check(len(doc['frames']) == 8, '8 vistas de 1 frame')
    def door(d):
        c = cell(doc, sheet, f'idle_{d}_000')
        blue = (c[..., 2] > 0.6) & (c[..., 0] < 0.5) & (c[..., 3] > 0)
        return int(blue.sum())
    counts = {d: door(d) for d in ('S', 'N', 'E', 'W')}
    print(f'    pixeles de la puerta: {counts}')
    check(counts['S'] > counts['N'] and counts['S'] > 0, 'la puerta se ve desde S y no desde N')
    check(counts['N'] == 0, 'desde N la puerta queda oculta')
    check(sheet.shape[:2] == (8 * 49 + 1, 1 * 49 + 1), 'cuadrícula de 8 filas')
    keep(os.path.join(out, 'house.png'), 'iso-house-8.png')
    s.export_gifs = False


def main():
    psf.register()
    t = time.time()
    uc1_armature_rpg()
    uc2_side_scroller()
    uc3_root_motion()
    uc4_iso_prop()
    psf.unregister()
    ok = sum(1 for r in results if r[0])
    print(f'\n{ok}/{len(results)} verificaciones OK en {time.time() - t:.0f}s')
    return len(results) - ok


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
