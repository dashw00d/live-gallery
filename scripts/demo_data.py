"""Generate demo images and 3D models for the README screenshots.

Everything is procedural (no personal files). Needs Pillow and numpy:
    pip install pillow numpy
Usage: python3 scripts/demo_data.py OUTDIR [SECOND_OUTDIR]
"""
import json
import math
import os
import struct
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


# ---------- images ----------
def _grid(w, h):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return x / w, y / h


def _to_img(a):
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def palette(t, stops):
    """Map t in [0,1] to RGB through a list of RGB stops."""
    stops = np.array(stops, dtype=np.float32)
    t = np.clip(t, 0, 1) * (len(stops) - 1)
    i = np.minimum(t.astype(int), len(stops) - 2)
    f = (t - i)[..., None]
    return stops[i] * (1 - f) + stops[i + 1] * f


def plasma(w, h, seed, stops):
    r = np.random.RandomState(seed)
    x, y = _grid(w, h)
    v = np.zeros_like(x)
    for _ in range(5):
        fx, fy, ph = r.uniform(2, 9), r.uniform(2, 9), r.uniform(0, 6.28)
        v += np.sin(fx * x * 6.28 + fy * y * 6.28 + ph + np.sin(y * r.uniform(2, 6)))
    v = (v - v.min()) / (v.max() - v.min())
    return _to_img(palette(v, stops))


def julia(w, h, c, stops, zoom=1.0):
    x, y = _grid(w, h)
    z = ((x - 0.5) * 3.2 / zoom) + 1j * ((y - 0.5) * 3.2 * h / w / zoom)
    n = np.zeros(z.shape)
    for i in range(80):
        m = np.abs(z) < 2
        z = np.where(m, z * z + c, z)
        n += m
    return _to_img(palette(np.sqrt(n / 80), stops))


def orbs(w, h, seed, bg, cols):
    r = np.random.RandomState(seed)
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(26):
        c = cols[r.randint(len(cols))]
        rad = r.randint(h // 14, h // 4)
        cx, cy = r.randint(0, w), r.randint(0, h)
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=c + (r.randint(70, 170),))
    return im.filter(ImageFilter.GaussianBlur(2))


def landscape(w, h, seed, sky, hills):
    r = np.random.RandomState(seed)
    x, y = _grid(w, h)
    img = palette(y, sky)
    for k, col in enumerate(hills):
        base = 0.55 + 0.1 * k
        ridge = base + 0.07 * np.sin(x * r.uniform(5, 12) + r.uniform(0, 6)) + 0.04 * np.sin(x * r.uniform(15, 30))
        img = np.where((y > ridge)[..., None], np.array(col, dtype=np.float32), img)
    return _to_img(img)


