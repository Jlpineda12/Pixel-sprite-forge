# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal animated GIF89a writer (LZW, transparency, infinite loop).
Pure Python + numpy, so it runs inside Blender without Pillow."""
import struct

import numpy as np


def _lzw(indices, min_code_size):
    """GIF-flavoured LZW (variable code size, clear on full table)."""
    clear = 1 << min_code_size
    eoi = clear + 1
    data = bytearray()
    state = {'buf': 0, 'n': 0, 'size': min_code_size + 1}

    def emit(code):
        state['buf'] |= code << state['n']
        state['n'] += state['size']
        while state['n'] >= 8:
            data.append(state['buf'] & 0xFF)
            state['buf'] >>= 8
            state['n'] -= 8

    def fresh():
        return {bytes([i]): i for i in range(clear)}

    table = fresh()
    next_code = eoi + 1
    emit(clear)
    w = b''
    for idx in indices:
        c = bytes([idx])
        wc = w + c
        if wc in table:
            w = wc
            continue
        emit(table[w])
        # same rule as giflib: widen after emitting once the next code needs more bits
        if next_code >= (1 << state['size']) and state['size'] < 12:
            state['size'] += 1
        if next_code >= 4095:
            emit(clear)
            table = fresh()
            next_code = eoi + 1
            state['size'] = min_code_size + 1
        else:
            table[wc] = next_code
            next_code += 1
        w = c
    if w:
        emit(table[w])
        if next_code >= (1 << state['size']) and state['size'] < 12:
            state['size'] += 1
    emit(eoi)
    if state['n']:
        data.append(state['buf'] & 0xFF)
    return bytes(data)


def _subblocks(b):
    out = bytearray()
    for i in range(0, len(b), 255):
        chunk = b[i:i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def write_gif(path, frames, delay_ms=100, scale=1):
    """frames: list of (H, W, 4) float RGBA (row 0 = top). Alpha is binary.
    Colors are collected exactly (pixel art has few); >255 colors get reduced."""
    imgs = [np.repeat(np.repeat(f, scale, 0), scale, 1) if scale > 1 else f for f in frames]
    h, w = imgs[0].shape[:2]
    rgb8 = [(np.clip(f[..., :3], 0, 1) * 255 + 0.5).astype(np.uint8) for f in imgs]
    alpha = [f[..., 3] > 0 for f in imgs]

    colors = np.unique(np.concatenate([r[a] for r, a in zip(rgb8, alpha)] or [np.zeros((0, 3), np.uint8)]),
                       axis=0)
    if len(colors) > 255:
        from .palettes import kmeans_palette
        colors = (kmeans_palette(colors.astype(np.float32) / 255, 255) * 255 + 0.5).astype(np.uint8)
    table = np.zeros((256, 3), np.uint8)
    table[1:len(colors) + 1] = colors  # index 0 = transparent

    out = bytearray(b'GIF89a')
    out += struct.pack('<HHBBB', w, h, 0xF7, 0, 0)  # global table, 8 bits, 256 entries
    out += table.tobytes()
    out += b'\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00'  # loop forever
    cen = colors.astype(np.int32)
    for r, a in zip(rgb8, alpha):
        if len(cen):
            d = ((r.reshape(-1, 1, 3).astype(np.int32) - cen[None]) ** 2).sum(-1)
            idx = (np.argmin(d, axis=1) + 1).astype(np.uint8)
        else:
            idx = np.zeros(h * w, np.uint8)
        idx[~a.reshape(-1)] = 0
        delay = max(2, int(round(delay_ms / 10)))
        out += b'\x21\xF9\x04' + struct.pack('<BHBB', 0x09, delay, 0, 0)  # dispose=2, transparent
        out += b'\x2C' + struct.pack('<HHHHB', 0, 0, w, h, 0)
        out.append(8)
        out += _subblocks(_lzw(idx.tolist(), 8))
    out += b'\x3B'
    with open(path, 'wb') as fh:
        fh.write(out)
