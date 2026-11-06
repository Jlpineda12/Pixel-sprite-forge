# SPDX-License-Identifier: GPL-3.0-or-later
"""Sprite-sheet packing + exporters (PNG, TexturePacker/PixiJS/Phaser JSON,
Aseprite-style frameTags, Godot 4 SpriteFrames .tres). Pure Python + numpy."""
import json
import os
import struct
import zlib

import numpy as np

from .imaging import trim_box

# ---------------------------------------------------------------------------
# PNG writer (exact 8-bit output, no color management surprises)
# ---------------------------------------------------------------------------

def write_png(path, rgba):
    """rgba: (H, W, 4) float 0..1, row 0 = top."""
    data = (np.clip(rgba, 0, 1) * 255 + 0.5).astype(np.uint8)
    h, w = data.shape[:2]
    raw = b''.join(b'\x00' + data[y].tobytes() for y in range(h))

    def chunk(tag, payload):
        c = struct.pack('>I', len(payload)) + tag + payload
        return c + struct.pack('>I', zlib.crc32(tag + payload) & 0xFFFFFFFF)

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(raw, 9))
    png += chunk(b'IEND', b'')
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(png)


def read_png(path):
    """Minimal PNG reader (8-bit RGB/RGBA, non-interlaced) used by the tests."""
    with open(path, 'rb') as f:
        data = f.read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos, idat = 8, b''
    w = h = ctype = None
    while pos < len(data):
        ln = struct.unpack('>I', data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if tag == b'IHDR':
            w, h, depth, ctype = struct.unpack('>IIBB', body[:10])
        elif tag == b'IDAT':
            idat += body
        pos += 12 + ln
    ch = 4 if ctype == 6 else 3
    raw = zlib.decompress(idat)
    stride = w * ch
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = np.frombuffer(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)], dtype=np.uint8).astype(np.int32)
        cur = np.zeros(stride, dtype=np.int32)
        for i in range(stride):
            a = cur[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            x = line[i]
            if f == 0:
                v = x
            elif f == 1:
                v = x + a
            elif f == 2:
                v = x + b
            elif f == 3:
                v = x + ((a + b) >> 1)
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                v = x + (a if pa <= pb and pa <= pc else (b if pb <= pc else c))
            cur[i] = v & 0xFF
        out[y] = cur
        prev = cur
    img = out.reshape(h, w, ch).astype(np.float32) / 255
    if ch == 3:
        img = np.concatenate([img, np.ones((h, w, 1), np.float32)], -1)
    return img


# ---------------------------------------------------------------------------
# Packing
# ---------------------------------------------------------------------------

class Frame:
    __slots__ = ('name', 'anim', 'direction', 'index', 'rgba', 'normal', 'duration_ms',
                 'trim', 'x', 'y')

    def __init__(self, name, anim, direction, index, rgba, normal=None, duration_ms=100):
        self.name, self.anim, self.direction, self.index = name, anim, direction, index
        self.rgba, self.normal, self.duration_ms = rgba, normal, duration_ms
        self.trim = None
        self.x = self.y = 0


def _next_pow2(v):
    p = 1
    while p < v:
        p <<= 1
    return p


def pack(frames, layout='GRID', padding=1, trim=True, pow2=False, max_width=2048):
    """Places frames on a sheet. Returns (sheet_w, sheet_h).

    GRID: one row per animation+direction, uniform cells (no trimming): easiest
          to slice in Godot (hframes/vframes) or Unity (Grid By Cell Size).
    PACKED: trims transparent borders and shelf-packs tightly; positions are
            restored from the JSON (spriteSourceSize) / Godot margins.
    """
    if not frames:
        raise ValueError('No hay frames para empaquetar')
    cell_h, cell_w = frames[0].rgba.shape[:2]

    if layout == 'GRID':
        rows = []
        for f in frames:
            key = (f.anim, f.direction)
            if not rows or rows[-1][0] != key:
                rows.append((key, []))
            rows[-1][1].append(f)
        cols = max(len(r[1]) for r in rows)
        for ry, (_, fr) in enumerate(rows):
            for cx, f in enumerate(fr):
                f.trim = (0, 0, cell_w, cell_h)
                f.x = padding + cx * (cell_w + padding)
                f.y = padding + ry * (cell_h + padding)
        w = padding + cols * (cell_w + padding)
        h = padding + len(rows) * (cell_h + padding)
    else:
        for f in frames:
            box = trim_box(f.rgba[..., 3]) if trim else (0, 0, cell_w, cell_h)
            f.trim = box or (0, 0, 1, 1)
        order = sorted(frames, key=lambda f: (-f.trim[3], -f.trim[2]))
        area = sum((f.trim[2] + padding) * (f.trim[3] + padding) for f in frames)
        target_w = min(max_width, max(max(f.trim[2] for f in frames) + 2 * padding,
                                      int(np.ceil(np.sqrt(area) * 1.15))))
        x = y = padding
        shelf_h = 0
        w = 0
        for f in order:
            fw, fh = f.trim[2], f.trim[3]
            if x + fw + padding > target_w:
                x = padding
                y += shelf_h + padding
                shelf_h = 0
            f.x, f.y = x, y
            x += fw + padding
            shelf_h = max(shelf_h, fh)
            w = max(w, x)
        h = y + shelf_h + padding
    if pow2:
        w, h = _next_pow2(w), _next_pow2(h)
    return int(w), int(h)


def compose(frames, w, h, attr='rgba'):
    sheet = np.zeros((h, w, 4), dtype=np.float32)
    for f in frames:
        src = getattr(f, attr)
        if src is None:
            continue
        tx, ty, tw, th = f.trim
        sheet[f.y:f.y + th, f.x:f.x + tw] = src[ty:ty + th, tx:tx + tw]
    return sheet


# ---------------------------------------------------------------------------
# Metadata exporters
# ---------------------------------------------------------------------------

def _anim_groups(frames):
    groups = {}
    for f in frames:
        groups.setdefault(f'{f.anim}_{f.direction}', []).append(f)
    return groups


def export_json(path, frames, image_name, w, h, fps, app_version='1.0.0'):
    """TexturePacker 'JSON Hash' (Phaser 3 atlas, PixiJS Spritesheet) plus:
    - top-level "animations" (PixiJS AnimatedSprite)
    - meta.frameTags (Aseprite style) and per-frame duration in ms."""
    cell_h, cell_w = frames[0].rgba.shape[:2]
    frames_json = {}
    for f in frames:
        tx, ty, tw, th = f.trim
        frames_json[f.name] = {
            'frame': {'x': f.x, 'y': f.y, 'w': tw, 'h': th},
            'rotated': False,
            'trimmed': (tw, th) != (cell_w, cell_h),
            'spriteSourceSize': {'x': tx, 'y': ty, 'w': tw, 'h': th},
            'sourceSize': {'w': cell_w, 'h': cell_h},
            'pivot': {'x': 0.5, 'y': 1.0},
            'duration': f.duration_ms,
        }
    groups = _anim_groups(frames)
    tags, i = [], 0
    for name, fr in groups.items():
        tags.append({'name': name, 'from': i, 'to': i + len(fr) - 1, 'direction': 'forward',
                     'anim': fr[0].anim, 'facing': fr[0].direction})
        i += len(fr)
    doc = {
        'frames': frames_json,
        'animations': {name: [f.name for f in fr] for name, fr in groups.items()},
        'meta': {
            'app': 'https://github.com/Jlpineda12/pixel-sprite-forge',
            'version': app_version,
            'image': image_name,
            'format': 'RGBA8888',
            'size': {'w': w, 'h': h},
            'scale': '1',
            'fps': fps,
            'cell': {'w': cell_w, 'h': cell_h},
            'frameTags': tags,
        },
    }
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    return doc


def export_godot_spriteframes(path, frames, image_name, fps, loop_anims=None, atlas_type='Texture2D'):
    """Godot 4 SpriteFrames resource: drag it onto an AnimatedSprite2D.
    Trimmed frames use AtlasTexture.margin so every frame keeps the same pivot.
    atlas_type='CanvasTexture' + image_name='<x>_canvas.tres' makes a variant
    whose frames carry the normal map (reacts to PointLight2D)."""
    cell_h, cell_w = frames[0].rgba.shape[:2]
    loop_anims = loop_anims or {}
    lines = []
    subs = []
    for i, f in enumerate(frames):
        tx, ty, tw, th = f.trim
        sub = [f'[sub_resource type="AtlasTexture" id="AtlasTexture_{i}"]',
               'atlas = ExtResource("1_sheet")',
               f'region = Rect2({f.x}, {f.y}, {tw}, {th})']
        if (tw, th) != (cell_w, cell_h):
            sub.append(f'margin = Rect2({tx}, {ty}, {cell_w - tw}, {cell_h - th})')
        sub.append('filter_clip = true')
        subs.append('\n'.join(sub))
    lines.append(f'[gd_resource type="SpriteFrames" load_steps={len(frames) + 2} format=3]\n')
    lines.append(f'[ext_resource type="{atlas_type}" path="{image_name}" id="1_sheet"]\n')
    lines.append('\n\n'.join(subs) + '\n')
    lines.append('[resource]')
    anims = []
    index = {id(f): i for i, f in enumerate(frames)}
    for name, fr in _anim_groups(frames).items():
        fr_txt = ', '.join(
            '{\n"duration": 1.0,\n"texture": SubResource("AtlasTexture_%d")\n}' % index[id(f)] for f in fr)
        loop = 'true' if loop_anims.get(fr[0].anim, True) else 'false'
        anims.append('{\n"frames": [%s],\n"loop": %s,\n"name": &"%s",\n"speed": %s\n}'
                     % (fr_txt, loop, name, float(fps)))
    lines.append('animations = [%s]\n' % ', '.join(anims))
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))


def export_godot_canvas_texture(path, image_name, normal_name):
    """CanvasTexture pairing the sheet with its normal map (2D dynamic lights)."""
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('[gd_resource type="CanvasTexture" load_steps=3 format=3]\n\n'
                 f'[ext_resource type="Texture2D" path="{image_name}" id="1_diffuse"]\n'
                 f'[ext_resource type="Texture2D" path="{normal_name}" id="2_normal"]\n\n'
                 '[resource]\n'
                 'diffuse_texture = ExtResource("1_diffuse")\n'
                 'normal_texture = ExtResource("2_normal")\n'
                 'texture_filter = 1\n')
