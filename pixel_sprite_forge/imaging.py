# SPDX-License-Identifier: GPL-3.0-or-later
"""Pixel-art post-processing pipeline (pure numpy, no bpy).

All images are float32 arrays shaped (H, W, 4), RGBA, sRGB display values in
0..1, row 0 = TOP of the image.

Pipeline:  supersampled render -> downsample -> color tweak -> palette
quantize (+ ordered / error-diffusion dithering) -> outline -> clean alpha.
Normal maps go through the same downsample + alpha mask so they line up
pixel-perfectly with the color sprite.
"""
import numpy as np

# ---------------------------------------------------------------------------
# Color spaces
# ---------------------------------------------------------------------------

def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float32), 0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]], dtype=np.float32)
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]], dtype=np.float32)


def srgb_to_oklab(rgb):
    """(..., 3) sRGB -> OKLab. Perceptual space: nearest-color here looks right."""
    lin = srgb_to_linear(rgb)
    lms = lin @ _M1.T
    return np.cbrt(lms) @ _M2.T


def oklab_to_srgb(lab):
    lms_ = np.asarray(lab, dtype=np.float32) @ np.linalg.inv(_M2).T
    lin = (lms_ ** 3) @ np.linalg.inv(_M1).T
    return linear_to_srgb(lin)


# ---------------------------------------------------------------------------
# Downsampling (virtual resolution)
# ---------------------------------------------------------------------------

def downsample(img, factor, mode='AVERAGE', alpha_threshold=0.5):
    """Box-filters a supersampled render to the virtual pixel grid.

    AVERAGE: coverage-weighted color (premultiplied), good for soft shading.
    NEAREST: samples the center of each block, crispest silhouettes.
    """
    img = np.asarray(img, dtype=np.float32)
    if factor <= 1:
        out = img.copy()
    else:
        h, w = img.shape[0] // factor, img.shape[1] // factor
        img = img[:h * factor, :w * factor]
        if mode == 'NEAREST':
            c = factor // 2
            out = img[c::factor, c::factor].copy()
        else:
            blocks = img.reshape(h, factor, w, factor, 4)
            a = blocks[..., 3].mean(axis=(1, 3))
            rgb_premul = (blocks[..., :3] * blocks[..., 3:4]).sum(axis=(1, 3))
            weight = blocks[..., 3].sum(axis=(1, 3))[..., None]
            rgb = np.where(weight > 1e-6, rgb_premul / np.maximum(weight, 1e-6), 0)
            out = np.concatenate([rgb, a[..., None]], axis=-1).astype(np.float32)
    out[..., 3] = (out[..., 3] >= alpha_threshold).astype(np.float32)
    out[..., :3] *= out[..., 3:4]
    return out


def downsample_normals(nrm, alpha_hi, factor):
    """Average camera-space normals (xyz in -1..1) per block, weighted by coverage."""
    nrm = np.asarray(nrm, dtype=np.float32)[..., :3]
    a = np.asarray(alpha_hi, dtype=np.float32)
    if factor > 1:
        h, w = nrm.shape[0] // factor, nrm.shape[1] // factor
        nrm = nrm[:h * factor, :w * factor].reshape(h, factor, w, factor, 3)
        a = a[:h * factor, :w * factor].reshape(h, factor, w, factor)
        nrm = (nrm * a[..., None]).sum(axis=(1, 3))
    length = np.linalg.norm(nrm, axis=-1, keepdims=True)
    flat = np.array([0, 0, 1], dtype=np.float32)
    return np.where(length > 1e-6, nrm / np.maximum(length, 1e-6), flat)


# ---------------------------------------------------------------------------
# Color tweaks
# ---------------------------------------------------------------------------

def adjust(img, saturation=1.0, contrast=1.0, brightness=0.0):
    out = img.copy()
    rgb = out[..., :3]
    if saturation != 1.0:
        gray = (rgb * np.array([0.299, 0.587, 0.114], dtype=np.float32)).sum(-1, keepdims=True)
        rgb = gray + (rgb - gray) * saturation
    if contrast != 1.0 or brightness != 0.0:
        rgb = (rgb - 0.5) * contrast + 0.5 + brightness
    out[..., :3] = np.clip(rgb, 0, 1) * out[..., 3:4]
    return out


