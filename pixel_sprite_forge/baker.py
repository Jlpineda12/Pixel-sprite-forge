# SPDX-License-Identifier: GPL-3.0-or-later
"""Renders every animation x direction x frame and runs the pixel pipeline."""
import os
import tempfile
import time

import bpy
import numpy as np

from . import gif, imaging, packer, palettes, rig

NORMAL_MAT = 'PSF_NormalPass'


# ---------------------------------------------------------------------------
# Settings snapshot (plain dict for the numpy pipeline)
# ---------------------------------------------------------------------------

def pipeline_settings(s):
    return {
        'supersample': int(s.supersample),
        'downsample_mode': s.downsample_mode,
        'alpha_threshold': s.alpha_threshold,
        'saturation': s.saturation,
        'contrast': s.contrast,
        'brightness': s.brightness,
        'light_bands': s.light_bands,
        'dither': s.dither,
        'dither_strength': s.dither_strength,
        'outline': s.outline,
        'outline_color': tuple(s.outline_color),
        'outline_adaptive': s.outline_adaptive,
        'outline_diagonal': s.outline_diagonal,
        'normal_flip_y': s.normal_flip_y,
    }


def resolve_palette(s, sample_frames=None):
    """Returns an (N, 3) array or None (no quantization)."""
    if s.palette == 'NONE':
        return None
    if s.palette == 'FILE':
        path = bpy.path.abspath(s.palette_file)
        if not s.palette_file or not os.path.isfile(path):
            raise RuntimeError('Selecciona un archivo de paleta válido (.hex, .pal o .gpl)')
        return palettes.load_palette_file(path)
    if s.palette == 'AUTO':
        if not sample_frames:
            return None
        px = np.concatenate([f[..., :3][f[..., 3] > 0] for f in sample_frames if (f[..., 3] > 0).any()] or
                            [np.zeros((0, 3), np.float32)])
        return palettes.kmeans_palette(px, s.auto_colors)
    return palettes.builtin_palette(s.palette)


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _engine_id(choice):
    available = _builtin_engines()
    if choice == 'EEVEE':
        # 4.2-4.x: BLENDER_EEVEE_NEXT · 5.x: BLENDER_EEVEE
        for cand in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
            if cand in available:
                return cand
    if choice == 'WORKBENCH':
        return 'BLENDER_WORKBENCH'
    if choice == 'CYCLES' and 'CYCLES' in available:
        return 'CYCLES'
    return None


def _builtin_engines():
    try:
        return {i.identifier for i in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}
    except Exception:  # pragma: no cover
        return set()


def _normal_material():
    mat = bpy.data.materials.get(NORMAL_MAT)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(NORMAL_MAT)
    if not getattr(mat, 'use_nodes', True):  # always True (and deprecated) in Blender 5
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    # World-space normals (same convention in Cycles, EEVEE and Workbench);
    # converted to camera space in numpy with the camera matrix.
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    vm = nt.nodes.new('ShaderNodeVectorMath')
    vm.operation = 'MULTIPLY_ADD'
    vm.inputs[1].default_value = (0.5, 0.5, 0.5)
    vm.inputs[2].default_value = (0.5, 0.5, 0.5)
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Strength'].default_value = 1.0
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(geo.outputs['Normal'], vm.inputs[0])
    nt.links.new(vm.outputs[0], em.inputs['Color'])
    nt.links.new(em.outputs[0], out.inputs['Surface'])
    return mat


