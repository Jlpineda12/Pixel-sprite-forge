# SPDX-License-Identifier: GPL-3.0-or-later
import os

import bpy
import numpy as np

from . import baker, palettes, rig

PREVIEW_IMAGE = 'PSF Preview'

PRESETS = {
    'GAMEBOY': dict(resolution='32', palette='GAMEBOY', dither='BAYER4', dither_strength=0.7,
                    outline='OUTER', outline_adaptive=False, saturation=1.0, contrast=1.2, light_bands=0),
    'NES': dict(resolution='32', palette='NES', dither='NONE', outline='OUTER', outline_adaptive=False,
                outline_color=(0.0, 0.0, 0.0), saturation=1.25, contrast=1.15, light_bands=3),
    'PICO8': dict(resolution='48', palette='PICO8', dither='BAYER2', dither_strength=0.5,
                  outline='OUTER', outline_adaptive=True, saturation=1.2, contrast=1.1, light_bands=0),
    'C64': dict(resolution='48', palette='C64', dither='BAYER8', dither_strength=0.8,
                outline='INNER', outline_adaptive=True, saturation=1.1, contrast=1.1, light_bands=0),
    'MODERN': dict(resolution='64', palette='AUTO', auto_colors=24, dither='NONE', outline='OUTER',
                   outline_adaptive=True, saturation=1.15, contrast=1.1, light_bands=4),
    'HD': dict(resolution='128', palette='AUTO', auto_colors=48, dither='BAYER4', dither_strength=0.35,
               outline='INNER', outline_adaptive=True, saturation=1.1, contrast=1.05, light_bands=0),
}


def refresh_palette_swatches(s):
    s.swatches.clear()
    try:
        if s.palette in ('NONE', 'AUTO'):
            return
        if s.palette == 'FILE':
            path = bpy.path.abspath(s.palette_file)
            if not os.path.isfile(path):
                return
            pal = palettes.load_palette_file(path)
        else:
            pal = palettes.builtin_palette(s.palette)
    except Exception:
        return
    for c in pal[:64]:
        s.swatches.add().color = tuple(float(v) for v in c)


def _settings(context):
    return context.scene.pixel_forge


# ---------------------------------------------------------------------------
# Rig
# ---------------------------------------------------------------------------

