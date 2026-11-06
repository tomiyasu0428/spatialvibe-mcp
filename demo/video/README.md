# demo/video — デモ動画のドラフト（約 1 分 46 秒・無音・1080p）

`video.html` が章ごとの画面（実写の写真、再現した会話、実ビルドの結果、AR、印刷引き継ぎ、締め）を決定論的に描き、
`render.py` が章を個別に書き出してから `demo/process/process.mp4` の 2 区間（工程図・ツール 6 枚）を間に挟んで `demo.mp4` に結合します。

- 会話は再現ですが、`build_model` の判定・寸法・警告、プレビュー画像、`export_print` の条件は `examples/pi_mount/model.py` を
  実際にビルドした結果（v001 → v003）をそのまま使っています。
- `assets/` は git 管理外（写真・プレビュー画像・AR 画像）。写真は Drive の「claudeハッカソン」から、プレビューは実ビルドから入れ直せます。
  AR の電話枠は `assets/ar_sim.png`（`tools/ar_sim.py` の模擬図）が仮。実機のスクショに差し替えるときは `video.html` の `s-ar` の画像パスを変えます。
- 章の順番と工程クリップの区間は `render.py` の `ORDER`、各章の秒数は `video.html` の `CHAPTERS`。

```bash
.venv/bin/python demo/process/render.py     # 先に工程クリップ
.venv/bin/python demo/video/render.py       # 章の書き出し → 結合 → demo/video/demo.mp4
.venv/bin/python demo/video/render.py --frame 24000   # 1 枚だけ確認
```
