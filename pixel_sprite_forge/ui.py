# SPDX-License-Identifier: GPL-3.0-or-later
import bpy

from . import rig

CATEGORY = 'Pixel Forge'


class PSF_UL_anims(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, 'enabled', text='')
        row.prop(item, 'name', text='', emboss=False, icon='ACTION')
        sub = row.row(align=True)
        sub.scale_x = 0.55
        sub.label(text=f'{item.frame_start}-{item.frame_end}')
        row.prop(item, 'loop', text='', icon='FILE_REFRESH' if item.loop else 'FORWARD', emboss=False)


class _Panel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY


class PSF_PT_main(_Panel, bpy.types.Panel):
    bl_label = 'Pixel Sprite Forge'
    bl_idname = 'PSF_PT_main'

    def draw_header(self, context):
        self.layout.label(text='', icon='IMAGE_RGB_ALPHA')

    def draw(self, context):
        s = context.scene.pixel_forge
        col = self.layout.column(align=True)
        col.prop(s, 'target', icon='ARMATURE_DATA')
        col.label(text='Estilos rápidos:')
        grid = col.grid_flow(columns=3, align=True)
        for key, label in (('GAMEBOY', 'Game Boy'), ('NES', 'NES'), ('PICO8', 'PICO-8'),
                           ('C64', 'C64'), ('MODERN', 'Indie'), ('HD', 'HD')):
            grid.operator('pixel_forge.apply_preset', text=label).preset = key


class PSF_PT_camera(_Panel, bpy.types.Panel):
    bl_label = '1 · Cámara de 8 direcciones'
    bl_parent_id = 'PSF_PT_main'

    def draw(self, context):
        s = context.scene.pixel_forge
        lay = self.layout
        lay.prop(s, 'directions')
        lay.prop(s, 'camera_view')
        if s.camera_view == 'CUSTOM':
            lay.prop(s, 'elevation')
        lay.prop(s, 'facing')
        row = lay.row(align=True)
        row.prop(s, 'auto_fit')
        sub = row.row()
        sub.enabled = not s.auto_fit
        sub.prop(s, 'ortho_scale', text='')
        lay.prop(s, 'fit_padding', slider=True)
        lay.operator('pixel_forge.create_rig', icon='OUTLINER_OB_CAMERA')
        # compass to jump between directions
        dirs = rig.directions(s)
        box = lay.box()
        box.label(text='Ver dirección:')
        compass = [['NW', 'N', 'NE'], ['W', None, 'E'], ['SW', 'S', 'SE']]
        for row_dirs in compass:
            row = box.row(align=True)
            for d in row_dirs:
                if d is None:
                    row.label(text='', icon='USER')
                elif d in dirs:
                    op = row.operator('pixel_forge.look_direction', text=d,
                                      depress=(s.preview_direction == d))
                    op.direction = d
                else:
                    row.label(text='')


class PSF_PT_style(_Panel, bpy.types.Panel):
    bl_label = '2 · Estilo pixel art'
    bl_parent_id = 'PSF_PT_main'

    def draw(self, context):
        s = context.scene.pixel_forge
        lay = self.layout
        row = lay.row(align=True)
        row.prop(s, 'resolution')
        if s.resolution == 'CUSTOM':
            row.prop(s, 'resolution_custom', text='')
        lay.prop(s, 'supersample')
        lay.prop(s, 'downsample_mode', expand=True)

        box = lay.box()
        box.prop(s, 'palette', icon='COLOR')
        if s.palette == 'FILE':
            box.prop(s, 'palette_file')
        elif s.palette == 'AUTO':
            box.prop(s, 'auto_colors')
        if len(s.swatches):
            flow = box.grid_flow(columns=min(16, len(s.swatches)), align=True)
            for sw in s.swatches:
                flow.prop(sw, 'color', text='')
        elif s.palette not in ('NONE', 'AUTO'):
            box.operator('pixel_forge.refresh_palette', icon='FILE_REFRESH')
        if s.palette != 'NONE':
            box.prop(s, 'dither')
            if s.dither != 'NONE':
                box.prop(s, 'dither_strength', slider=True)

        box = lay.box()
        box.prop(s, 'outline')
        if s.outline != 'NONE':
            row = box.row(align=True)
            row.prop(s, 'outline_adaptive', toggle=True)
            row.prop(s, 'outline_diagonal', toggle=True)
            if not s.outline_adaptive:
                box.prop(s, 'outline_color')

        col = lay.column(align=True)
        col.prop(s, 'light_bands')
        col.prop(s, 'saturation')
        col.prop(s, 'contrast')
        col.prop(s, 'brightness')
        lay.prop(s, 'alpha_threshold', slider=True)


