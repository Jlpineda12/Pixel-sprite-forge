# SPDX-License-Identifier: GPL-3.0-or-later
"""Historical palettes + loaders for .hex / .pal (JASC) / .gpl (GIMP) files.

Pure Python + numpy: no bpy import, so it can be unit-tested outside Blender.
"""
import os

import numpy as np


def _hex_list(s):
    return [h.strip() for h in s.split() if h.strip()]


BUILTIN = {
    'GAMEBOY': ('Game Boy (DMG, 4 verdes)', _hex_list('0f380f 306230 8bac0f 9bbc0f')),
    'GAMEBOY_POCKET': ('Game Boy Pocket (4 grises)', _hex_list('000000 555555 aaaaaa ffffff')),
    'PICO8': ('PICO-8 (16)', _hex_list(
        '000000 1d2b53 7e2553 008751 ab5236 5f574f c2c3c7 fff1e8 '
        'ff004d ffa300 ffec27 00e436 29adff 83769c ff77a8 ffccaa')),
    'NES': ('NES (2C02, 54)', _hex_list(
        '7c7c7c 0000fc 0000bc 4428bc 940084 a80020 a81000 881400 503000 007800 006800 005800 004058 000000 '
        'bcbcbc 0078f8 0058f8 6844fc d800cc e40058 f83800 e45c10 ac7c00 00b800 00a800 00a844 008888 '
        'f8f8f8 3cbcfc 6888fc 9878f8 f878f8 f85898 f87858 fca044 f8b800 b8f818 58d854 58f898 00e8d8 787878 '
        'fcfcfc a4e4fc b8b8f8 d8b8f8 f8b8f8 f8a4c0 f0d0b0 fce0a8 f8d878 d8f878 b8f8b8 b8f8d8 00fcfc f8d8f8')),
    'C64': ('Commodore 64 (Pepto, 16)', _hex_list(
        '000000 ffffff 68372b 70a4b2 6f3d86 588d43 352879 b8c76f '
        '6f4f25 433900 9a6759 444444 6c6c6c 9ad284 6c5eb5 959595')),
    'CGA': ('CGA (modo 4, paleta 1 alta)', _hex_list('000000 55ffff ff55ff ffffff')),
    'SWEETIE16': ('Sweetie 16', _hex_list(
        '1a1c2c 5d275d b13e53 ef7d57 ffcd75 a7f070 38b764 257179 '
        '29366f 3b5dc9 41a6f6 73eff7 f4f4f4 94b0c2 566c86 333c57')),
    'ENDESGA32': ('Endesga 32', _hex_list(
        'be4a2f d77643 ead4aa e4a672 b86f50 733e39 3e2731 a22633 e43b44 f77622 feae34 fee761 '
        '63c74d 3e8948 265c42 193c3e 124e89 0099db 2ce8f5 ffffff c0cbdc 8b9bb4 5a6988 3a4466 '
        '262b44 181425 ff0044 68386c b55088 f6757a e8b796 c28569')),
}


def hex_to_rgb(h):
    h = h.strip().lstrip('#')
    if len(h) == 8:  # AARRGGBB (lospec .hex sometimes) -> drop alpha
        h = h[2:]
    if len(h) != 6:
        raise ValueError(f'Color hex inválido: {h!r}')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def palette_array(hex_colors):
    """List of hex strings -> (N, 3) float array in 0..1 (sRGB, display-referred)."""
    arr = np.array([hex_to_rgb(h) for h in hex_colors], dtype=np.float32) / 255.0
    # dedupe while preserving order
    _, idx = np.unique(arr, axis=0, return_index=True)
    return arr[np.sort(idx)]


def load_palette_file(path):
    """Loads .hex (one color per line), .pal (JASC-PAL) or .gpl (GIMP palette)."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = [l.strip() for l in f if l.strip()]
    colors = []
    if ext == '.hex' or ext == '.txt':
        for l in lines:
            if l.startswith(';') or l.startswith('//'):
                continue
            colors.append(l.split()[0])
    elif ext == '.pal':
        if lines and lines[0].upper().startswith('JASC-PAL'):
            body = lines[3:]
        else:
            body = lines
        for l in body:
            parts = l.split()
            if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
                colors.append('%02x%02x%02x' % tuple(int(p) for p in parts[:3]))
    elif ext == '.gpl':
        for l in lines:
            if l.startswith('#') or l.startswith('GIMP') or ':' in l.split()[0]:
                continue
            parts = l.split()
            if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
                colors.append('%02x%02x%02x' % tuple(int(p) for p in parts[:3]))
    else:
        raise ValueError(f'Formato de paleta no soportado: {ext} (usa .hex, .pal o .gpl)')
    if not colors:
        raise ValueError(f'No se encontraron colores en {os.path.basename(path)}')
    return palette_array(colors)


def builtin_palette(key):
    return palette_array(BUILTIN[key][1])


def kmeans_palette(pixels_rgb, n_colors, iterations=12, seed=0):
    """Builds an adaptive palette (k-means in OKLab) from (M, 3) sRGB pixels."""
    from .imaging import srgb_to_oklab, oklab_to_srgb
    px = np.asarray(pixels_rgb, dtype=np.float32)
    if len(px) == 0:
        return np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
    rng = np.random.default_rng(seed)
    if len(px) > 20000:
        px = px[rng.choice(len(px), 20000, replace=False)]
    lab = srgb_to_oklab(px)
    n = int(min(n_colors, len(np.unique(px, axis=0))))
    # k-means++ init
    centers = [lab[rng.integers(len(lab))]]
    for _ in range(1, n):
        d = np.min(((lab[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        probs = d / d.sum() if d.sum() > 0 else None
        centers.append(lab[rng.choice(len(lab), p=probs)])
    centers = np.array(centers)
    for _ in range(iterations):
        lbl = np.argmin(((lab[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)
        for k in range(n):
            m = lbl == k
            if m.any():
                centers[k] = lab[m].mean(0)
    out = np.clip(oklab_to_srgb(centers), 0, 1)
    # sort dark -> light for a nicer palette strip
    return out[np.argsort(srgb_to_oklab(out)[:, 0])]


def enum_items():
    items = [(k, v[0], f'{len(v[1])} colores') for k, v in BUILTIN.items()]
    items.append(('AUTO', 'Automática (k-means)', 'Calcula la mejor paleta de N colores a partir de tu animación'))
    items.append(('FILE', 'Archivo (.hex / .pal / .gpl)', 'Carga una paleta propia, p. ej. descargada de Lospec'))
    items.append(('NONE', 'Sin cuantizar', 'Mantiene los colores originales (solo pixelado)'))
    return items