class PSF_OT_create_rig(bpy.types.Operator):
    bl_idname = 'pixel_forge.create_rig'
    bl_label = 'Crear / actualizar rig de cámara'
    bl_description = 'Crea una cámara ortográfica orbital que encuadra al personaje en 4 u 8 direcciones'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = _settings(context)
        if s.target is None:
            if context.active_object is None:
                self.report({'ERROR'}, 'Selecciona tu personaje primero')
                return {'CANCELLED'}
            s.target = context.active_object
        sc = context.scene
        frames = list(range(sc.frame_start, sc.frame_end + 1, max(1, (sc.frame_end - sc.frame_start) // 8 or 1)))
        rig.ensure_rig(context, s, frames)
        self.report({'INFO'}, f'Rig listo · escala ortográfica {s.ortho_scale:.2f}')
        return {'FINISHED'}


class PSF_OT_look_direction(bpy.types.Operator):
    bl_idname = 'pixel_forge.look_direction'
    bl_label = 'Ver dirección'
    bl_description = 'Gira el rig a esta dirección y mira a través de la cámara'
    direction: bpy.props.StringProperty()

    def execute(self, context):
        s = _settings(context)
        r, cam = rig.get_rig(context.scene)
        if r is None:
            bpy.ops.pixel_forge.create_rig()
            r, cam = rig.get_rig(context.scene)
        rig.set_direction(s, r, self.direction)
        s.preview_direction = self.direction
        context.scene.camera = cam
        for area in context.screen.areas if context.screen else []:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Animations list
# ---------------------------------------------------------------------------

class PSF_OT_detect_actions(bpy.types.Operator):
    bl_idname = 'pixel_forge.detect_actions'
    bl_label = 'Detectar acciones'
    bl_description = 'Llena la lista con todas las acciones del archivo (walk, attack, jump…)'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = _settings(context)
        existing = {a.action for a in s.anims}
        n = 0
        for act in bpy.data.actions:
            if act in existing or act.name.startswith('PSF_'):
                continue
            it = s.anims.add()
            it.name = act.name.lower().replace(' ', '_').split('|')[-1]
            it.action = act
            start, end = act.frame_range
            it.frame_start, it.frame_end = int(start), int(end)
            it.loop = not any(k in it.name for k in ('attack', 'death', 'die', 'hit', 'jump'))
            n += 1
        s.anim_source = 'LIST'
        self.report({'INFO'}, f'{n} acciones añadidas')
        return {'FINISHED'}


class PSF_OT_anim_add(bpy.types.Operator):
    bl_idname = 'pixel_forge.anim_add'
    bl_label = 'Añadir animación'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = _settings(context)
        it = s.anims.add()
        t = s.target
        if t and t.animation_data and t.animation_data.action:
            it.action = t.animation_data.action
            it.name = it.action.name.lower()
            it.frame_start, it.frame_end = (int(v) for v in it.action.frame_range)
        s.anims_index = len(s.anims) - 1
        return {'FINISHED'}


class PSF_OT_anim_remove(bpy.types.Operator):
    bl_idname = 'pixel_forge.anim_remove'
    bl_label = 'Quitar animación'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = _settings(context)
        if len(s.anims):
            s.anims.remove(s.anims_index)
            s.anims_index = max(0, s.anims_index - 1)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Presets & palettes
# ---------------------------------------------------------------------------

class PSF_OT_apply_preset(bpy.types.Operator):
    bl_idname = 'pixel_forge.apply_preset'
    bl_label = 'Aplicar estilo'
    bl_options = {'REGISTER', 'UNDO'}
    preset: bpy.props.EnumProperty(items=[
        ('GAMEBOY', 'Game Boy', '32 px, 4 verdes, Bayer 4×4'),
        ('NES', 'NES', '32 px, paleta 2C02, contorno negro, cel'),
        ('PICO8', 'PICO-8', '48 px, 16 colores, Bayer 2×2'),
        ('C64', 'Commodore 64', '48 px, Pepto, Bayer 8×8'),
        ('MODERN', 'Indie moderno', '64 px, 24 colores automáticos, cel'),
        ('HD', 'HD pixel', '128 px, 48 colores automáticos')])

    def execute(self, context):
        s = _settings(context)
        for k, v in PRESETS[self.preset].items():
            setattr(s, k, v)
        refresh_palette_swatches(s)
        return {'FINISHED'}


class PSF_OT_refresh_palette(bpy.types.Operator):
    bl_idname = 'pixel_forge.refresh_palette'
    bl_label = 'Recargar paleta'

    def execute(self, context):
        refresh_palette_swatches(_settings(context))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def _show_image(context, rgba, name=PREVIEW_IMAGE):
    h, w = rgba.shape[:2]
    scale = max(1, 256 // max(w, h))
    big = np.repeat(np.repeat(rgba, scale, axis=0), scale, axis=1)
    H, W = big.shape[:2]
    img = bpy.data.images.get(name)
    if img is None or tuple(img.size) != (W, H):
        if img is not None:
            bpy.data.images.remove(img)
        img = bpy.data.images.new(name, W, H, alpha=True)
    img.pixels.foreach_set(big[::-1].astype(np.float32).ravel())
    img.update()
    for area in (context.screen.areas if context.screen else []):
        if area.type == 'IMAGE_EDITOR':
            area.spaces.active.image = img
            area.tag_redraw()
    return img


def run_preview(context):
    s = _settings(context)
    frames, palette, _ = baker.bake(context, s, preview=(s.preview_direction, context.scene.frame_current))
    rgba = frames[0].rgba
    if palette is not None and s.palette == 'AUTO':
        s.swatches.clear()
        for c in palette:
            s.swatches.add().color = tuple(float(v) for v in c)
    return _show_image(context, rgba)


class PSF_OT_preview(bpy.types.Operator):
    bl_idname = 'pixel_forge.preview'
    bl_label = 'Vista previa'
    bl_description = 'Renderiza el frame actual con el estilo pixel art y lo muestra en el Editor de Imágenes'

    def execute(self, context):
        try:
            run_preview(context)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f'Vista previa lista en la imagen "{PREVIEW_IMAGE}" (Editor de Imágenes)')
        return {'FINISHED'}


class PSF_OT_live_preview(bpy.types.Operator):
    """Re-renders the pixel preview whenever the frame, direction or style changes"""
    bl_idname = 'pixel_forge.live_preview'
    bl_label = 'Vista previa en vivo'
    _timer = None
    _sig = None

    def _signature(self, context):
        s = _settings(context)
        keys = ('resolution', 'resolution_custom', 'supersample', 'downsample_mode', 'alpha_threshold',
                'palette', 'palette_file', 'auto_colors', 'dither', 'dither_strength', 'light_bands',
                'saturation', 'contrast', 'brightness', 'outline', 'outline_adaptive', 'outline_diagonal',
                'preview_direction', 'facing', 'camera_view', 'elevation')
        return (context.scene.frame_current, tuple(getattr(s, k) for k in keys), tuple(s.outline_color))

    def modal(self, context, event):
        s = _settings(context)
        if not s.live_preview or event.type == 'ESC':
            return self.cancel(context) or {'CANCELLED'}
        if event.type == 'TIMER':
            sig = self._signature(context)
            if sig != self._sig:
                self._sig = sig
                try:
                    run_preview(context)
                except Exception as e:
                    self.report({'WARNING'}, f'Vista previa: {e}')
                    s.live_preview = False
        return {'PASS_THROUGH'}

    def execute(self, context):
        s = _settings(context)
        s.live_preview = True
        self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        _settings(context).live_preview = False


# ---------------------------------------------------------------------------
# Bake
# ---------------------------------------------------------------------------

class PSF_OT_bake(bpy.types.Operator):
    bl_idname = 'pixel_forge.bake'
    bl_label = 'Generar sprite sheet'
    bl_description = 'Renderiza todas las animaciones en todas las direcciones y exporta PNG + JSON + Godot'

    def execute(self, context):
        s = _settings(context)
        if bpy.data.filepath == '' and s.output_dir.startswith('//'):
            self.report({'ERROR'}, 'Guarda el archivo .blend primero o elige una carpeta absoluta de salida')
            return {'CANCELLED'}

        def report(done, total, elapsed):
            eta = elapsed / done * (total - done)
            print(f'[Pixel Sprite Forge] {done}/{total} frames · faltan ~{eta:.0f}s')
        try:
            frames, palette, loops = baker.bake(context, s, report=report)
            paths, (w, h) = baker.export(s, frames, loops)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if palette is not None and s.palette == 'AUTO':
            s.swatches.clear()
            for c in palette:
                s.swatches.add().color = tuple(float(v) for v in c)
        img = bpy.data.images.load(paths[0], check_existing=True)
        img.reload()
        for area in (context.screen.areas if context.screen else []):
            if area.type == 'IMAGE_EDITOR':
                area.spaces.active.image = img
        self.report({'INFO'}, f'{len(frames)} frames → {os.path.basename(paths[0])} ({w}×{h}) en {os.path.dirname(paths[0])}')
        return {'FINISHED'}


class PSF_OT_open_output(bpy.types.Operator):
    bl_idname = 'pixel_forge.open_output'
    bl_label = 'Abrir carpeta'

    def execute(self, context):
        path = bpy.path.abspath(_settings(context).output_dir)
        os.makedirs(path, exist_ok=True)
        bpy.ops.wm.path_open(filepath=path)
        return {'FINISHED'}


classes = (PSF_OT_create_rig, PSF_OT_look_direction, PSF_OT_detect_actions, PSF_OT_anim_add,
           PSF_OT_anim_remove, PSF_OT_apply_preset, PSF_OT_refresh_palette, PSF_OT_preview,
           PSF_OT_live_preview, PSF_OT_bake, PSF_OT_open_output)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
