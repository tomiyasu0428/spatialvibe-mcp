"""Render demo/process/process.html to process.mp4 (1920x1080, 30 fps, silent H.264).

The page exposes the same capture hooks as reel/engine.html (reelReady / reelDuration / reelSeek),
so frames are rendered deterministically: seek -> screenshot -> encode. No audio: the clip is cut
into the demo video and narrated there.

Usage:
  .venv/bin/python demo/process/render.py                 # writes demo/process/process.mp4
  .venv/bin/python demo/process/render.py --frame 12000   # one PNG at t=12 s (process_12000.png)
"""
import argparse
import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FPS, W, H = 30, 1920, 1080


def open_page(p):
    exe = os.environ.get("SPATIALVIBE_CHROMIUM")  # e.g. /opt/pw-browsers/chromium when playwright's own download is absent
    browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    pg = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    pg.goto((HERE / "process.html").as_uri() + "?capture=1")
    pg.wait_for_function("window.reelReady !== undefined")
    pg.evaluate("window.reelReady")
    return browser, pg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", type=int, help="ms: write a single PNG instead of the MP4")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, pg = open_page(p)
        if a.frame is not None:
            pg.evaluate(f"window.reelSeek({a.frame})")
            out = HERE / f"process_{a.frame}.png"
            out.write_bytes(pg.screenshot(type="png"))
            print(out)
            browser.close()
            return
        import imageio_ffmpeg
        from PIL import Image
        n = int(pg.evaluate("window.reelDuration") / 1000 * FPS)
        out = HERE / "process.mp4"
        w = imageio_ffmpeg.write_frames(str(out), (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
                                        quality=None, output_params=["-crf", "17", "-preset", "medium", "-movflags", "+faststart"],
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
