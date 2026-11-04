# spatialvibe-mcp

**写真と目的から、その場所にぴったり合う 3D プリント部品を Claude と一緒に決めて作る MCP サーバー。**

畑・ハウス・トラクターで「ここにこれを付けたい」と思ったとき、Claude が選択肢で聞き返して形を決め、
手元の資料から寸法を探し、build123d で 3D データを作り、iPhone の AR で実寸を重ねて確かめるところまで進めます。
部品テンプレートは持ちません。目的に合う形は型にはまらないからです。

## 役割分担

| | 担当 |
| --- | --- |
| **Claude** | 写真を読む・選択肢で聞く・寸法を探す・ずれを吸収する形を考える・build123d のコードを書く |
| **この MCP サーバー** | コードの実行（隔離）・形の検査・4 方向プレビュー・実寸 USDZ の作成と iPhone への受け渡し |

進め方は [`spatialvibe_mcp/WORKFLOW.md`](spatialvibe_mcp/WORKFLOW.md) にあり、サーバーの instructions として Claude に渡ります。

## ツール

| ツール | 内容 |
| --- | --- |
| `build_model(project, code, note)` | build123d スクリプトを別プロセスで実行。`parts`（印刷するもの）と `context`（周囲：パイプ・箱など）を STL/STEP に。形の有効性・体積・外形・**丸穴**・**ベッドに入るか**・部品全体の大きさ、**部品と周囲の重なり**を返す。任意で `hardware`（買うもの）と `checks`（印刷前に確認）を書くと結果とシートに載る。版ごと（v001, v002…）に保存 |
| `preview(project, version?)` | 4 方向の画像と **寸法シート**（スマホ 1 画面: 部品ごとの W×D×H・穴・ベッドに入るか・上/正面の寸法線、買うもの、印刷前に確認）。Claude が自分で見て直し、シートをユーザーに渡す |
| `publish_ar(project, version?)` | 実寸 USDZ（m, Y-up）を作り iCloud Drive の `SpatialVibe/` に置く → iPhone の「ファイル」からタップで AR。回線を問わない |
| `list_projects` / `get_code` | 版の一覧、過去のスクリプト |

macOS では実行を `sandbox-exec` で囲み、ネットワークと版フォルダ外への書き込みを禁止しています（個人の Mac で使う前提の最低限の隔離です）。

## セットアップ（macOS）

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
claude mcp add --scope user -e PYTHONPATH=$(pwd) -- spatialvibe $(pwd)/.venv/bin/python -m spatialvibe_mcp
```

Claude Desktop では `claude_desktop_config.json` の `mcpServers` に同じコマンドを書きます。

| 環境変数 | 既定 | 意味 |
| --- | --- | --- |
| `SPATIALVIBE_HOME` | `./data/mcp_projects` | プロジェクトと版の保存先 |
| `SPATIALVIBE_PUBLISH` | `icloud` | AR ファイルの置き場所（`icloud` / `dir:/path`） |
| `SPATIALVIBE_TIMEOUT` | `180` | 1 回の実行の制限秒数 |
| `SPATIALVIBE_BED` | `256,256,256` | プリンタの造形範囲 mm（`fits_bed` の判定） |

## 作例

[`examples/aio_mount/model.py`](examples/aio_mount/model.py) — トラクターの 1 インチ手すりパイプ（Ø25.6 mm）に
AgOpenGPS の AIO ボックス（Hammond 1455Q2201）を水平に載せるマウント。上下 2 分割クランプ ×2、
M8 調整脚でお辞儀止めと水平出し、後ろパネルのネジで抜け止め。

## 進捗リール（20 秒の動画）

`reels/<日付>-<slug>/scenes.json` を書くと、`reel/make_reel.py` が 20 秒のキネティックタイポグラフィを作ります。
120 BPM・10 小節。音楽は場面の並びから合成し（ブレイク・ライザー・ドロップ）、文字はキックに合わせて鼓動します。
出力は 1920×1080・30 fps・AAC 音声つきの MP4 と、音つきで再生できる HTML。Claude Code ではコミットのたびに「動画にしますか？」と聞かれ、
答えると `progress-reel` サブエージェントが前回以降の変更から台本を書いて書き出します。

```bash
uv pip install --python .venv/bin/python -r requirements-reel.txt && .venv/bin/python -m playwright install chromium
.venv/bin/python reel/make_reel.py reels/2026-11-04-app-to-mcp
```

## エージェントでの試験（現場の使い方を再現）

`.claude/agents/` の 3 つのサブエージェント（`field-user` 農家役・`designer` 設計役・`checker` 検証役）で、
現場からの依頼 → 質問 → 回答 → 設計 → 検証と評価 を 1 ラウンドとして回し、見つかった問題でツールと
WORKFLOW.md を直します。記録は [`sessions/`](sessions/README.md)、ツールはシェルから `tools/sv.py` で呼べます。

## テスト

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## 限界

写真 1 枚から正確な寸法はわかりません。AR は見た目と大きさの確認で、強度や取り付けの保証ではありません。
スライスと印刷は各自のプリンタで行います（屋外は PETG / ASA 推奨）。

経緯: 最初は Web アプリ（[spatial-vibe-modeling-app](https://github.com/tomiyasu0428/spatial-vibe-modeling-app)）として作り、2026-11-04 に MCP サーバーへ移りました。
