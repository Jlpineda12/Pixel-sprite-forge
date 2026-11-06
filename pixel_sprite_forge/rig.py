# SPDX-License-Identifier: GPL-3.0-or-later
"""Orthographic orbit camera rig: one empty (yaw) + one ortho camera (pitch)."""
import math

import bpy
import numpy as np
from mathutils import Vector

from .properties import DIRECTIONS_4, DIRECTIONS_8

RIG_NAME = 'PSF_Rig'
CAM_NAME = 'PSF_Camera'
COLLECTION = 'Pixel Sprite Forge'

# Yaw of the rig for each sprite direction, for a character facing -Y.
# "S" = character faces the viewer (down on screen), "E" = faces screen-right.
DIR_YAW = {'S': 0, 'SE': -45, 'E': -90, 'NE': -135, 'N': 180, 'NW': 135, 'W': 90, 'SW': 45}
FACING_OFFSET = {'NEG_Y': 0, 'POS_Y': 180, 'POS_X': 90, 'NEG_X': -90}
VIEW_ELEVATION = {'SIDE': 0.0, 'THREE_QUARTER': 30.0, 'ISOMETRIC': 35.264, 'TOP': 89.9}


def directions(settings):
    return {'1': ['S'], '4': DIRECTIONS_4, '8': DIRECTIONS_8}[settings.directions]


def elevation(settings):
    return settings.elevation if settings.camera_view == 'CUSTOM' else VIEW_ELEVATION[settings.camera_view]


def cell_size(settings):
    return settings.resolution_custom if settings.resolution == 'CUSTOM' else int(settings.resolution)


def get_rig(scene):
    rig = scene.objects.get(RIG_NAME)
    cam = scene.objects.get(CAM_NAME)
    return rig, cam


def _collection(scene):
    col = bpy.data.collections.get(COLLECTION)
    if col is None:
        col = bpy.data.collections.new(COLLECTION)
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    return col


def _render_meshes(target):
    """Mesh-like objects that make up the character (target + its children)."""
    if target is None:
        return []
    objs = [target] + list(target.children_recursive)
    return [o for o in objs if o.type in {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'} and o.visible_get() is not False]


def _world_corners(depsgraph, objs):
    pts = []
    for o in objs:
        ev = o.evaluated_get(depsgraph)
        mw = ev.matrix_world
        pts.extend([tuple(mw @ Vector(c)) for c in ev.bound_box])
    return pts


def sample_points(context, settings, frames):
    """Bounding-box corners of the character over the given frames (all anims)."""
    scene = context.scene
    objs = _render_meshes(settings.target)
    if not objs:
        return np.zeros((0, 3))
    keep = scene.frame_current
    pts = []
    for f in frames:
        scene.frame_set(f)
        pts.extend(_world_corners(context.evaluated_depsgraph_get(), objs))
    scene.frame_set(keep)
    return np.array(pts, dtype=np.float64)


def fit(points, center, elev_deg, yaws_deg, padding):
    """Smallest square ortho scale that contains the points from every direction."""
    if len(points) == 0:
        return 3.0
    p = points - np.asarray(center)
    e = math.radians(elev_deg)
    half = 0.0
    for yaw in yaws_deg:
        a = math.radians(yaw)
        # camera basis after yaw a and pitch e (camera sits at -Y before yaw)
        right = np.array([math.cos(a), math.sin(a), 0.0])
        fwd = np.array([-math.sin(a), math.cos(a), 0.0])
        up = np.array([0.0, 0.0, 1.0]) * math.cos(e) + fwd * math.sin(e)
        half = max(half, np.abs(p @ right).max(), np.abs(p @ up).max())
    return float(2 * half * (1 + padding))


def ensure_rig(context, settings, frames=None):
    """Creates or updates the rig so it frames the target for every direction."""
    scene = context.scene
    rig, cam = get_rig(scene)
    col = _collection(scene)
    if rig is None:
        rig = bpy.data.objects.new(RIG_NAME, None)
        rig.empty_display_type = 'CIRCLE'
        rig.empty_display_size = 1.0
        col.objects.link(rig)
    if cam is None:
        cam_data = bpy.data.cameras.new(CAM_NAME)
        cam = bpy.data.objects.new(CAM_NAME, cam_data)
        col.objects.link(cam)
    cam.parent = rig
    cam.data.type = 'ORTHO'

    target = settings.target
    frames = frames or [scene.frame_current]
    pts = sample_points(context, settings, frames) if target else np.zeros((0, 3))
    if len(pts):
        lo, hi = pts.min(0), pts.max(0)
        center = Vector((target.matrix_world.translation.x, target.matrix_world.translation.y,
                         (lo[2] + hi[2]) / 2))
    else:
        center = target.matrix_world.translation.copy() if target else Vector((0, 0, 1))
    rig.location = center

    elev = elevation(settings)
    radius = 10.0
    if len(pts):
        radius = float(np.linalg.norm(pts - np.array(center), axis=1).max()) * 3 + 2
    e = math.radians(elev)
    cam.location = (0.0, -radius * math.cos(e), radius * math.sin(e))
    cam.rotation_euler = (math.radians(90) - e, 0.0, 0.0)
    cam.data.clip_start = 0.01
    cam.data.clip_end = radius * 3

    offset = FACING_OFFSET[settings.facing]
    yaws = [DIR_YAW[d] + offset for d in directions(settings)]
    if settings.auto_fit and len(pts):
        settings.ortho_scale = fit(pts, center, elev, yaws, settings.fit_padding)
    cam.data.ortho_scale = settings.ortho_scale

    size = cell_size(settings)
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.camera = cam
    set_direction(settings, rig, 'S')
    return rig, cam


def set_direction(settings, rig, direction):
    rig.rotation_euler = (0.0, 0.0, math.radians(DIR_YAW[direction] + FACING_OFFSET[settings.facing]))