class PSF_PT_anims(_Panel, bpy.types.Panel):
    bl_label = '3 · Animaciones'
    bl_parent_id = 'PSF_PT_main'

    def draw(self, context):
        s = context.scene.pixel_forge
        lay = self.layout
        lay.prop(s, 'anim_source', expand=True)
        if s.anim_source == 'SCENE':
            lay.prop(s, 'scene_anim_name')
            sc = context.scene
            lay.label(text=f'Rango de escena: {sc.frame_start}–{sc.frame_end}', icon='TIME')
        else:
            row = lay.row()
            row.template_list('PSF_UL_anims', '', s, 'anims', s, 'anims_index', rows=4)
            col = row.column(align=True)
            col.operator('pixel_forge.anim_add', text='', icon='ADD')
            col.operator('pixel_forge.anim_remove', text='', icon='REMOVE')
            col.separator()
            col.operator('pixel_forge.detect_actions', text='', icon='VIEWZOOM')
            if len(s.anims):
                it = s.anims[s.anims_index]
                box = lay.box()
                box.prop(it, 'action')
                r = box.row(align=True)
                r.prop(it, 'frame_start')
                r.prop(it, 'frame_end')
        row = lay.row(align=True)
        row.prop(s, 'frame_step')
        row.prop(s, 'fps')


class PSF_PT_preview(_Panel, bpy.types.Panel):
    bl_label = '4 · Vista previa'
    bl_parent_id = 'PSF_PT_main'

    def draw(self, context):
        s = context.scene.pixel_forge
        lay = self.layout
        lay.prop(s, 'preview_direction')
        row = lay.row(align=True)
        row.scale_y = 1.3
        row.operator('pixel_forge.preview', icon='RENDER_STILL')
        if s.live_preview:
            row.prop(s, 'live_preview', text='Detener', toggle=True, icon='PAUSE')
        else:
            row.operator('pixel_forge.live_preview', text='En vivo', icon='PLAY')
        lay.label(text='Abre un Editor de Imágenes para verla', icon='INFO')


class PSF_PT_export(_Panel, bpy.types.Panel):
    bl_label = '5 · Exportar'
    bl_parent_id = 'PSF_PT_main'

    def draw(self, context):
        s = context.scene.pixel_forge
        lay = self.layout
        lay.prop(s, 'output_dir')
        lay.prop(s, 'base_name')
        lay.prop(s, 'engine')
        lay.prop(s, 'standard_view')
        lay.prop(s, 'layout', expand=True)
        row = lay.row(align=True)
        row.prop(s, 'padding')
        row.prop(s, 'power_of_two', toggle=True)
        col = lay.column(align=True)
        col.prop(s, 'export_json')
        col.prop(s, 'export_godot')
        col.prop(s, 'export_normals')
        if s.export_normals:
            col.prop(s, 'normal_flip_y')
        col.prop(s, 'export_frames')

        n_dirs = len(rig.directions(s))
        lay.label(text=f'{n_dirs} direcciones · celda {rig.cell_size(s)} px', icon='INFO')
        row = lay.row()
        row.scale_y = 1.8
        row.operator('pixel_forge.bake', icon='RENDER_ANIMATION')
        lay.operator('pixel_forge.open_output', icon='FILE_FOLDER')


classes = (PSF_UL_anims, PSF_PT_main, PSF_PT_camera, PSF_PT_style, PSF_PT_anims, PSF_PT_preview, PSF_PT_export)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