def posterize_light(img, levels):
    """Cel-shading look before quantizing: snaps brightness to N bands."""
    if levels <= 1:
        return img
    out = img.copy()
    lab = srgb_to_oklab(out[..., :3])
    lab[..., 0] = np.round(lab[..., 0] * (levels - 1)) / (levels - 1)
    out[..., :3] = np.clip(oklab_to_srgb(lab), 0, 1) * out[..., 3:4]
    return out


# ---------------------------------------------------------------------------
# Palette quantization + dithering
# ---------------------------------------------------------------------------

def bayer_matrix(n):
    """Recursive Bayer index matrix, normalized to -0.5..0.5."""
    m = np.array([[0, 2], [3, 1]], dtype=np.float32)
    while m.shape[0] < n:
        k = m.shape[0]
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
        assert m.shape[0] == 2 * k
    return (m + 0.5) / (n * n) - 0.5


def _palette_spread(palette):
    """Typical distance between neighbouring palette colors (sRGB): dither amplitude."""
    if len(palette) < 2:
        return 0.25
    d = np.sqrt(((palette[:, None, :] - palette[None]) ** 2).sum(-1))
    d[d == 0] = np.inf
    return float(np.clip(np.median(d.min(axis=1)), 0.05, 0.6))


def nearest_index(rgb, palette_lab):
    lab = srgb_to_oklab(rgb)
    d = ((lab[..., None, :] - palette_lab) ** 2).sum(-1)
    return np.argmin(d, axis=-1)


