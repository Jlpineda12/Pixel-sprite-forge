"""Demo: builds a low-poly knight with a walk cycle and an attack, ready for
Pixel Sprite Forge. Run it from Blender's Text Editor (Run Script) or:

    blender --python examples/demo_scene.py

Then open the "Pixel Forge" tab in the 3D View sidebar (N) and press
"Generar sprite sheet".
"""
import math

import bpy


def mat(name, rgb, rough=0.6, emit=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if not getattr(m, 'use_nodes', True):
        m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = (*rgb, 1)
    p.inputs['Roughness'].default_value = rough
    if emit:
        key = 'Emission Color' if 'Emission Color' in p.inputs else 'Emission'
        p.inputs[key].default_value = (*rgb, 1)
        p.inputs['Emission Strength'].default_value = emit
    return m


def part(name, prim, size, loc, parent, material, rot=(0, 0, 0)):
    if prim == 'cube':
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    elif prim == 'sphere':
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, segments=12, ring_count=8)
    elif prim == 'cone':
        bpy.ops.mesh.primitive_cone_add(radius1=0.5, depth=1, vertices=8)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    ob.rotation_euler = rot
    ob.location = loc
    ob.parent = parent
    ob.data.materials.append(material)
    bpy.ops.object.shade_flat()
    return ob


def pivot(name, loc, parent):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 0.1
    bpy.context.scene.collection.objects.link(e)
    e.location = loc
    e.parent = parent
    return e


def key_rot(ob, frame, x=None, z=None):
    r = list(ob.rotation_euler)
    if x is not None:
        r[0] = math.radians(x)
    if z is not None:
        r[2] = math.radians(z)
    ob.rotation_euler = r
    ob.keyframe_insert('rotation_euler', frame=frame)


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, 17
    sc.render.fps = 24
    world = bpy.data.worlds.new('World')
    world.color = (0.05, 0.05, 0.08)
    sc.world = world

    steel = mat('Steel', (0.55, 0.6, 0.72), 0.35)
    dark = mat('DarkSteel', (0.18, 0.2, 0.28), 0.5)
    cape = mat('Cape', (0.75, 0.08, 0.12))
    skin = mat('Skin', (0.95, 0.72, 0.55))
    gold = mat('Gold', (1.0, 0.75, 0.15), 0.3)
    blade = mat('Blade', (0.85, 0.95, 1.0), 0.2, emit=0.4)
    wood = mat('Wood', (0.45, 0.25, 0.1))

    root = bpy.data.objects.new('Knight', None)
    sc.collection.objects.link(root)
    hips = pivot('Hips', (0, 0, 0.95), root)

    part('Torso', 'cube', (0.55, 0.32, 0.6), (0, 0, 0.35), hips, steel)
    part('Belt', 'cube', (0.58, 0.35, 0.1), (0, 0, 0.05), hips, wood)
    part('Cape', 'cube', (0.5, 0.06, 0.75), (0, 0.2, 0.25), hips, cape)
    head = part('Head', 'sphere', (0.42, 0.42, 0.42), (0, 0, 0.9), hips, skin)
    part('Helmet', 'sphere', (0.48, 0.48, 0.36), (0, 0, 0.98), hips, steel)
    part('Visor', 'cube', (0.36, 0.06, 0.1), (0, -0.21, 0.9), hips, dark)
    part('Plume', 'cone', (0.12, 0.3, 0.35), (0, 0.05, 1.28), hips, cape, rot=(math.radians(-20), 0, 0))
    del head

    legs, arms = [], []
    for side, x in (('L', 0.15), ('R', -0.15)):
        hp = pivot(f'Hip.{side}', (x, 0, 0), hips)
        part(f'Leg.{side}', 'cube', (0.2, 0.22, 0.55), (0, 0, -0.32), hp, dark)
        part(f'Boot.{side}', 'cube', (0.22, 0.32, 0.14), (0, -0.05, -0.62), hp, wood)
        legs.append(hp)
        sp = pivot(f'Shoulder.{side}', (x * 2.15, 0, 0.58), hips)
        part(f'Arm.{side}', 'cube', (0.16, 0.18, 0.5), (0, 0, -0.25), sp, steel)
        arms.append(sp)
    # sword in the right hand, shield on the left arm
    part('Sword', 'cube', (0.06, 0.06, 0.75), (0, -0.25, -0.45), arms[1], blade, rot=(math.radians(80), 0, 0))
    part('Guard', 'cube', (0.25, 0.06, 0.06), (0, -0.05, -0.47), arms[1], gold)
    part('Shield', 'cube', (0.08, 0.42, 0.5), (0.12, -0.05, -0.3), arms[0], gold)

    # walk cycle 1..17
    for f, a in ((1, 30), (5, 0), (9, -30), (13, 0), (17, 30)):
        key_rot(legs[0], f, x=a)
        key_rot(legs[1], f, x=-a)
        key_rot(arms[0], f, x=-a * 0.8)
        key_rot(arms[1], f, x=a * 0.8)
        hips.location.z = 0.95 + (0.05 if a == 0 else 0)
        hips.keyframe_insert('location', index=2, frame=f)

    # lights
    bpy.ops.object.light_add(type='SUN', location=(3, -4, 6))
    sun = bpy.context.active_object
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(45), 0, math.radians(30))
    bpy.ops.object.light_add(type='SUN', location=(-3, 4, 3))
    fill = bpy.context.active_object
    fill.data.energy = 0.8
    fill.data.color = (0.5, 0.6, 1.0)
    fill.rotation_euler = (math.radians(-60), 0, math.radians(200))

    s = getattr(sc, 'pixel_forge', None)
    if s is not None:
        s.target = root
        s.scene_anim_name = 'walk'
    return root


if __name__ == '__main__':
    build()
