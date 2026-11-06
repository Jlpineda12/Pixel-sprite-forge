# SPDX-License-Identifier: GPL-3.0-or-later
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, PointerProperty, StringProperty)

from . import palettes

DIRECTIONS_8 = ['S', 'SE', 'E', 'NE', 'N', 'NW', 'W', 'SW']
DIRECTIONS_4 = ['S', 'E', 'N', 'W']


def _palette_changed(self, context):
    # refresh the swatch strip shown in the UI
    from .operators import refresh_palette_swatches
    refresh_palette_swatches(self)


class PSF_AnimItem(bpy.types.PropertyGroup):
    name: StringProperty(name='Nombre', description='Nombre de la animación en el sprite sheet (walk, attack, jump…)',
                         default='idle')
    action: PointerProperty(name='Acción', type=bpy.types.Action)
    frame_start: IntProperty(name='Inicio', default=1, min=0)
    frame_end: IntProperty(name='Fin', default=24, min=0)
    loop: BoolProperty(name='Loop', default=True, description='La animación se repite en el motor')
    enabled: BoolProperty(name='', default=True)


class PSF_Swatch(bpy.types.PropertyGroup):
    color: FloatVectorProperty(subtype='COLOR_GAMMA', size=3, min=0, max=1)


class PSF_Settings(bpy.types.PropertyGroup):
    # --- Target & rig -------------------------------------------------------
    target: PointerProperty(name='Personaje', type=bpy.types.Object,
                            description='Objeto animado (armature o malla). La cámara se centra en él')
    directions: EnumProperty(name='Direcciones', default='8', items=[
        ('1', '1 (frente)', 'Solo la vista frontal (S)'),
        ('4', '4 (N, S, E, O)', 'Cuatro direcciones cardinales'),
        ('8', '8 (con diagonales)', 'Cardinales + diagonales: S, SE, E, NE, N, NW, W, SW')])
    camera_view: EnumProperty(name='Vista', default='THREE_QUARTER', items=[
        ('SIDE', 'Lateral (0°)', 'Plataformas / side-scroller'),
        ('THREE_QUARTER', '3/4 (30°)', 'RPG top-down clásico'),
        ('ISOMETRIC', 'Isométrica (35.26°)', 'Isométrico 2:1 real'),
        ('TOP', 'Cenital (90°)', 'Vista desde arriba'),
        ('CUSTOM', 'Personalizada', 'Usa el ángulo de elevación manual')])
    elevation: FloatProperty(name='Elevación', default=30, min=-89, max=90, subtype='NONE',
                             description='Ángulo de la cámara sobre el horizonte, en grados')
    facing: EnumProperty(name='El personaje mira hacia', default='NEG_Y', items=[
        ('NEG_Y', '-Y (estándar Blender)', ''), ('POS_Y', '+Y', ''),
        ('POS_X', '+X', ''), ('NEG_X', '-X', '')])
    fit_padding: FloatProperty(name='Margen', default=0.08, min=0, max=1, subtype='FACTOR',
                               description='Espacio libre alrededor del personaje dentro de la celda')
    auto_fit: BoolProperty(name='Encuadre automático', default=True,
                           description='Calcula una escala ortográfica fija que contiene al personaje en todos los frames y direcciones (sin "temblor")')
    ortho_scale: FloatProperty(name='Escala ortográfica', default=3.0, min=0.01)

    # --- Pixel style --------------------------------------------------------
    resolution: EnumProperty(name='Resolución virtual', default='64', items=[
        ('16', '16×16', ''), ('24', '24×24', ''), ('32', '32×32', ''), ('48', '48×48', ''),
        ('64', '64×64', ''), ('96', '96×96', ''), ('128', '128×128', ''), ('256', '256×256', ''),
        ('CUSTOM', 'Personalizada', '')])
    resolution_custom: IntProperty(name='Tamaño', default=40, min=4, max=1024)
    supersample: EnumProperty(name='Supermuestreo', default='4', items=[
        ('1', '1× (rápido)', 'Renderiza directamente a la resolución virtual'),
        ('2', '2×', ''), ('4', '4× (recomendado)', 'Bordes y colores más estables'), ('8', '8×', '')])
    downsample_mode: EnumProperty(name='Reducción', default='AVERAGE', items=[
        ('AVERAGE', 'Promedio', 'Color promedio de cada bloque: sombreado más suave'),
        ('NEAREST', 'Centro', 'Muestra el centro del bloque: siluetas más duras')])
    alpha_threshold: FloatProperty(name='Umbral de alfa', default=0.5, min=0.01, max=1, subtype='FACTOR')

    palette: EnumProperty(name='Paleta', items=palettes.enum_items(), default='PICO8', update=_palette_changed)
    palette_file: StringProperty(name='Archivo', subtype='FILE_PATH', update=_palette_changed,
                                 description='.hex, .pal (JASC) o .gpl (GIMP). Ej.: descargada de lospec.com')
    auto_colors: IntProperty(name='Colores', default=16, min=2, max=64, update=_palette_changed)
    swatches: CollectionProperty(type=PSF_Swatch)

    dither: EnumProperty(name='Dithering', default='BAYER4', items=[
        ('NONE', 'Ninguno', 'Color más cercano'),
        ('BAYER2', 'Bayer 2×2', 'Ordenado, patrón fino'),
        ('BAYER4', 'Bayer 4×4', 'Ordenado clásico (estable entre frames)'),
        ('BAYER8', 'Bayer 8×8', 'Ordenado, degradados más suaves'),
        ('FLOYD', 'Floyd–Steinberg', 'Difusión de error (más orgánico, puede "hervir" en animación)')])
    dither_strength: FloatProperty(name='Intensidad', default=0.6, min=0, max=2, subtype='FACTOR')
    light_bands: IntProperty(name='Bandas de luz (cel)', default=0, min=0, max=8,
                             description='0 = desactivado. Agrupa la iluminación en N bandas antes de cuantizar')
    saturation: FloatProperty(name='Saturación', default=1.15, min=0, max=3)
    contrast: FloatProperty(name='Contraste', default=1.1, min=0, max=3)
    brightness: FloatProperty(name='Brillo', default=0.0, min=-1, max=1)

    outline: EnumProperty(name='Contorno', default='OUTER', items=[
        ('NONE', 'Sin contorno', ''),
        ('OUTER', 'Exterior', 'Añade 1 px alrededor de la silueta'),
        ('INNER', 'Interior', 'Recolorea el borde de la silueta sin agrandarla')])
    outline_adaptive: BoolProperty(name='Adaptativo', default=True,
                                   description='Color del contorno = color vecino oscurecido (selout), ajustado a la paleta')
    outline_color: FloatVectorProperty(name='Color', subtype='COLOR_GAMMA', size=3, min=0, max=1,
                                       default=(0.08, 0.05, 0.12))
    outline_diagonal: BoolProperty(name='Diagonales', default=False, description='Contorno con conectividad 8 (más grueso en esquinas)')

    # --- Animations ---------------------------------------------------------
    anim_source: EnumProperty(name='Origen', default='SCENE', items=[
        ('SCENE', 'Acción actual', 'Usa la acción activa y el rango de la escena'),
        ('LIST', 'Lista de acciones', 'Hornea varias acciones (walk, attack, jump…) en una sola hoja')])
    scene_anim_name: StringProperty(name='Nombre', default='anim')
    anims: CollectionProperty(type=PSF_AnimItem)
    anims_index: IntProperty()
    frame_step: IntProperty(name='Cada N frames', default=2, min=1, max=60,
                            description='Renderiza 1 de cada N frames (el pixel art suele ir a 8-12 fps)')
    fps: IntProperty(name='FPS en el motor', default=12, min=1, max=120)

    # --- Preview ------------------------------------------------------------
    preview_direction: EnumProperty(name='Dirección', default='S',
                                    items=[(d, d, '') for d in DIRECTIONS_8])
    live_preview: BoolProperty(name='Vista previa en vivo', default=False)

    # --- Export -------------------------------------------------------------
    output_dir: StringProperty(name='Carpeta', subtype='DIR_PATH', default='//sprites/')
    base_name: StringProperty(name='Nombre', default='character')
    engine: EnumProperty(name='Motor de render', default='KEEP', items=[
        ('KEEP', 'El de la escena', ''), ('EEVEE', 'EEVEE', 'Rápido, el más usado'),
        ('WORKBENCH', 'Workbench', 'Plano / flat shading'), ('CYCLES', 'Cycles', 'Lento pero funciona sin GPU')])
    layout: EnumProperty(name='Distribución', default='GRID', items=[
        ('GRID', 'Cuadrícula', 'Celdas iguales, una fila por animación y dirección (fácil en Godot/Unity)'),
        ('PACKED', 'Empaquetada', 'Recorta espacios vacíos y empaqueta (usa el JSON para posicionar)')])
    padding: IntProperty(name='Separación', default=1, min=0, max=16)
    power_of_two: BoolProperty(name='Potencia de 2', default=False)
    export_json: BoolProperty(name='JSON (Phaser / PixiJS / Unity)', default=True)
    export_godot: BoolProperty(name='Godot 4 SpriteFrames (.tres)', default=True)
    export_normals: BoolProperty(name='Normal map', default=True,
                                 description='Hoja de normales alineada píxel a píxel para luces 2D dinámicas')
    normal_flip_y: BoolProperty(name='Invertir Y (DirectX)', default=False,
                                description='Godot y Unity usan la convención OpenGL (Y+): déjalo apagado')
    export_frames: BoolProperty(name='PNG por frame', default=False)
    standard_view: BoolProperty(name='Color "Standard" al hornear', default=True,
                                description='Usa la transformación de vista Standard durante el render (AgX/Filmic desaturan los colores)')


classes = (PSF_AnimItem, PSF_Swatch, PSF_Settings)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.pixel_forge = PointerProperty(type=PSF_Settings)


def unregister():
    del bpy.types.Scene.pixel_forge
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
