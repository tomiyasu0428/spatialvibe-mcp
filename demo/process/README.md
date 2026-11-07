# demo/process — 役割分担アニメーション（デモ動画の挿入カット）

写真から 3D プリントまでの全工程を、**誰がやるか**（人 / Claude / MCP）の 3 レーンに置いて順に点灯させ、最後に MCP の 6 ツールをカードで並べる約 41 秒の無音クリップ。
デモ動画の冒頭説明（「Claude が考え、MCP が動かし、人は確かめる」）の下に敷く。ナレーションは動画側で付ける。

- `process.html` … 自己完結。ブラウザで開けば再生ボタンで見られる。工程・文言・タイミングは先頭の `LANES` / `STEPS` / `TOOLS` / 時間定数を編集する。ツールの説明は README のツール表と合わせる。
- `render.py` … `process.mp4`（1920×1080・30 fps・H.264・無音）を書き出す。`--frame <ms>` で 1 枚だけ PNG。

```bash
.venv/bin/pip install -r requirements-reel.txt pillow
.venv/bin/python demo/process/render.py
# playwright 同梱の Chromium がない環境では SPATIALVIBE_CHROMIUM=/path/to/chrome を指定
```

`reel/engine.html`（進捗リール）とは独立。リール側は 20 秒・ビート同期の制約があるので、ここでは使わない。