class RenderState:
    """Saves the scene's render settings and restores them afterwards."""

    def __init__(self, scene, settings):
        self.scene, self.s = scene, settings

    def __enter__(self):
        sc, r = self.scene, self.scene.render
        self.saved = dict(
            engine=r.engine, rx=r.resolution_x, ry=r.resolution_y, pct=r.resolution_percentage,
            film=r.film_transparent, path=r.filepath, fmt=r.image_settings.file_format,
            cmode=r.image_settings.color_mode, depth=r.image_settings.color_depth,
            camera=sc.camera, frame=sc.frame_current,
            view=sc.view_settings.view_transform, look=sc.view_settings.look,
            exposure=sc.view_settings.exposure, gamma=sc.view_settings.gamma,
            override=bpy.context.view_layer.material_override,
            action=self._action(),
        )
        eng = _engine_id(self.s.engine)
        if eng:
            r.engine = eng
        shading = getattr(sc.display, 'shading', None)
        self.saved['wb_color'] = shading.color_type if shading else None
        if shading and r.engine == 'BLENDER_WORKBENCH':
            shading.color_type = 'MATERIAL'   # Viewport Display colour of each material
        r.film_transparent = True
        r.resolution_percentage = 100
        if self.s.standard_view:
            sc.view_settings.view_transform = 'Standard'
            try:
                sc.view_settings.look = 'None'
            except TypeError:
                pass
            sc.view_settings.exposure, sc.view_settings.gamma = 0.0, 1.0
        size = rig.cell_size(self.s) * int(self.s.supersample)
        r.resolution_x = r.resolution_y = size
        return self

    def _action(self):
        t = self.s.target
        if t is not None and t.animation_data is not None:
            return t.animation_data.action
        return None

    def __exit__(self, *exc):
        sc, r, v = self.scene, self.scene.render, self.saved
        if v.get('wb_color') and getattr(sc.display, 'shading', None):
            sc.display.shading.color_type = v['wb_color']
        r.engine = v['engine']
        r.resolution_x, r.resolution_y, r.resolution_percentage = v['rx'], v['ry'], v['pct']
        r.film_transparent, r.filepath = v['film'], v['path']
        r.image_settings.file_format = v['fmt']
        r.image_settings.color_mode = v['cmode']
        r.image_settings.color_depth = v['depth']
        sc.camera = v['camera']
        sc.view_settings.view_transform = v['view']
        sc.view_settings.look = v['look']
        sc.view_settings.exposure, sc.view_settings.gamma = v['exposure'], v['gamma']
        bpy.context.view_layer.material_override = v['override']
        t = self.s.target
        if t is not None and t.animation_data is not None and v['action'] is not None:
            assign_action(t, v['action'])
        sc.frame_set(v['frame'])
        return False


def assign_action(obj, action):
    if obj.animation_data is None:
        obj.animation_data_create()
    ad = obj.animation_data
    ad.action = action
    # Blender 4.4+ "slotted actions": make sure a slot is bound
    if hasattr(ad, 'action_slot') and action is not None and getattr(ad, 'action_slot', None) is None:
        slots = getattr(action, 'slots', [])
        for slot in slots:
            if getattr(slot, 'target_id_type', 'OBJECT') == 'OBJECT':
                ad.action_slot = slot
                break


def _load_pixels(path):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        buf = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        return buf.reshape(h, w, 4)[::-1].copy()  # bottom-up -> top-down
    finally:
        bpy.data.images.remove(img)


def render_color(scene, path):
    r = scene.render
    r.image_settings.file_format = 'PNG'
    r.image_settings.color_mode = 'RGBA'
    r.image_settings.color_depth = '8'
    r.filepath = path
    bpy.ops.render.render(write_still=True)
    return _load_pixels(path)


def render_normals(scene, path):
    """Camera-space normals (OpenGL style: +Z towards the viewer) via a world-normal
    material override rendered to linear EXR."""
    r = scene.render
    vl = bpy.context.view_layer
    prev = vl.material_override
    vl.material_override = _normal_material()
    prev_view = scene.view_settings.view_transform
    prev_engine = r.engine
    if r.engine == 'BLENDER_WORKBENCH':
        # Workbench ignores node materials (solid shading): bake the normal
        # pass with EEVEE (or Cycles) so the override material is evaluated
        r.engine = _engine_id('EEVEE') or 'CYCLES'
    try:
        r.image_settings.file_format = 'OPEN_EXR'
        r.image_settings.color_mode = 'RGBA'
        r.image_settings.color_depth = '32'
        r.filepath = path
        bpy.ops.render.render(write_still=True)
        px = _load_pixels(path)
    finally:
        vl.material_override = prev
        scene.view_settings.view_transform = prev_view
        r.engine = prev_engine
    n_world = px[..., :3] * 2.0 - 1.0
    # camera axes (columns): X = screen right, Y = screen up, Z = towards viewer
    bpy.context.view_layer.update()
    rot = np.array(scene.camera.matrix_world.to_3x3(), dtype=np.float32)
    n_cam = n_world @ rot
    return np.concatenate([n_cam, px[..., 3:4]], axis=-1)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def animation_jobs(context, s):
    """[(name, action_or_None, start, end, loop)]"""
    scene = context.scene
    if s.anim_source == 'LIST':
        jobs = [(a.name or 'anim', a.action, a.frame_start, a.frame_end, a.loop)
                for a in s.anims if a.enabled]
        if not jobs:
            raise RuntimeError('La lista de animaciones está vacía: usa "Detectar acciones" o añade una')
        return jobs
    act = s.target.animation_data.action if (s.target and s.target.animation_data) else None
    return [(s.scene_anim_name or 'anim', act, scene.frame_start, scene.frame_end, True)]


