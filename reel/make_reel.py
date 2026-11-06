"""Build a 20-second beat-synced kinetic-typography reel from scenes.json.

Outputs in the reel folder: audio.wav (synthesised, 44.1 kHz stereo), reel.html (playable, sound
embedded) and reel.mp4 (1920x1080, 30 fps, H.264 + AAC).

Usage:
  .venv/bin/python reel/make_reel.py reels/<dir>              # everything
  .venv/bin/python reel/make_reel.py reels/<dir> --html-only  # skip the MP4
  .venv/bin/python reel/make_reel.py reels/<dir> --check      # validate scenes.json only

Frames are rendered deterministically (seek -> screenshot) and the music is generated from the same
scene timing, so picture and sound stay locked to the beat on any machine.
"""
import argparse
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import music  # noqa: E402

ROOT = Path(__file__).resolve().parent
BPM = 120
TOTAL_BARS = 10          # 10 bars at 120 BPM = 20 s
FPS = 30
W, H = 1920, 1080

FIELDS = {
    "drop": {"big"}, "stamp": {"big"}, "overflow": {"boxed", "burst"}, "stretch": {"big"},
    "swap": {"from", "to"}, "split": {"left", "right"}, "flow": {"steps"}, "final": {"big"},
}


def validate(reel: dict) -> list:
    errs = []
    scenes = reel.get("scenes") or []
    if reel.get("bpm", BPM) != BPM:
        errs.append(f"bpm must be {BPM}")
    if not 4 <= len(scenes) <= 10:
        errs.append(f"use 4-10 scenes (got {len(scenes)})")
    bars = 0
    for i, s in enumerate(scenes):
        t = s.get("type")
        if t not in FIELDS:
            errs.append(f"scene {i}: unknown type {t!r}; one of {sorted(FIELDS)}")
            continue
        missing = FIELDS[t] - set(s)
        if missing:
            errs.append(f"scene {i} ({t}): missing {sorted(missing)}")
        n = s.get("bars")
        if not isinstance(n, int) or not 1 <= n <= 3:
            errs.append(f"scene {i}: bars must be 1, 2 or 3 (got {n!r})")
        else:
            bars += n
        if t == "flow" and not 2 <= len(s.get("steps", [])) <= 4:
            errs.append(f"scene {i}: flow needs 2-4 steps")
        if t == "split" and not all("title" in s.get(k, {}) for k in ("left", "right")):
            errs.append(f"scene {i}: split needs left.title and right.title")
        if t == "final" and s.get("bars") != 2:
            errs.append(f"scene {i}: final must be 2 bars (hit + tail)")
    if scenes and scenes[-1].get("type") != "final":
        errs.append("last scene must be type 'final'")
    if bars != TOTAL_BARS:
        errs.append(f"bars must add up to {TOTAL_BARS} (got {bars})")
    return errs


def build(reel: dict, out: Path):
    st, hits = music.render(reel["scenes"], BPM)
    wav = out / "audio.wav"
    music.write_wav(wav, st)
    buf = io.BytesIO()
    music.write_wav(buf, music.mono_22k(st), sr=music.SR // 2)
    data = dict(reel, bpm=BPM, hits=hits)
    tpl = (ROOT / "engine.html").read_text(encoding="utf-8")
    html = (tpl.replace("/*__REEL__*/", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
               .replace("/*__AUDIO__*/", "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode())
               .replace("<title>spatialvibe reel</title>", f"<title>{reel.get('title', 'reel')}</title>"))
    page = out / "reel.html"
    page.write_text(html, encoding="utf-8")
    return page, wav


def record(page: Path, wav: Path, mp4: Path) -> None:
    import imageio_ffmpeg
    from PIL import Image
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmp:
        silent = Path(tmp) / "video.mp4"
        with sync_playwright() as p:
            exe = os.environ.get("REEL_CHROMIUM")  # e.g. a preinstalled Chromium in CI/containers
            browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
            pg = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            pg.goto(page.resolve().as_uri() + "?capture=1")
            pg.wait_for_function("window.reelReady !== undefined")
            pg.evaluate("window.reelReady")
            n = int(pg.evaluate("window.reelDuration") / 1000 * FPS)
            w = imageio_ffmpeg.write_frames(
                str(silent), (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p", quality=None,
                output_params=["-crf", "17", "-preset", "medium"], macro_block_size=8)
            w.send(None)
            for f in range(n):
                pg.evaluate(f"window.reelSeek({f * 1000 / FPS})")
                w.send(Image.open(io.BytesIO(pg.screenshot(type="png"))).convert("RGB").tobytes())
                if f % 60 == 0:
                    print(f"  frame {f}/{n}", file=sys.stderr)
            w.close()
            browser.close()
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(silent), "-i", str(wav),
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(mp4)],
                       check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reel_dir", type=Path)
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    reel = json.loads((a.reel_dir / "scenes.json").read_text(encoding="utf-8"))
    errs = validate(reel)
    if errs:
        print("scenes.json has problems:\n- " + "\n- ".join(errs))
        sys.exit(1)
    if a.check:
        print("ok")
        return
    page, wav = build(reel, a.reel_dir)
    print(page)
    if not a.html_only:
        mp4 = a.reel_dir / "reel.mp4"
        record(page, wav, mp4)
        print(mp4)


if __name__ == "__main__":
    main()