def texture(w, h, seed, a, b):
    r = np.random.RandomState(seed)
    n = np.zeros((h, w), dtype=np.float32)
    for s in (4, 8, 16, 32, 64):
        small = r.rand(h // s + 2, w // s + 2).astype(np.float32)
        im = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        n += np.asarray(im, dtype=np.float32) / 255 * (s / 64 + .3)
    n = (n - n.min()) / (n.max() - n.min())
    return _to_img(palette(n, [a, b]))


def icon(size, bg, fg, shape):
    im = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(im)
    m = size // 5
    if shape == "circle":
        d.ellipse([m, m, size - m, size - m], fill=fg)
    elif shape == "tri":
        d.polygon([(size // 2, m), (size - m, size - m), (m, size - m)], fill=fg)
    elif shape == "ring":
        d.ellipse([m, m, size - m, size - m], outline=fg, width=size // 8)
    else:
        d.rounded_rectangle([m, m, size - m, size - m], size // 8, fill=fg)
    return im


# ---------- meshes ----------
def torus_knot(p=2, q=3, segs=220, sides=16, r=0.28):
    v, n, f = [], [], []
    def pt(t):
        rr = 2 + math.cos(q * t)
        return np.array([rr * math.cos(p * t), rr * math.sin(p * t), -math.sin(q * t)])
    for i in range(segs):
        t = 2 * math.pi * i / segs
        c, c2 = pt(t), pt(t + 0.01)
        T = c2 - c
        T /= np.linalg.norm(T)
        N = np.cross(T, [0, 0, 1])
        N /= np.linalg.norm(N)
        B = np.cross(T, N)
        for j in range(sides):
            a = 2 * math.pi * j / sides
            d = math.cos(a) * N + math.sin(a) * B
            v.append(c + r * d)
            n.append(d)
    for i in range(segs):
        for j in range(sides):
            a, b = i * sides + j, i * sides + (j + 1) % sides
            c_, d_ = ((i + 1) % segs) * sides + j, ((i + 1) % segs) * sides + (j + 1) % sides
            f += [(a, c_, b), (b, c_, d_)]
    return np.array(v, np.float32), np.array(n, np.float32), np.array(f, np.uint32)


def torus(R=1.4, r=0.55, segs=48, sides=24):
    v, n, f = [], [], []
    for i in range(segs):
        u = 2 * math.pi * i / segs
        for j in range(sides):
            w = 2 * math.pi * j / sides
            d = np.array([math.cos(u) * math.cos(w), math.sin(u) * math.cos(w), math.sin(w)])
            v.append(np.array([R * math.cos(u), R * math.sin(u), 0]) + r * d)
            n.append(d)
    for i in range(segs):
        for j in range(sides):
            a, b = i * sides + j, i * sides + (j + 1) % sides
            c, d = ((i + 1) % segs) * sides + j, ((i + 1) % segs) * sides + (j + 1) % sides
            f += [(a, c, b), (b, c, d)]
    return np.array(v, np.float32), np.array(n, np.float32), np.array(f, np.uint32)


def icosphere(sub=2, bump=0.0):
    t = (1 + 5 ** .5) / 2
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
         (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5),
         (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    v = [np.array(p, float) / np.linalg.norm(p) for p in v]
    for _ in range(sub):
        cache, nf = {}, []
        def mid(a, b):
            k = (min(a, b), max(a, b))
            if k not in cache:
                m = (v[a] + v[b]) / 2
                v.append(m / np.linalg.norm(m))
                cache[k] = len(v) - 1
            return cache[k]
        for a, b, c in f:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        f = nf
    v = np.array(v)
    nrm = v.copy()
    if bump:
        v = v * (1 + bump * np.sin(v[:, 0] * 7) * np.sin(v[:, 1] * 7) * np.sin(v[:, 2] * 7))[:, None]
    return v.astype(np.float32) * 1.5, nrm.astype(np.float32), np.array(f, np.uint32)


def write_obj(path, m):
    v, n, f = m
    with open(path, "w") as fh:
        fh.write("# demo mesh\n")
        for p in v: fh.write("v %.5f %.5f %.5f\n" % tuple(p))
        for p in n: fh.write("vn %.5f %.5f %.5f\n" % tuple(p))
        for a, b, c in f + 1: fh.write("f %d//%d %d//%d %d//%d\n" % (a, a, b, b, c, c))


def write_stl(path, m):
    v, _, f = m
    with open(path, "w") as fh:
        fh.write("solid demo\n")
        for a, b, c in f:
            nrm = np.cross(v[b] - v[a], v[c] - v[a])
            nrm = nrm / (np.linalg.norm(nrm) or 1)
            fh.write("facet normal %.5f %.5f %.5f\n outer loop\n" % tuple(nrm))
            for i in (a, b, c): fh.write("  vertex %.5f %.5f %.5f\n" % tuple(v[i]))
            fh.write(" endloop\nendfacet\n")
        fh.write("endsolid demo\n")


def write_ply(path, m):
    v, _, f = m
    with open(path, "w") as fh:
        fh.write("ply\nformat ascii 1.0\nelement vertex %d\nproperty float x\nproperty float y\nproperty float z\n"
                 "element face %d\nproperty list uchar int vertex_indices\nend_header\n" % (len(v), len(f)))
        for p in v: fh.write("%.5f %.5f %.5f\n" % tuple(p))
        for a, b, c in f: fh.write("3 %d %d %d\n" % (a, b, c))


def write_glb(path, m, color=(0.9, 0.45, 0.2)):
    v, n, f = m
    pos, nor, idx = v.astype("<f4").tobytes(), n.astype("<f4").tobytes(), f.astype("<u4").ravel().tobytes()
    blob = pos + nor + idx
    j = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
         "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}]}],
         "materials": [{"pbrMetallicRoughness": {"baseColorFactor": list(color) + [1], "metallicFactor": 0.3,
                                                  "roughnessFactor": 0.45}}],
         "buffers": [{"byteLength": len(blob)}],
         "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos), "target": 34962},
                         {"buffer": 0, "byteOffset": len(pos), "byteLength": len(nor), "target": 34962},
                         {"buffer": 0, "byteOffset": len(pos) + len(nor), "byteLength": len(idx), "target": 34963}],
         "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(v), "type": "VEC3",
                        "min": v.min(0).tolist(), "max": v.max(0).tolist()},
                       {"bufferView": 1, "componentType": 5126, "count": len(n), "type": "VEC3"},
                       {"bufferView": 2, "componentType": 5125, "count": f.size, "type": "SCALAR"}]}
    js = json.dumps(j).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        fh.write(struct.pack("<II", len(blob), 0x004E4942) + blob)


# ---------- layout ----------
def make(root, root2=None):
    """Populate ROOT with a nested, agent-style output tree (the exports/ part goes to ROOT2 if
    given, so two watched folders can be shown). Returns the files created, oldest first."""
    W, H = 640, 480
    S = lambda *c: [c_ for c_ in c]
    warm = S((20, 10, 50), (190, 40, 90), (250, 170, 60), (255, 240, 200))
    cool = S((5, 20, 50), (20, 90, 160), (60, 200, 200), (230, 255, 240))
    violet = S((10, 5, 30), (90, 30, 160), (220, 90, 200), (255, 220, 240))
    forest = S((5, 25, 20), (20, 100, 70), (140, 200, 90), (250, 250, 190))
    jobs = [
        # path, factory
        ("run3/renders/lane_a/frame_0001.png", lambda: julia(W, H, -0.8 + 0.156j, warm)),
        ("run3/renders/lane_a/frame_0002.png", lambda: julia(W, H, -0.4 + 0.6j, cool)),
        ("run3/renders/lane_a/frame_0003.png", lambda: julia(W, H, 0.285 + 0.01j, violet)),
        ("run3/renders/lane_c/sunset_study.jpg", lambda: landscape(1280, 720, 1, S((40, 20, 90), (240, 120, 80), (255, 210, 130)), [(60, 30, 70), (40, 20, 60), (20, 10, 40)])),
        ("run3/renders/lane_c/alpine_dawn.jpg", lambda: landscape(1280, 720, 4, S((90, 140, 210), (200, 220, 240), (255, 235, 210)), [(110, 130, 150), (70, 95, 120), (35, 55, 80)])),
        ("run3/renders/lane_c/pine_valley.jpg", lambda: landscape(1280, 720, 7, S((20, 60, 70), (110, 170, 150), (220, 235, 190)), [(40, 90, 70), (25, 65, 50), (12, 40, 32)])),
        ("run3/textures/moss.png", lambda: texture(W, W, 3, (20, 50, 20), (150, 190, 80))),
        ("run3/textures/sandstone.png", lambda: texture(W, W, 5, (120, 80, 50), (240, 200, 150))),
        ("run3/textures/ice.png", lambda: texture(W, W, 9, (150, 200, 230), (250, 255, 255))),
        ("run3/concepts/nebula_v1.webp", lambda: plasma(W, H, 11, violet)),
        ("run3/concepts/nebula_v2.webp", lambda: plasma(W, H, 12, cool)),
        ("run3/concepts/orbs_a.png", lambda: orbs(W, H, 2, (15, 15, 35), [(255, 120, 90), (90, 190, 255), (255, 220, 110)])),
        ("run3/concepts/orbs_b.png", lambda: orbs(W, H, 8, (240, 235, 225), [(230, 80, 110), (60, 120, 200), (250, 190, 70)])),
        ("exports/icons/play.png", lambda: icon(256, (30, 41, 59), (56, 189, 248), "tri")),
        ("exports/icons/record.png", lambda: icon(256, (30, 41, 59), (248, 113, 113), "circle")),
        ("exports/icons/loop.png", lambda: icon(256, (30, 41, 59), (163, 230, 53), "ring")),
        ("exports/icons/stop.png", lambda: icon(256, (30, 41, 59), (251, 191, 36), "sq")),
    ]
    models = [
        ("run3/models/knot_v1.glb", lambda p: write_glb(p, torus_knot(2, 3), (0.95, 0.5, 0.2))),
        ("run3/models/knot_v2.glb", lambda p: write_glb(p, torus_knot(3, 4, segs=300), (0.3, 0.65, 0.95))),
        ("run3/models/donut.obj", lambda p: write_obj(p, torus())),
        ("exports/meshes/rock.stl", lambda p: write_stl(p, icosphere(2, 0.18))),
        ("exports/meshes/gem.ply", lambda p: write_ply(p, icosphere(1, 0.12))),
    ]
    root2 = root2 or root
    made = []
    t0 = time.time() - 3600
    allj = [(p, "img", f) for p, f in jobs] + [(p, "mdl", f) for p, f in models]
    # interleave so newest-first looks mixed
    order = [allj[i] for i in (0, 16, 3, 1, 4, 17, 6, 2, 9, 5, 18, 7, 12, 8, 19, 10, 13, 11, 20, 14, 15)]
    for i, (rel, kind, fn) in enumerate(order):
        path = os.path.join(root2 if rel.startswith("exports/") else root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if kind == "img":
            fn().save(path, quality=88)
        else:
            fn(path)
        ts = t0 + i * 150
        os.utime(path, (ts, ts))
        made.append(path)
    return made


def make_late(root):
    """Files that 'arrive' while the gallery is open."""
    W, H = 640, 480
    out = []
    items = [
        ("run4/renders/lane_a/frame_0001.png", lambda p: julia(W, H, -0.7 + 0.27j, [(5, 5, 30), (40, 80, 200), (120, 220, 255), (255, 255, 255)]).save(p)),
        ("run4/renders/lane_a/frame_0002.png", lambda p: julia(W, H, -0.12 + 0.74j, [(30, 5, 10), (200, 40, 60), (255, 190, 90), (255, 250, 220)]).save(p)),
        ("run4/models/knot_v3.glb", lambda p: write_glb(p, torus_knot(2, 5, segs=300), (0.55, 0.85, 0.4))),
    ]
    for rel, fn in items:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fn(path)
        out.append(path)
    return out


if __name__ == "__main__":
    make(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
