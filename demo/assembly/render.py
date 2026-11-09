"""Vertical assembly reel: two photos in -> Claude reads them -> the parts rise one by one -> AR.

Runs the model script (parts + context), tessellates it, and inlines the meshes, the story
(<story>.json) and three.js into one self-contained HTML page. The page exposes the same capture
hooks as demo/process (reelReady / reelDuration / reelSeek), so frames are rendered
deterministically: seek -> screenshot -> encode. Silent H.264, 1080x1920, 30 fps, ~30 s.

Photos are optional and never committed (this repo is public): pass them at render time and they
are embedded only in the generated files under demo/assembly/out/.

Usage:
  (cd demo/assembly && npm install)            # once: three.js
  .venv/bin/python demo/assembly/render.py                       # out/tractor_phone.{html,mp4}
  .venv/bin/python demo/assembly/render.py --html-only           # just the page (open it to play)
  .venv/bin/python demo/assembly/render.py --frame 15000         # one PNG at t=15 s
  .venv/bin/python demo/assembly/render.py --place IMG_1.jpg --thing IMG_2.jpg --ar IMG_3.jpg
"""
import argparse
import base64
import io
import json
import mimetypes
import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FPS, W, H = 30, 1080, 1920
THREE = HERE / "node_modules" / "three" / "build" / "three.module.min.js"


def _b64(arr) -> str:
    import numpy as np
    return base64.b64encode(np.ascontiguousarray(arr, dtype="<f4").tobytes()).decode()


def _mesh(shape, tol=0.15):
    """Non-indexed triangle soup in three.js axes (metres are not needed: mm, Y up)."""
    import numpy as np
    verts, tris = shape.tessellate(tol, 0.2)
    v = np.array([(p.X, p.Z, -p.Y) for p in verts], dtype=float)   # Z-up mm -> Y-up
    return v[np.array(tris, dtype=int).reshape(-1)]


def _screen(tri):
    """The phone face that looks most toward the driver (-Y, a little up), shrunk to a screen."""
    import numpy as np
    t = tri.reshape(-1, 3, 3)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    want = np.array([0.0, 0.3, 1.0]); want /= np.linalg.norm(want)   # three axes: -Y(model) = +Z
    best = (n @ want).max()
    face = t[(n @ want) > best - 1e-3]
    pts = face.reshape(-1, 3)
    c = pts.mean(axis=0)
    out = c + (face - c) * np.array([0.9, 0.95, 0.9]) + n[(n @ want).argmax()] * 0.8
    return out.reshape(-1, 3)


def _photo(path):
    if not path:
        return None
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def build_html(story_path: Path, photos: dict) -> Path:
    story = json.loads(story_path.read_text(encoding="utf-8"))
    ns = runpy.run_path(str(ROOT / story["model"]))
    meshes = {}
    for kind in ("parts", "context"):
        for name, shape in ns[kind].items():
            meshes[name] = {"kind": kind, "pos": _mesh(shape)}
    scr = story.get("fit", {}).get("screen_of")
    if scr in meshes:
        meshes["_screen"] = {"kind": "screen", "pos": _screen(meshes[scr]["pos"])}
    for m in meshes.values():
        m["pos"] = _b64(m["pos"])
    if not THREE.exists():
        sys.exit(f"three.js missing: run (cd {HERE.relative_to(ROOT)} && npm install)")
    data = dict(story, meshes=meshes, photos={k: _photo(v) for k, v in photos.items()},
                three=base64.b64encode(THREE.read_bytes()).decode())
    tpl = (HERE / "assembly.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    dst = out / f"{story_path.stem}.html"
    dst.write_text(html, encoding="utf-8")
    return dst


def open_page(p, page: Path):
    exe = os.environ.get("SPATIALVIBE_CHROMIUM")
    args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
    browser = p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args)
    pg = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    pg.goto(page.as_uri() + "?capture=1")
    pg.wait_for_function("window.reelReady !== undefined")
    pg.evaluate("window.reelReady")
    return browser, pg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("story", nargs="?", default=str(HERE / "tractor_phone.json"))
    ap.add_argument("--place", help="photo of the place (e.g. the handrail)")
    ap.add_argument("--thing", help="photo of the thing to hold (e.g. the phone)")
    ap.add_argument("--ar", help="screenshot of the AR view on site")
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--frame", type=int, help="ms: write a single PNG instead of the MP4")
    a = ap.parse_args()
    story = Path(a.story)
    page = build_html(story, {"place": a.place, "thing": a.thing, "ar": a.ar})
    print(page)
    if a.html_only:
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, pg = open_page(p, page)
        if a.frame is not None:
            pg.evaluate(f"window.reelSeek({a.frame})")
            out = page.with_name(f"{story.stem}_{a.frame}.png")
            out.write_bytes(pg.screenshot(type="png"))
            print(out)
            browser.close()
            return
        import imageio_ffmpeg
        from PIL import Image
        n = int(pg.evaluate("window.reelDuration") / 1000 * FPS)
        out = page.with_suffix(".mp4")
        w = imageio_ffmpeg.write_frames(str(out), (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
                                        quality=None, output_params=["-crf", "18", "-preset", "medium", "-movflags", "+faststart"],
                                        macro_block_size=8)
        w.send(None)
        for f in range(n):
            pg.evaluate(f"window.reelSeek({f * 1000 / FPS})")
            w.send(Image.open(io.BytesIO(pg.screenshot(type="png"))).convert("RGB").tobytes())
            if f % 90 == 0:
                print(f"  frame {f}/{n}", file=sys.stderr)
        w.close()
        browser.close()
        print(out)


if __name__ == "__main__":
    main()
