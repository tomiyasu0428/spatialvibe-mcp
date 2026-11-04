"""Build a 20-second kinetic-typography reel from scenes.json: HTML (playable) + MP4 (1920x1080, 30 fps).

Usage:
  .venv/bin/python reel/make_reel.py reels/2026-11-04-app-to-mcp            # html + mp4
  .venv/bin/python reel/make_reel.py reels/... --html-only                  # skip recording
  .venv/bin/python reel/make_reel.py reels/... --check                      # validate scenes.json only

Frames are rendered deterministically (seek -> screenshot), so the MP4 is smooth regardless of machine speed.
"""
import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOTAL_MS = 20000
FPS = 30
W, H = 1920, 1080

FIELDS = {
    "drop": {"big"}, "stamp": {"big"}, "overflow": {"boxed", "burst"}, "stretch": {"big"},
    "swap": {"from", "to"}, "split": {"left", "right"}, "flow": {"steps"}, "final": {"big"},
}


def validate(reel: dict) -> list:
    errs = []
    scenes = reel.get("scenes") or []
    if not 4 <= len(scenes) <= 10:
        errs.append(f"use 4-10 scenes (got {len(scenes)})")
    total = 0
    for i, s in enumerate(scenes):
        t = s.get("type")
        if t not in FIELDS:
            errs.append(f"scene {i}: unknown type {t!r}; one of {sorted(FIELDS)}")
            continue
        missing = FIELDS[t] - set(s)
        if missing:
            errs.append(f"scene {i} ({t}): missing {sorted(missing)}")
        d = s.get("dur")
        if not isinstance(d, int) or not 1400 <= d <= 4000:
            errs.append(f"scene {i}: dur must be an int 1400-4000 ms (got {d!r})")
        else:
            total += d
        if t == "flow" and not 2 <= len(s.get("steps", [])) <= 4:
            errs.append(f"scene {i}: flow needs 2-4 steps")
        if t == "split" and not all("title" in s.get(k, {}) for k in ("left", "right")):
            errs.append(f"scene {i}: split needs left.title and right.title")
    if scenes and scenes[-1].get("type") != "final":
        errs.append("last scene must be type 'final'")
    if total != TOTAL_MS:
        errs.append(f"durations must add up to {TOTAL_MS} ms (got {total})")
    return errs


def build_html(reel: dict, out: Path) -> Path:
    tpl = (ROOT / "engine.html").read_text(encoding="utf-8")
    data = json.dumps(reel, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("/*__REEL__*/", data).replace("<title>spatialvibe reel</title>", f"<title>{reel.get('title', 'reel')}</title>")
    path = out / "reel.html"
    path.write_text(html, encoding="utf-8")
    return path


def record(html: Path, mp4: Path) -> None:
    import imageio_ffmpeg
    from PIL import Image
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.goto(html.resolve().as_uri() + "?capture=1")
        page.wait_for_function("window.reelReady !== undefined")
        page.evaluate("window.reelReady")
        dur = page.evaluate("window.reelDuration")
        n = int(dur / 1000 * FPS)
        writer = imageio_ffmpeg.write_frames(
            str(mp4), (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p", quality=None,
            output_params=["-crf", "18", "-preset", "medium", "-movflags", "+faststart"], macro_block_size=8)
        writer.send(None)
        for f in range(n):
            page.evaluate(f"window.reelSeek({f * 1000 / FPS})")
            png = page.screenshot(type="png")
            writer.send(Image.open(io.BytesIO(png)).convert("RGB").tobytes())
            if f % 60 == 0:
                print(f"  frame {f}/{n}", file=sys.stderr)
        writer.close()
        browser.close()


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
    html = build_html(reel, a.reel_dir)
    print(html)
    if not a.html_only:
        mp4 = a.reel_dir / "reel.mp4"
        record(html, mp4)
        print(mp4)


if __name__ == "__main__":
    main()
