# demo/assembly — 組み上げリール（縦 30 秒）

写真 2 枚 → Claude が読み取る → 部品が 1 つずつ立ち上がる → スマホが入って画面が点く → AR で実寸、
という流れの縦型動画（1080×1920・30 fps・約 31 秒・無音）。題材は
[`examples/tractor_phone/model.py`](../../examples/tractor_phone/model.py)（トラクターの 1 インチ手すりに付けるスマホホルダー、4 部品）。

- `tractor_phone.json` … 台本。見出し・読み取った寸法・部品ごとの字幕（`steps` の順に立ち上がる）・最後の一言。モデルのパスもここ。
- `assembly.html` … テンプレート。時間は先頭の `T` で調整。
- `render.py` … モデルを実行してメッシュにし、台本と three.js と一緒に `out/<台本>.html` に埋め込み、1 コマずつ撮って `out/<台本>.mp4` にする。

```bash
(cd demo/assembly && npm install)                 # 初回だけ（three.js）
.venv/bin/python demo/assembly/render.py          # out/tractor_phone.mp4
.venv/bin/python demo/assembly/render.py --frame 15000   # 15 秒の 1 コマだけ PNG
# 実際の写真を入れる（out/ にだけ埋め込まれ、コミットされない）
.venv/bin/python demo/assembly/render.py --place 手すり.jpg --thing スマホ.jpg --ar AR画面.png
# playwright 同梱の Chromium がない環境では SPATIALVIBE_CHROMIUM=/path/to/chrome
```

写真を渡さないと、カードは仮のイラスト、AR の場面は 3D の画面に iPhone の枠をかぶせた見本になる。
投稿用には `--place` `--thing` に実際の 2 枚を、`--ar` に AR Quick Look のスクリーンショットを入れる。

スマホの寸法（ケース込み 160×78×12）は推定。印刷する前に実物を測ってモデルの `P` を直す。
