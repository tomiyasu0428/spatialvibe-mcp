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
MUSIC = HERE / "assets" / "music.mp3"          # optional: muxed under the whole video with a fade-out
# Region (x, y, w, h) in the phone recording's own pixels that is blurred (the Mac's name in the header).
BLUR = {"assets/phone.mov": (240, 158, 300, 50)}
FPS, W, H = 30, 1920, 1080
# Final order: page chapters by id, ("process", start_s, end_s, speed) segments of the process clip,
# or ("footage", path, start_s, end_s, speed) for real footage under demo/video/assets/ (local only).
ORDER = [
    "tease",                                                  # the finished part, then the bare holes + the question
    "open", ("process", 0, 12.2, 1.35), "how", "field",
    # real: the phone recording (Remote Control -> Claude -> questions -> dims -> preview -> AR link -> AR), captioned
    ("footage", "assets/phone.mov", 1.0, 4.5, 1.0, "写真と一言を送る"),
    ("footage", "assets/phone.mov", 10.5, 13.5, 1.0, "Claude が選択肢で聞く：どんな状態で付ける？"),
    ("footage", "assets/phone.mov", 21.0, 23.5, 1.0, "どのくらい外す？"),
    ("footage", "assets/phone.mov", 38.5, 42.0, 1.0, "何をつなぐ？"),
    ("footage", "assets/phone.mov", 108.0, 111.0, 1.0, "測るのは 2 か所：穴のピッチと、床からの高さ"),
    ("footage", "assets/phone.mov", 148.0, 151.0, 1.0, "プレビューが届く"),
    ("footage", "assets/phone.mov", 166.0, 169.0, 1.0, "AR に公開"),
    ("footage", "assets/phone.mov", 177.0, 180.5, 1.0, "推定した値は「推定」と明記"),
    ("footage", "assets/phone.mov", 183.0, 187.0, 1.0, "届いたリンクをタップ"),
    ("footage", "assets/phone.mov", 192.0, 194.5, 1.0, "AR ページ"),
    ("footage", "assets/phone.mov", 201.0, 204.0, 1.0, "自宅で試した AR。現場の画面は、次"),
    "ar", "done", ("process", 31.05, 38.5, 1.0), "export", "close",
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


CAPTION_HTML = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@700;900&display=block">
<style>html,body{margin:0;width:1920px;height:1080px;background:transparent;overflow:hidden}
.c{position:absolute;left:50%;bottom:64px;transform:translateX(-50%);display:flex;align-items:center;gap:22px;
background:rgba(13,14,16,.86);padding:18px 34px;border-radius:14px;white-space:nowrap}
.c i{display:block;width:10px;height:44px;background:#ff5a1f;border-radius:3px}
.c b{font:900 40px "Noto Sans JP",sans-serif;color:#f1f0ec;letter-spacing:-.02em}</style></head>
<body><div class="c"><i></i><b>__TEXT__</b></div></body></html>"""


def caption_png(text: str, out: Path):
    """Render one caption (bottom centre, transparent background) to a 1920x1080 PNG for ffmpeg overlay."""
    from playwright.sync_api import sync_playwright
    html = out.with_suffix(".html")
    html.write_text(CAPTION_HTML.replace("__TEXT__", text.replace("&", "&amp;").replace("<", "&lt;")), encoding="utf-8")
    with sync_playwright() as p:
        exe = os.environ.get("SPATIALVIBE_CHROMIUM")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        pg = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pg.goto(html.as_uri())
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(out), omit_background=True)
        browser.close()


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
            _, src, a, b, speed = item[:5]
            caption = item[5] if len(item) > 5 else None
            src = Path(src) if Path(src).is_absolute() else HERE / src
            if not src.exists():
                sys.exit(f"missing footage {src}")
            seg = clips / f"footage_{k}.mp4"
            fit = (f"setpts=PTS/{speed},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                   f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0d0e10,fps={FPS}")
            blur = BLUR.get(item[1])
            chain = "[0:v]"
            parts = []
            if blur:
                x, y, w, h = blur
                parts.append(f"{chain}split[base][tmp];[tmp]crop={w}:{h}:{x}:{y},boxblur=12:2,boxblur=12:2[blr];[base][blr]overlay={x}:{y}[v]")
                chain = "[v]"
            parts.append(f"{chain}{fit}[fitted]")
            extra_in = []
            if caption:
                png = clips / f"caption_{k}.png"
                caption_png(caption, png)
                extra_in = ["-i", str(png)]
                parts.append("[fitted][1:v]overlay=0:0[out]")
            else:
                parts.append("[fitted]null[out]")
            cmd = [ff, "-v", "error", "-y", "-ss", str(a)] + (["-to", str(b)] if b else []) + \
                  ["-i", str(src), *extra_in, "-an", "-filter_complex", ";".join(parts), "-map", "[out]",
                   "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", str(seg)]
            subprocess.run(cmd, check=True)
            inputs.append(seg)
        else:
            inputs.append(clips / f"{item}.mp4")
    lst = clips / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in inputs))
    silent = clips / "joined_silent.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent)], check=True)
    if not MUSIC.exists():
        silent.replace(out); return
    info = subprocess.run([ff, "-i", str(silent)], capture_output=True, text=True).stderr
    h, m, sec = info.split("Duration: ")[1].split(",")[0].split(":")
    dur = int(h) * 3600 + int(m) * 60 + float(sec)
    af = f"atrim=0:{dur:.3f},afade=t=in:st=0:d=1,afade=t=out:st={dur - 4:.3f}:d=4,volume=0.9"
    subprocess.run([ff, "-v", "error", "-y", "-i", str(silent), "-stream_loop", "-1", "-i", str(MUSIC), "-filter_complex", f"[1:a]{af}[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)], check=True)


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
