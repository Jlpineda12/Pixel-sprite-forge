"""Procedural test scenes for the use-case suite (no .blend files needed)."""
import math

import bpy


def reset(frame_end=24):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, frame_end
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 4
    sc.cycles.device = 'CPU'
    sc.world = bpy.data.worlds.new('W')
    bpy.ops.object.light_add(type='SUN', location=(3, -4, 6))
    sun = bpy.context.active_object
    sun.data.energy = 4
    sun.rotation_euler = (math.radians(45), 0, math.radians(30))
    return sc


def material(name, rgb, emit=0.0):
    m = bpy.data.materials.new(name)
    if not getattr(m, 'use_nodes', True):
        m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (*rgb, 1)
    if emit:
        key = 'Emission Color' if 'Emission Color' in p.inputs else 'Emission'
        p.inputs[key].default_value = (*rgb, 1)
        p.inputs['Emission Strength'].default_value = emit
    return m


def box(name, size, loc, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    bpy.ops.object.transform_apply(scale=True)
    ob.data.materials.append(mat)
    return ob


def armature_hero():
    """Armature with bone-parented parts + a skinned torso and 3 actions:
    idle (breathing), walk (legs/arms swing), attack (right arm swing)."""
    sc = reset(24)
    bpy.ops.object.armature_add(location=(0, 0, 0))
    arm = bpy.context.active_object
    arm.name = 'HeroRig'
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    root = eb[0]
    root.name = 'root'
    root.head, root.tail = (0, 0, 0), (0, 0.3, 0)

    def bone(name, head, tail, parent):
        b = eb.new(name)
        b.head, b.tail = head, tail
        b.parent = eb[parent]
        return b
    bone('spine', (0, 0, 0.9), (0, 0, 1.5), 'root')
    bone('head', (0, 0, 1.5), (0, 0, 1.9), 'spine')
    bone('leg.L', (0.15, 0, 0.9), (0.15, 0, 0.1), 'root')
    bone('leg.R', (-0.15, 0, 0.9), (-0.15, 0, 0.1), 'root')
    bone('arm.L', (0.38, 0, 1.45), (0.38, 0, 0.95), 'spine')
    bone('arm.R', (-0.38, 0, 1.45), (-0.38, 0, 0.95), 'spine')
    bpy.ops.object.mode_set(mode='OBJECT')

    skin = material('Skin', (0.95, 0.7, 0.55))
    shirt = material('Shirt', (0.2, 0.45, 0.9))
    pants = material('Pants', (0.25, 0.2, 0.3))
    red = material('Nose', (1, 0, 0.1), emit=1.5)

    torso = box('Torso', (0.55, 0.3, 0.6), (0, 0, 1.2), shirt)
    vg = torso.vertex_groups.new(name='spine')
    vg.add([v.index for v in torso.data.vertices], 1.0, 'REPLACE')
    torso.parent = arm
    mod = torso.modifiers.new('Armature', 'ARMATURE')
    mod.object = arm

    def rigid(ob, bone_name):
        mw = ob.matrix_world.copy()
        ob.parent = arm
        ob.parent_type = 'BONE'
        ob.parent_bone = bone_name
        bpy.context.view_layer.update()
        ob.matrix_world = mw
    rigid(box('Head', (0.4, 0.4, 0.4), (0, 0, 1.72), skin), 'head')
    rigid(box('Nose', (0.12, 0.2, 0.12), (0, -0.25, 1.7), red), 'head')
    rigid(box('Leg.L', (0.2, 0.22, 0.8), (0.15, 0, 0.5), pants), 'leg.L')
    rigid(box('Leg.R', (0.2, 0.22, 0.8), (-0.15, 0, 0.5), pants), 'leg.R')
    rigid(box('Arm.L', (0.15, 0.15, 0.5), (0.38, 0, 1.2), shirt), 'arm.L')
    rigid(box('Arm.R', (0.15, 0.15, 0.5), (-0.38, 0, 1.2), shirt), 'arm.R')

    arm.animation_data_create()
    pb = arm.pose.bones

    def act(name, keys, frames):
        a = bpy.data.actions.new(name)
        a.use_fake_user = True
        arm.animation_data.action = a
        for f, pose in zip(frames, keys):
            for bname, (axis, deg) in pose.items():
                b = pb[bname]
                b.rotation_mode = 'XYZ'
                r = [0, 0, 0]
                r['XYZ'.index(axis)] = math.radians(deg)
                b.rotation_euler = r
                b.keyframe_insert('rotation_euler', frame=f)
        return a
    act('idle', [{'spine': ('X', 0)}, {'spine': ('X', 4)}, {'spine': ('X', 0)}], [1, 9, 17])
    act('walk', [{'leg.L': ('X', 30), 'leg.R': ('X', -30), 'arm.L': ('X', -25), 'arm.R': ('X', 25)},
                 {'leg.L': ('X', -30), 'leg.R': ('X', 30), 'arm.L': ('X', 25), 'arm.R': ('X', -25)},
                 {'leg.L': ('X', 30), 'leg.R': ('X', -30), 'arm.L': ('X', -25), 'arm.R': ('X', 25)}],
        [1, 9, 17])
    act('attack', [{'arm.R': ('X', 0)}, {'arm.R': ('X', -150)}, {'arm.R': ('X', 40)}, {'arm.R': ('X', 0)}],
        [1, 5, 9, 13])
    for b in pb:
        b.rotation_euler = (0, 0, 0)
    arm.animation_data.action = bpy.data.actions['idle']
    return arm


def moving_cube():
    """Object that travels 4 m along -Y (root motion) while bobbing."""
    sc = reset(17)
    body = box('Runner', (0.6, 0.6, 1.0), (0, 0, 0.5), material('Body', (0.9, 0.5, 0.1)))
    box('Nose', (0.15, 0.2, 0.15), (0, -0.38, 0.7), material('NoseR', (1, 0, 0.1), 1.5)).parent = body
    body.animation_data_create()
    for f, y in ((1, 0.0), (17, -4.0)):
        body.location = (0, y, 0)
        body.keyframe_insert('location', frame=f)
    return body


def iso_prop():
    """Static asymmetric prop (house with a door on -Y and a chimney at +X)."""
    reset(1)
    wall = material('Wall', (0.85, 0.8, 0.65))
    roof = material('Roof', (0.7, 0.15, 0.15))
    door = material('Door', (0.0, 0.25, 1.0), emit=1.5)  # emissive blue: only blue thing in the scene
    house = box('House', (1.6, 1.2, 1.0), (0, 0, 0.5), wall)
    box('Roof', (1.7, 1.3, 0.25), (0, 0, 1.12), roof).parent = house
    box('Door', (0.35, 0.05, 0.6), (0, -0.62, 0.3), door).parent = house
    box('Chimney', (0.25, 0.25, 0.6), (0.6, 0, 1.4), roof).parent = house
    return house
