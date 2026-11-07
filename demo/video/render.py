"""Render demo/video/video.html into demo.mp4 (1920x1080, 30 fps, silent H.264).

The page exposes reelReady / reelDuration / reelSeek like the reel engine, plus reelChapters.
Each chapter is rendered to its own clip, then the clips are joined in ORDER together with
segments of the process clip (demo/process/process.mp4, rendered first by its own render.py).

Usage:
  .venv/bin/python demo/video/render.py                  # chapters + join -> demo/video/demo.mp4
  .venv/bin/python demo/video/render.py --frame 20000    # one PNG at t=20 s of the page timeline
  .venv/bin/python demo/video/render.py --join-only      # re-join existing chapter clips
"""
import argparse
import io
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROCESS = HERE.parent / "process" / "process.mp4"
FPS, W, H = 30, 1920, 1080
# Final order: page chapters by id, ("process", start_s, end_s, speed) segments of the process clip,
# or ("footage", path, start_s, end_s, speed) for real footage under demo/video/assets/ (local only).
ORDER = [
    ("footage", "assets/board.mov", 0, 4.5, 1.0),            # real: boarding the tractor
    "open", "ba", ("process", 0, 26.5, 1.25), "how", "field",
    # real: the phone recording (Remote Control -> Claude -> questions -> dims -> preview -> AR link -> AR)
    ("footage", "assets/phone.mov", 1.0, 4.5, 1.0), ("footage", "assets/phone.mov", 10.5, 13.5, 1.0),
    ("footage", "assets/phone.mov", 21.0, 23.5, 1.0), ("footage", "assets/phone.mov", 38.5, 42.0, 1.0),
    ("footage", "assets/phone.mov", 108.0, 111.0, 1.0), ("footage", "assets/phone.mov", 148.0, 151.0, 1.0),
    ("footage", "assets/phone.mov", 166.0, 169.0, 1.0), ("footage", "assets/phone.mov", 183.0, 187.0, 1.0),
    ("footage", "assets/phone.mov", 192.0, 194.5, 1.0), ("footage", "assets/phone.mov", 198.0, 205.0, 1.0),
    "ar", "done", ("process", 31.05, None, 1.0), "export", "close",
]


def open_page(p):
    exe = os.environ.get("SPATIALVIBE_CHROMIUM")
    browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    pg = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    pg.goto((HERE / "video.html").as_uri() + "?capture=1")
    pg.wait_for_function("window.reelReady !== undefined")
    pg.evaluate("window.reelReady")
    return browser, pg


def write_clip(pg, out: Path, t0: float, t1: float):
    import imageio_ffmpeg
    from PIL import Image
    n = int(round((t1 - t0) / 1000 * FPS))
    w = imageio_ffmpeg.write_frames(str(out), (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p", quality=None,
                                    output_params=["-crf", "17", "-preset", "medium"], macro_block_size=8)
    w.send(None)
    for f in range(n):
        pg.evaluate(f"window.reelSeek({t0 + f * 1000 / FPS})")
        w.send(Image.open(io.BytesIO(pg.screenshot(type="png"))).convert("RGB").tobytes())
    w.close()


def join(out: Path):
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    clips = HERE / "clips"
    inputs, n = [], 0
    for k, item in enumerate(ORDER):
        if isinstance(item, tuple) and item[0] == "process":
            _, a, b, speed = item
            seg = clips / f"process_{int(a * 1000)}.mp4"
            cmd = [ff, "-v", "error", "-y", "-ss", str(a)] + (["-to", str(b)] if b else []) + \
                  ["-i", str(PROCESS), "-an", "-filter:v", f"setpts=PTS/{speed}", "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                   "-pix_fmt", "yuv420p", "-r", str(FPS), str(seg)]
            subprocess.run(cmd, check=True)
            inputs.append(seg)
        elif isinstance(item, tuple) and item[0] == "footage":
            # ("footage", path, start_s, end_s, speed): real footage (phone video, screen recording),
            # scaled to fit 1920x1080 with black bars, audio dropped, same codec as the chapters.
            _, src, a, b, speed = item
            src = Path(src) if Path(src).is_absolute() else HERE / src
            if not src.exists():
                sys.exit(f"missing footage {src}")
            seg = clips / f"footage_{k}.mp4"
            vf = (f"setpts=PTS/{speed},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                  f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0d0e10,fps={FPS}")
            cmd = [ff, "-v", "error", "-y", "-ss", str(a)] + (["-to", str(b)] if b else []) + \
                  ["-i", str(src), "-an", "-vf", vf, "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", str(seg)]
            subprocess.run(cmd, check=True)
            inputs.append(seg)
        else:
            inputs.append(clips / f"{item}.mp4")
    lst = clips / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in inputs))
    subprocess.run([ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", type=int)
    ap.add_argument("--join-only", action="store_true")
    a = ap.parse_args()
    out = HERE / "demo.mp4"
    if a.join_only:
        join(out); print(out); return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, pg = open_page(p)
        if a.frame is not None:
            pg.evaluate(f"window.reelSeek({a.frame})")
            png = HERE / f"frame_{a.frame}.png"; png.write_bytes(pg.screenshot(type="png")); print(png); browser.close(); return
        chapters = pg.evaluate("window.reelChapters")
        (HERE / "clips").mkdir(exist_ok=True)
        for ch in chapters:
            print(f"  chapter {ch['id']} {ch['start']}-{ch['end']} ms", file=sys.stderr)
            write_clip(pg, HERE / "clips" / f"{ch['id']}.mp4", ch["start"], ch["end"])
        browser.close()
    if not PROCESS.exists():
        sys.exit(f"missing {PROCESS}: run demo/process/render.py first")
    join(out)
    print(out)


if __name__ == "__main__":
    main()
