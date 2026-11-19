#!/usr/bin/env python3
"""Regenerate the README screenshots in docs/screenshots/ from a real running Live Gallery.

Dev-only helper (not needed to use Live Gallery). It creates procedural demo files under
/tmp/lg-demo, starts the server with an empty throw-away HOME (so none of your own
folders or saved state appear), drives it with headless Chromium and saves optimized PNGs.

    pip install playwright pillow numpy && playwright install chromium
    python3 scripts/screenshots.py                 # Python version (./live-gallery)
    python3 scripts/screenshots.py --rust BINARY   # Rust build, e.g. target/release/live-gallery

Set CHROMIUM_PATH to use a specific Chromium/headless-shell binary.
"""
import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import demo_data  # noqa: E402

DEMO = "/tmp/lg-demo"
A, B = f"{DEMO}/agent-output", f"{DEMO}/design-exports"
GL = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def log(*m):
    print(*m, flush=True)


def save(src, dst, width=1280):
    im = Image.open(src).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(dst, optimize=True)
    kb = os.path.getsize(dst) // 1024
    if kb > 400:  # fall back to a palette PNG to stay small
        im.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(dst, optimize=True)
        kb = os.path.getsize(dst) // 1024
    print(f"{os.path.relpath(dst, REPO)}: {im.width}x{im.height}, {kb} KB")


def terminal_html(blocks):
    rows = []
    for cmd, out in blocks:
        rows.append(f'<div class="p"><span class="d">$</span> {html.escape(cmd)}</div>')
        rows.append(f'<div class="o">{html.escape(out.rstrip())}</div>')
    return f"""<body style="margin:0;background:#0f1117"><div style="width:880px;box-sizing:border-box;padding:0;
background:#1b1e27;font:14px/1.5 'DejaVu Sans Mono',monospace;color:#d7dae0">
<div style="background:#2a2e3a;padding:9px 14px;display:flex;gap:7px;align-items:center">
<i style="width:12px;height:12px;border-radius:6px;background:#ff5f56"></i><i style="width:12px;height:12px;border-radius:6px;background:#ffbd2e"></i><i style="width:12px;height:12px;border-radius:6px;background:#27c93f"></i>
<span style="margin-left:10px;color:#9aa3b2;font-size:12px">terminal</span></div>
<div style="padding:16px 20px"><style>.p{{color:#fff;margin-top:6px}}.d{{color:#7ee787}}.o{{white-space:pre-wrap;color:#c3c8d2}}</style>
{''.join(rows)}</div></div></body>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rust", metavar="BINARY", help="use a built Rust binary instead of ./live-gallery")
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "screenshots"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cmd0 = [os.path.abspath(a.rust)] if a.rust else [sys.executable, os.path.join(REPO, "live-gallery")]
    shutil.rmtree(DEMO, ignore_errors=True)
    demo_data.make(A, B)
    home = tempfile.mkdtemp(prefix="lg-home-")
    scratch = tempfile.mkdtemp(prefix="lg-shots-")
    env = dict(os.environ, HOME=home, USERPROFILE=home, XDG_CONFIG_HOME="", XDG_CACHE_HOME="", PYTHONUNBUFFERED="1")
    env.pop("XDG_CONFIG_HOME"); env.pop("XDG_CACHE_HOME")
    shown_cmd = "live-gallery " + A + " " + B
    help_out = subprocess.run(cmd0 + ["--help"], capture_output=True, text=True, env=env).stdout
    srv = subprocess.Popen(cmd0 + [A, B], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    try:
        lines = []
        while True:
            ln = srv.stdout.readline()
            if not ln:
                raise SystemExit("server exited early:\n" + "".join(lines))
            lines.append(ln)
            if "indexed in" in ln:
                break
        url = re.search(r"http://\S+", "".join(lines)).group(0)
        start_out = "".join(lines)
        with sync_playwright() as p:
            kw = {"args": GL}
            if os.environ.get("CHROMIUM_PATH"):
                kw["executable_path"] = os.environ["CHROMIUM_PATH"]
            br = p.chromium.launch(**kw)
            pg = br.new_page(viewport={"width": 1440, "height": 900})
            pg.goto(url)
            pg.wait_for_selector(".card", timeout=15000) if pg.query_selector(".card") is None else None
            wait_thumbs = lambda: pg.wait_for_function("!document.querySelector('.thumb.pending')", timeout=60000)
            log('loaded'); wait_thumbs(); pg.wait_for_timeout(800); log('thumbs ready')

            # Files arriving while the page is open -> NEW badges on top (hero shot)
            demo_data.make_late(A)
            pg.wait_for_selector(".tag", timeout=15000); log('new tags')
            pg.wait_for_timeout(1500); wait_thumbs(); pg.wait_for_timeout(800)
            pg.mouse.move(5, 890)
            shot = lambda name: (pg.screenshot(path=f"{scratch}/{name}.png"), save(f"{scratch}/{name}.png", f"{a.out}/{name}.png"))
            shot("gallery")

            def open_card(name, wait_ms):
                pg.locator(".card", has=pg.locator(f".name:text-is('{name}')")).first.click()
                pg.wait_for_selector("#lb.open"); pg.wait_for_timeout(wait_ms)

            open_card("sunset_study.jpg", 1500); shot("viewer-image")
            pg.keyboard.press("Escape")
            open_card("knot_v1.glb", 6000); shot("viewer-3d")
            pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

            pg.fill("#q", "renders"); pg.wait_for_timeout(800); wait_thumbs()
            pg.mouse.move(5, 890); shot("filter-path")
            br.close()

            br = p.chromium.launch(**{k: v for k, v in kw.items() if k != "args"})
            pg = br.new_page(viewport={"width": 880, "height": 100}, device_scale_factor=1)
            pg.set_content(terminal_html([(shown_cmd, start_out), ("live-gallery --help", help_out)]))
            pg.screenshot(path=f"{scratch}/cli.png", full_page=True)
            save(f"{scratch}/cli.png", f"{a.out}/cli.png")
            br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(5)
        except subprocess.TimeoutExpired:
            srv.kill()
        shutil.rmtree(home, ignore_errors=True); shutil.rmtree(scratch, ignore_errors=True)
        shutil.rmtree(DEMO, ignore_errors=True)


if __name__ == "__main__":
    main()
