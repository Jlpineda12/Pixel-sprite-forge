"""Pure-python tests (no Blender needed):  python3 -m pytest tests/test_pipeline.py
or simply:  python3 tests/test_pipeline.py"""
import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load  # noqa: E402

imaging, palettes, packer = load()


def gradient_sprite(size=64, ss=4):
    """A shaded disc on transparent background, supersampled."""
    n = size * ss
    y, x = np.mgrid[0:n, 0:n] / n
    d = np.hypot(x - 0.5, y - 0.5)
    a = (d < 0.35).astype(np.float32)
    img = np.zeros((n, n, 4), np.float32)
    img[..., 0] = x
    img[..., 1] = 0.3 + 0.5 * y
    img[..., 2] = 1 - x
    img[..., 3] = a
    img[..., :3] *= a[..., None]
    return img


SETTINGS = dict(supersample=4, downsample_mode='AVERAGE', alpha_threshold=0.5, saturation=1.0,
                contrast=1.0, brightness=0.0, light_bands=0, dither='BAYER4', dither_strength=0.6,
                outline='OUTER', outline_color=(0, 0, 0), outline_adaptive=True, outline_diagonal=False,
                normal_flip_y=False)


def colors_of(img):
    m = img[..., 3] > 0
    return {tuple(np.round(c * 255).astype(int)) for c in img[m][:, :3]}


def pal_set(pal):
    return {tuple(np.round(c * 255).astype(int)) for c in pal}


def test_builtin_palettes():
    assert len(palettes.builtin_palette('GAMEBOY')) == 4
    assert len(palettes.builtin_palette('PICO8')) == 16
    assert len(palettes.builtin_palette('C64')) == 16
    assert len(palettes.builtin_palette('NES')) >= 52
    assert len(palettes.builtin_palette('ENDESGA32')) == 32


def test_palette_files():
    d = tempfile.mkdtemp()
    hexf = os.path.join(d, 'p.hex')
    open(hexf, 'w').write('ff0000\n00ff00\n0000ff\n')
    pal = os.path.join(d, 'p.pal')
    open(pal, 'w').write('JASC-PAL\n0100\n2\n255 0 0\n0 0 0\n')
    gpl = os.path.join(d, 'p.gpl')
    open(gpl, 'w').write('GIMP Palette\nName: test\nColumns: 2\n#\n255 255 255\tWhite\n10 20 30\tInk\n')
    assert len(palettes.load_palette_file(hexf)) == 3
    assert len(palettes.load_palette_file(pal)) == 2
    g = palettes.load_palette_file(gpl)
    assert len(g) == 2 and pal_set(g) == {(255, 255, 255), (10, 20, 30)}


def test_bayer_matrix():
    for n in (2, 4, 8):
        m = imaging.bayer_matrix(n)
        assert m.shape == (n, n)
        assert len(np.unique(m)) == n * n
        assert abs(m.mean()) < 1e-6


def test_oklab_roundtrip():
    rgb = np.random.default_rng(1).random((100, 3)).astype(np.float32)
    back = imaging.oklab_to_srgb(imaging.srgb_to_oklab(rgb))
    assert np.abs(back - rgb).max() < 1e-3


def test_pipeline_uses_only_palette_colors():
    pal = palettes.builtin_palette('PICO8')
    for dither in ('NONE', 'BAYER2', 'BAYER4', 'BAYER8', 'FLOYD'):
        cfg = dict(SETTINGS, dither=dither)
        rgba, _ = imaging.process_sprite(gradient_sprite(), cfg, pal)
        assert rgba.shape == (64, 64, 4)
        assert colors_of(rgba) <= pal_set(pal), dither
        assert set(np.unique(rgba[..., 3])) <= {0.0, 1.0}


def test_gameboy_has_max_4_colors():
    pal = palettes.builtin_palette('GAMEBOY')
    rgba, _ = imaging.process_sprite(gradient_sprite(), dict(SETTINGS, dither='FLOYD'), pal)
    assert len(colors_of(rgba)) <= 4