def frame_numbers(start, end, step):
    return list(range(start, end + 1, max(1, step)))


def bake(context, s, preview=None, report=None):
    """Renders every animation x direction x frame through the pixel pipeline.

    preview=(direction, frame): renders just that frame with the current
    action (fast path used by the live preview; reuses the existing rig).
    Returns (frames, palette, loops_by_anim)."""
    scene = context.scene
    if s.target is None:
        raise RuntimeError('Elige el objeto "Personaje" en el panel Pixel Sprite Forge')
    cfg = pipeline_settings(s)

    if preview is not None:
        direction, frame = preview
        action = None
        if s.anim_source == 'LIST' and len(s.anims):
            action = s.anims[min(s.anims_index, len(s.anims) - 1)].action
        jobs = [('preview', action, frame, frame, True)]
        dirs = [direction]
        want_normals = False
    else:
        jobs = animation_jobs(context, s)
        dirs = rig.render_directions(s)
        want_normals = s.export_normals

    with RenderState(scene, s):
        rig_obj, cam = rig.get_rig(scene)
        if preview is None or rig_obj is None or cam is None:
            rig_obj, cam = rig.ensure_rig(context, s, frames=[scene.frame_current])
            if preview is None and s.auto_fit:
                # stable framing: fit over sampled frames of EVERY animation
                sample = []
                meshes = rig._render_meshes(s.target)
                for _, action, start, end, _ in jobs:
                    if action is not None:
                        assign_action(s.target, action)
                    fr = frame_numbers(start, end, s.frame_step)
                    for f in fr[::max(1, len(fr) // 12)] + [fr[-1]]:
                        scene.frame_set(f)
                        pts = np.array(rig._world_corners(context.evaluated_depsgraph_get(), meshes))
                        if s.follow_target and len(pts):
                            # framing relative to the moving character, not the world
                            a = rig.anchor(s)
                            pts[:, 0] += rig_obj.location.x - a.x
                            pts[:, 1] += rig_obj.location.y - a.y
                        sample.extend(pts.tolist())
                if sample:
                    off = rig.FACING_OFFSET[s.facing]
                    s.ortho_scale = rig.fit(np.array(sample), tuple(rig_obj.location), rig.elevation(s),
                                            [rig.DIR_YAW[d] + off for d in rig.directions(s)], s.fit_padding)
                    cam.data.ortho_scale = s.ortho_scale
        # ensure_rig() sets the cell size; render supersampled
        size = rig.cell_size(s) * int(s.supersample)
        scene.render.resolution_x = scene.render.resolution_y = size
        scene.camera = cam

        total = sum(len(frame_numbers(j[2], j[3], s.frame_step)) for j in jobs) * len(dirs)
        done, t0 = 0, time.time()
        wm = context.window_manager
        wm.progress_begin(0, max(total, 1))
        tmp = tempfile.mkdtemp(prefix='psf_')
        stage = {}  # (anim, direction, index) -> (lo, normals_lo, pivot)
        base_z = rig_obj.location.z
        try:
            for name, action, start, end, _ in jobs:
                if action is not None:
                    assign_action(s.target, action)
                for d in dirs:
                    rig.set_direction(s, rig_obj, d)
                    for i, f in enumerate(frame_numbers(start, end, s.frame_step)):
                        scene.frame_set(f)
                        if s.follow_target:
                            rig.follow(s, rig_obj, base_z)
                        piv = rig.pivot(scene, cam, s)
                        hi = render_color(scene, os.path.join(tmp, 'c.png'))
                        nh = render_normals(scene, os.path.join(tmp, 'n.exr')) if want_normals else None
                        stage[(name, d, i)] = imaging.stage1(hi, cfg, nh) + (piv,)
                        done += 1
                        wm.progress_update(done)
                        if report:
                            report(done, total, time.time() - t0)
        finally:
            wm.progress_end()
            rig.set_direction(s, rig_obj, 'S')

    # Mirrored directions: horizontal flip of their source (normals: negate X)
    if preview is None and s.mirror_directions:
        for (name, d, i), (lo, n_lo, piv) in list(stage.items()):
            for dst, src in rig.MIRROR_SOURCE.items():
                if src == d and dst in rig.directions(s):
                    n_m = None
                    if n_lo is not None:
                        n_m = n_lo[:, ::-1].copy()
                        n_m[..., 0] *= -1
                    stage[(name, dst, i)] = (lo[:, ::-1].copy(), n_m, (round(1 - piv[0], 4), piv[1]))

    palette = resolve_palette(s, [v[0] for v in stage.values()])
    duration = int(round(1000 / max(1, s.fps)))
    frames = []
    order = rig.directions(s) if preview is None else dirs
    for name, action, start, end, _ in jobs:
        for d in order:
            for i in range(len(frame_numbers(start, end, s.frame_step))):
                if (name, d, i) not in stage:
                    continue
                lo, n_lo, piv = stage[(name, d, i)]
                rgba, nrm = imaging.stage2(lo, n_lo, cfg, palette)
                fr = packer.Frame(f'{name}_{d}_{i:03d}', name, d, i, rgba, nrm, duration)
                fr.pivot = piv
                frames.append(fr)
    loops = {j[0]: j[4] for j in jobs}
    return frames, palette, loops


def export(s, frames, loops):
    out_dir = bpy.path.abspath(s.output_dir) or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    base = bpy.path.clean_name(s.base_name or 'character')
    w, h = packer.pack(frames, s.layout, s.padding, trim=(s.layout == 'PACKED'), pow2=s.power_of_two)
    sheet_name = f'{base}.png'
    paths = [os.path.join(out_dir, sheet_name)]
    packer.write_png(paths[0], packer.compose(frames, w, h, 'rgba'))
    normal_name = None
    if any(f.normal is not None for f in frames):
        normal_name = f'{base}_n.png'
        paths.append(os.path.join(out_dir, normal_name))
        packer.write_png(paths[-1], packer.compose(frames, w, h, 'normal'))
    if s.export_json:
        paths.append(os.path.join(out_dir, f'{base}.json'))
        packer.export_json(paths[-1], frames, sheet_name, w, h, s.fps)
    if s.export_godot:
        paths.append(os.path.join(out_dir, f'{base}_frames.tres'))
        packer.export_godot_spriteframes(paths[-1], frames, sheet_name, s.fps, loops)
        if normal_name:
            paths.append(os.path.join(out_dir, f'{base}_canvas.tres'))
            packer.export_godot_canvas_texture(paths[-1], sheet_name, normal_name)
            paths.append(os.path.join(out_dir, f'{base}_frames_lit.tres'))
            packer.export_godot_spriteframes(paths[-1], frames, f'{base}_canvas.tres', s.fps, loops,
                                             atlas_type='CanvasTexture')
    if s.export_gifs:
        gdir = os.path.join(out_dir, f'{base}_gifs')
        os.makedirs(gdir, exist_ok=True)
        groups = {}
        for f in frames:
            groups.setdefault(f'{f.anim}_{f.direction}', []).append(f.rgba)
        for key, imgs in groups.items():
            gif.write_gif(os.path.join(gdir, f'{key}.gif'), imgs, 1000 / max(1, s.fps), s.gif_scale)
        paths.append(gdir)
    if s.export_frames:
        fdir = os.path.join(out_dir, f'{base}_frames')
        for f in frames:
            packer.write_png(os.path.join(fdir, f'{f.name}.png'), f.rgba)
        paths.append(fdir)
    return paths, (w, h)