def quantize(img, palette, dither='NONE', strength=1.0):
    """Maps every opaque pixel to the palette. dither: NONE, BAYER2/4/8, FLOYD."""
    if palette is None or len(palette) == 0:
        return img
    palette = np.asarray(palette, dtype=np.float32)
    pal_lab = srgb_to_oklab(palette)
    out = img.copy()
    alpha = out[..., 3] > 0
    rgb = out[..., :3]

    if dither.startswith('BAYER'):
        # Two-color ordered dithering: each pixel picks between its two nearest
        # palette colors; the Bayer threshold decides, weighted by how far the
        # pixel sits between them. A color already in the palette never gets
        # noise, gradients get a clean 25/50/75% checker.
        n = int(dither[5:])
        h, w = rgb.shape[:2]
        thr = np.tile(bayer_matrix(n) + 0.5, (h // n + 1, w // n + 1))[:h, :w]
        lab = srgb_to_oklab(rgb)
        d = ((lab[..., None, :] - pal_lab) ** 2).sum(-1)
        order = np.argsort(d, axis=-1)
        i1, i2 = order[..., 0], order[..., 1] if len(palette) > 1 else order[..., 0]
        c1, c2 = pal_lab[i1], pal_lab[i2]
        seg = c2 - c1
        t = ((lab - c1) * seg).sum(-1) / np.maximum((seg * seg).sum(-1), 1e-9)
        t = np.clip(t * strength, 0, 1)
        idx = np.where(thr < t, i2, i1)
        out[..., :3] = palette[idx]
    elif dither == 'FLOYD':
        out[..., :3] = _floyd_steinberg(rgb, alpha, palette, pal_lab, strength)
    else:
        out[..., :3] = palette[nearest_index(rgb, pal_lab)]
    out[..., :3] *= alpha[..., None]
    return out


def _floyd_steinberg(rgb, alpha, palette, pal_lab, strength):
    """Serpentine Floyd–Steinberg. Error never leaks into transparent pixels."""
    work = rgb.astype(np.float32).copy()
    h, w = work.shape[:2]
    res = np.zeros_like(work)
    pal_list = [tuple(p) for p in palette]
    for y in range(h):
        xs = range(w) if y % 2 == 0 else range(w - 1, -1, -1)
        step = 1 if y % 2 == 0 else -1
        for x in xs:
            if not alpha[y, x]:
                continue
            old = np.clip(work[y, x], 0, 1)
            k = int(np.argmin(((srgb_to_oklab(old) - pal_lab) ** 2).sum(-1)))
            new = palette[k]
            res[y, x] = new
            err = (old - new) * strength
            for dx, dy, wgt in ((step, 0, 7 / 16), (-step, 1, 3 / 16), (0, 1, 5 / 16), (step, 1, 1 / 16)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and ny < h and alpha[ny, nx]:
                    work[ny, nx] += err * wgt
    del pal_list
    return res


# ---------------------------------------------------------------------------
# Outlines
# ---------------------------------------------------------------------------

def _neighbors(mask, diagonal):
    m = np.pad(mask, 1)
    acc = m[:-2, 1:-1] | m[2:, 1:-1] | m[1:-1, :-2] | m[1:-1, 2:]
    if diagonal:
        acc = acc | m[:-2, :-2] | m[:-2, 2:] | m[2:, :-2] | m[2:, 2:]
    return acc


def outline(img, mode='OUTER', color=(0.05, 0.03, 0.08), adaptive=True, palette=None,
            diagonal=False, darken=0.55):
    """OUTER: adds a 1px border around the silhouette (grows the sprite).
    INNER: recolors the silhouette's edge pixels (keeps the size).
    adaptive: border color = darkened neighbour color (snapped to palette),
    the classic 'selout' look, instead of one flat color."""
    if mode == 'NONE':
        return img
    out = img.copy()
    solid = out[..., 3] > 0
    if mode == 'OUTER':
        edge = _neighbors(solid, diagonal) & ~solid
    else:
        edge = solid & _neighbors(~solid, diagonal)
        edge &= _neighbors(solid, False)  # keep 1px features from vanishing
    if not edge.any():
        return out

    if adaptive:
        # average color of solid neighbours, darkened in OKLab
        src = out[..., :3] * solid[..., None]
        cnt = solid.astype(np.float32)
        p = np.pad(src, ((1, 1), (1, 1), (0, 0)))
        pc = np.pad(cnt, 1)
        acc = p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]
        acn = pc[:-2, 1:-1] + pc[2:, 1:-1] + pc[1:-1, :-2] + pc[1:-1, 2:]
        if mode == 'INNER':
            acc, acn = out[..., :3], np.ones_like(cnt)
        base = acc / np.maximum(acn[..., None], 1)
        lab = srgb_to_oklab(base)
        lab[..., 0] *= darken
        lab[..., 1:] *= 0.8
        col = np.clip(oklab_to_srgb(lab), 0, 1)
        if palette is not None and len(palette):
            col = palette[nearest_index(col, srgb_to_oklab(np.asarray(palette)))]
        out[edge, :3] = col[edge]
    else:
        c = np.asarray(color, dtype=np.float32)
        if palette is not None and len(palette):
            c = palette[nearest_index(c[None], srgb_to_oklab(np.asarray(palette)))[0]]
        out[edge, :3] = c
    out[edge, 3] = 1.0
    return out


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def stage1(hi_rgba, settings, normals_hi=None):
    """Render-resolution -> virtual resolution. Cheap to keep in memory for
    every frame, so an adaptive (AUTO) palette can be computed from all of them."""
    s = settings
    lo = downsample(hi_rgba, s['supersample'], s['downsample_mode'], s['alpha_threshold'])
    n = None
    if normals_hi is not None:
        n = downsample_normals(normals_hi, hi_rgba[..., 3], s['supersample'])
    return lo, n


def stage2(lo, n_lo, settings, palette):
    """Color tweaks, palette + dithering, outline, normal-map encoding."""
    s = settings
    lo = adjust(lo, s['saturation'], s['contrast'], s['brightness'])
    if s['light_bands'] > 1:
        lo = posterize_light(lo, s['light_bands'])
    lo = quantize(lo, palette, s['dither'], s['dither_strength'])
    pre_outline_alpha = lo[..., 3] > 0
    lo = outline(lo, s['outline'], s['outline_color'], s['outline_adaptive'], palette, s['outline_diagonal'])
    nrm_rgba = None
    if n_lo is not None:
        n = n_lo.copy()
        if s.get('normal_flip_y'):
            n[..., 1] *= -1
        nrm_rgba = np.zeros_like(lo)
        nrm_rgba[..., :3] = n * 0.5 + 0.5
        added = (lo[..., 3] > 0) & ~pre_outline_alpha
        nrm_rgba[added, :3] = (0.5, 0.5, 1.0)
        nrm_rgba[..., 3] = lo[..., 3]
        nrm_rgba[..., :3] *= nrm_rgba[..., 3:4]
    return lo, nrm_rgba


def process_sprite(hi_rgba, settings, palette, normals_hi=None):
    """hi_rgba: supersampled render. Returns (sprite_rgba, normal_rgba or None)."""
    lo, n = stage1(hi_rgba, settings, normals_hi)
    return stage2(lo, n, settings, palette)


def trim_box(alpha, pad=0):
    """Bounding box (x, y, w, h) of non-transparent pixels, or None if empty."""
    ys, xs = np.nonzero(alpha > 0)
    if len(xs) == 0:
        return None
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + 1 + pad, alpha.shape[1])
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + 1 + pad, alpha.shape[0])
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)
