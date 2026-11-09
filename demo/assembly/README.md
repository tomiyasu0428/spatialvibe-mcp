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

## Blender でレンダリングする（`--blender`）

3D の部分だけを Blender（Cycles）で描き、字幕やカードは同じ HTML を上に重ねる。柔らかい影、金属のパイプ、光るスマホ画面、
CAD 風の輪郭線（Freestyle）が付く。タイミングとカメラの動きは three.js 版と同じ（`blender_render.py` の `timeline` と
`assembly.html` の `T` は手でそろえる）。

```bash
# 初回だけ: Blender 本体（bpy）は Python 3.13 の別 venv に入れる
uv venv --python 3.13 .venv-blender
uv pip install --python .venv-blender/bin/python bpy==5.2.3 numpy

.venv/bin/python demo/assembly/render.py --blender --step 2   # 速い下見（15 fps、コマを 2 回ずつ使う）
.venv/bin/python demo/assembly/render.py --blender            # 残りのコマを埋めて 30 fps に
.venv/bin/python demo/assembly/render.py --blender --frame 23500   # 1 コマだけ
```

- 出力は `out/tractor_phone_blender/NNNN.png`（背景は透明、床は影だけ）と `out/tractor_phone_blender.mp4`。
  描いたコマは再利用するので、モデルや照明を変えたら `out/tractor_phone_blender/` を消してから描き直す。
- 既定は 67% 解像度・16 サンプル・デノイズあり（CPU 4 コアで 1 コマ約 11 秒、全 570 コマで約 1 時間 45 分）。
  `--scale 100 --samples 48` で高画質、Mac なら GPU が使える分もっと速い。
- `--engine eevee` も選べるが、GPU のないサーバーではソフトウェア描画になり Cycles より遅い。
