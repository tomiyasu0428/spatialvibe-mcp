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


def _screen_png(path: Path):
    """The same little field-guidance UI that assembly.html draws on the phone screen."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (512, 1024), "#0e1a2b")
    d = ImageDraw.Draw(im)
    for i in range(-6, 7):
        d.line([(256 + i * 28, 240), (256 + i * 140, 1024)], fill="#2f8f4e", width=12)
    d.line([(256, 240), (256, 1024)], fill="#ff5a1f", width=16)
    d.polygon([(256, 760), (216, 860), (296, 860)], fill="#ffffff")
    d.rectangle([0, 0, 512, 140], fill="#0b0f16")
    try:
        font = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 56)
    except OSError:
        font = ImageFont.load_default()
    d.text((40, 40), "AB  +0.02 m", fill="#cfe3ff", font=font)
    im.save(path)


def export_scene(story: dict, meshes: dict, stem: str) -> Path:
    """Triangles in model axes (mm, Z up) + metadata for blender_render.py."""
    import numpy as np
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    arrs = {n: np.stack([m["pos"][:, 0], -m["pos"][:, 2], m["pos"][:, 1]], axis=1).reshape(-1, 3, 3)
            for n, m in meshes.items()}
    npz = out / f"{stem}_scene.npz"
    np.savez(npz, **arrs)
    png = out / f"{stem}_screen.png"
    _screen_png(png)
    meta = {"kinds": {n: m["kind"] for n, m in meshes.items() if not n.startswith("_")},
            "steps": story["steps"], "screen_of": story["fit"].get("screen_of"),
            "slide": story["fit"].get("slide", [0, 0, 1]), "screen_png": str(png)}
    npz.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return npz


def build_html(story_path: Path, photos: dict, frames: Path = None, export: bool = False):
    story = json.loads(story_path.read_text(encoding="utf-8"))
    ns = runpy.run_path(str(ROOT / story["model"]))
    meshes = {}
    for kind in ("parts", "context"):
        for name, shape in ns[kind].items():
            meshes[name] = {"kind": kind, "pos": _mesh(shape)}
    scr = story.get("fit", {}).get("screen_of")
    if scr in meshes:
        meshes["_screen"] = {"kind": "screen", "pos": _screen(meshes[scr]["pos"])}
    scene = export_scene(story, meshes, story_path.stem) if export else None
    for m in meshes.values():
        m["pos"] = _b64(m["pos"])
    if not THREE.exists():
        sys.exit(f"three.js missing: run (cd {HERE.relative_to(ROOT)} && npm install)")
    data = dict(story, meshes=meshes, photos={k: _photo(v) for k, v in photos.items()},
                three=base64.b64encode(THREE.read_bytes()).decode())
    if frames and (frames / "frames.json").exists():   # Blender backdrop instead of three.js
        data["frames"] = dict(json.loads((frames / "frames.json").read_text()), dir=frames.name)
    tpl = (HERE / "assembly.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    dst = out / f"{story_path.stem}{'_blender' if frames else ''}.html"
    dst.write_text(html, encoding="utf-8")
    return dst, scene


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
    ap.add_argument("--blender", action="store_true",
                    help="render the 3D with Blender (.venv-blender, bpy) and lay the captions over it")
    ap.add_argument("--engine", default="cycles", choices=["eevee", "cycles"])
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--step", type=int, default=1, help="Blender: render every Nth frame (2 = quick pass)")
    ap.add_argument("--scale", type=int, default=67, help="Blender: resolution %% (upscaled to 1080x1920)")
    a = ap.parse_args()
    story = Path(a.story)
    photos = {"place": a.place, "thing": a.thing, "ar": a.ar}
    frames = HERE / "out" / f"{story.stem}_blender" if a.blender else None
    page, scene = build_html(story, photos, frames, export=a.blender)
    if a.blender:
        import subprocess
        bl = ROOT / ".venv-blender" / "bin" / "python"
        if not bl.exists():
            sys.exit("Blender venv missing: uv venv --python 3.13 .venv-blender && "
                     "uv pip install --python .venv-blender/bin/python bpy numpy")
        cmd = [str(bl), str(HERE / "blender_render.py"), str(scene), str(frames), "--engine", a.engine]
        cmd += ["--step", str(a.step), "--scale", str(a.scale)]
        if a.samples:
            cmd += ["--samples", str(a.samples)]
        if a.frame is not None:
            f = round(a.frame * FPS / 1000)
            cmd += ["--frames", f"{f}-{f}"]
        subprocess.run(cmd, check=True)
        page, _ = build_html(story, photos, frames)
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