def test_outer_outline_grows_silhouette():
    pal = palettes.builtin_palette('PICO8')
    no, _ = imaging.process_sprite(gradient_sprite(), dict(SETTINGS, outline='NONE'), pal)
    out, _ = imaging.process_sprite(gradient_sprite(), dict(SETTINGS, outline='OUTER'), pal)
    inner, _ = imaging.process_sprite(gradient_sprite(), dict(SETTINGS, outline='INNER'), pal)
    assert (out[..., 3] > 0).sum() > (no[..., 3] > 0).sum()
    assert (inner[..., 3] > 0).sum() == (no[..., 3] > 0).sum()


def test_normals_aligned_with_sprite():
    n = 64 * 4
    normals = np.zeros((n, n, 4), np.float32)
    normals[..., 2] = 1  # facing camera
    rgba, nrm = imaging.process_sprite(gradient_sprite(), SETTINGS, palettes.builtin_palette('PICO8'), normals)
    assert nrm.shape == rgba.shape
    assert np.array_equal(nrm[..., 3] > 0, rgba[..., 3] > 0)
    center = nrm[32, 32, :3]
    assert np.allclose(center, (0.5, 0.5, 1.0), atol=1e-3)


def test_auto_palette():
    px = np.random.default_rng(0).random((500, 3))
    pal = palettes.kmeans_palette(px, 8)
    assert len(pal) == 8 and pal.min() >= 0 and pal.max() <= 1


def _frames(n_anim=2, n_dir=8, n_fr=3):
    fs = []
    pal = palettes.builtin_palette('PICO8')
    base, _ = imaging.process_sprite(gradient_sprite(32), dict(SETTINGS), pal)
    for a in range(n_anim):
        dirs = {1: ['S'], 4: ['S', 'E', 'N', 'W'], 8: ['S', 'SE', 'E', 'NE', 'N', 'NW', 'W', 'SW']}[n_dir]
        for d in dirs:
            for i in range(n_fr):
                fs.append(packer.Frame(f'a{a}_{d}_{i:03d}', f'a{a}', d, i, base.copy(), base.copy(), 83))
    return fs


def _no_overlap(frames):
    rects = [(f.x, f.y, f.trim[2], f.trim[3]) for f in frames]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            if a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]:
                return False
    return True


def test_grid_and_packed_layouts():
    for layout in ('GRID', 'PACKED'):
        fs = _frames()
        w, h = packer.pack(fs, layout, padding=1, trim=(layout == 'PACKED'))
        assert _no_overlap(fs), layout
        assert all(f.x + f.trim[2] <= w and f.y + f.trim[3] <= h for f in fs)
    fs = _frames()
    w, h = packer.pack(fs, 'GRID', padding=0)
    assert (w, h) == (32 * 3, 32 * 16)  # 3 frames per row, 2 anims x 8 dirs rows


def test_png_roundtrip_and_exports():
    d = tempfile.mkdtemp()
    fs = _frames(1, 4, 2)
    w, h = packer.pack(fs, 'PACKED', padding=1, trim=True)
    sheet = packer.compose(fs, w, h)
    p = os.path.join(d, 'hero.png')
    packer.write_png(p, sheet)
    back = packer.read_png(p)
    assert back.shape == sheet.shape
    assert np.abs(back - sheet).max() <= 1 / 255 + 1e-6

    doc = packer.export_json(os.path.join(d, 'hero.json'), fs, 'hero.png', w, h, 12)
    assert len(doc['frames']) == len(fs)
    assert set(doc['animations']) == {'a0_S', 'a0_E', 'a0_N', 'a0_W'}
    f0 = doc['frames']['a0_S_000']
    assert f0['sourceSize'] == {'w': 32, 'h': 32}
    json.load(open(os.path.join(d, 'hero.json')))

    tres = os.path.join(d, 'hero_frames.tres')
    packer.export_godot_spriteframes(tres, fs, 'hero.png', 12, {'a0': True})
    txt = open(tres).read()
    assert txt.startswith('[gd_resource type="SpriteFrames"')
    assert txt.count('[sub_resource type="AtlasTexture"') == len(fs)
    assert '&"a0_S"' in txt and 'margin = Rect2(' in txt


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print(f'  PASS  {t.__name__}')
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f'  FAIL  {t.__name__}: {e!r}')
    print(f'\n{len(tests) - failed}/{len(tests)} tests OK')
    sys.exit(1 if failed else 0)
