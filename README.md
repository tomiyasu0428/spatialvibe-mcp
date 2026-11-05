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
| `build_model(project, code, note, printer?)` | build123d スクリプトを別プロセスで実行。`parts`（印刷するもの）と `context`（周囲：パイプ・箱など）を STL/STEP に。形の有効性・体積・外形、**部品と周囲の重なり**、部品ごとの**造形範囲チェック**（入る / 超過 / プリンター未設定）を返す。版ごと（v001, v002…）に保存 |
| `preview(project, version?)` | 4 方向の画像。Claude が自分で見て直す |
| `publish_ar(project, version?)` | 実寸 USDZ（m, Y-up）を作り iCloud Drive の `SpatialVibe/` に置く → iPhone の「ファイル」からタップで AR。回線を問わない |
| `export_print(project, version?, printer?, quantities?, material?, hardware?, notes?, part_notes?)` | 印刷に要るものを 1 つのフォルダと ZIP にまとめる（下記） |
| `list_projects` / `get_code` | 版の一覧、過去のスクリプト |

macOS では実行を `sandbox-exec` で囲み、ネットワークと版フォルダ外への書き込みを禁止しています（個人の Mac で使う前提の最低限の隔離です）。

### プリンターと印刷姿勢

- プリンターは `printer="a1mini"`（Bambu Lab A1 mini、180×180×180 mm）か、造形サイズ `"256x256x256"`（mm）で指定します。
  指定がなければ環境変数 `SPATIALVIBE_PRINTER` を使い、それもなければ「未設定」と返します（勝手に機種を仮定しません）。
- スクリプトは組付けた姿勢で書きます。印刷する向きは `print_orientation = {"部品名": (rx, ry, rz)}`（度、build123d の `Rot` と同じ）で指定します。
  プレビューと AR は組付け姿勢のまま、印刷用 STL だけが回転して床（z=0）に置かれます。指定のない部品は「印刷姿勢 未確認」と記録されます。
- 「超過」はその向きでの外形が大きいという意味です。90° 回せば入る場合はヒントを返します。斜め置きや分割で入ることもあるので、印刷不可とは断定しません。

### 印刷用ファイル（`export_print`）

版フォルダの中に `<project>_vNNN_print/` と同名の `.zip` を作ります（この Mac の中だけ。iCloud・スライサー・プリンターには何も送りません）。

```
<project>_vNNN_print/
  PRINT_GUIDE_ja.txt  日本語の印刷案内（個数・外形・印刷姿勢・造形範囲・材料・金具・注意点・未確認の項目）
  manifest.json       同じ内容の機械向け一覧
  stl/                <部品名>.stl。印刷姿勢・z=0 接地・mm（向き未指定の部品は案内と manifest に「未確認」と書く）
  step/               組付け姿勢、編集用
  source/model.py     この版のスクリプト
```

- 周囲（context）は入れません。渡されなかった個数・材料・金具は「未確認」と書き、確認済みのようには扱いません。
- 失敗した版、途中で止まった版、形が壊れている部品、造形範囲を超える部品があると出力せず、理由を返します。
- この機能より前に作った版は印刷姿勢の情報がないので、一度作り直します（`get_code` → `build_model`）。

## はじめかた（macOS）

### 1. 取得

```bash
git clone https://github.com/tomiyasu0428/spatialvibe-mcp.git
cd spatialvibe-mcp
```

### 2. 前提ツール

- macOS、git
- [uv](https://docs.astral.sh/uv/)（`brew install uv`）。Python 3.12 は uv が用意します（uv がなければ `python3.12` でも可）
- Claude Code または Claude Desktop

### 3. セットアップと点検

```bash
scripts/setup.sh                 # 何度実行しても OK。.venv（Python 3.12）作成 → 依存を入れる → doctor
scripts/setup.sh --printer a1mini   # 使うプリンターが決まっていれば、表示される設定に含める
```

最後に doctor が Python・依存パッケージ・sandbox・保存先・試しのビルドを点検し、下の接続設定をこの checkout の絶対パスで表示します。
**Claude の設定ファイルは書き換えません。** あとで点検だけしたいときは `.venv/bin/python -m spatialvibe_mcp.doctor`、
Desktop 用 JSON だけ欲しいときは `.venv/bin/python -m spatialvibe_mcp.doctor --json`。

### 4. Claude につなぐ

**Claude Code**（doctor が表示するコマンドを自分で実行）:

```bash
claude mcp add --scope user -e PYTHONPATH=/path/to/spatialvibe-mcp -- spatialvibe /path/to/spatialvibe-mcp/.venv/bin/python -m spatialvibe_mcp
```

**Claude Desktop**: `~/Library/Application Support/Claude/claude_desktop_config.json` に次を加え（他の `mcpServers` は残す）、Desktop を再起動します。
`/path/to/spatialvibe-mcp` は clone した場所の絶対パスです（doctor の表示をそのままコピーできます）。

```json
{
  "mcpServers": {
    "spatialvibe": {
      "command": "/path/to/spatialvibe-mcp/.venv/bin/python",
      "args": ["-m", "spatialvibe_mcp"],
      "env": {
        "PYTHONPATH": "/path/to/spatialvibe-mcp",
        "SPATIALVIBE_PRINTER": "a1mini"
      }
    }
  }
}
```

`SPATIALVIBE_PRINTER` の行は任意です（なければ Claude が最初に機種を聞きます）。

### 5. 最初の小さいモデル

Claude にこう頼みます:

> A1 mini を使っています。spatialvibe で 40×20×5 mm、M3 の穴が 2 つあるテスト板を作って、プレビューを見せてください。

Claude が `build_model` → `preview` を行い、造形範囲に入るかも返します。

### 6. 印刷用に出力

> 印刷用に出力して。PLA で 2 枚、金具はなし。

Claude が `export_print` を呼び、フォルダと ZIP の場所を伝えます。`stl/` をスライサー（Bambu Studio など）に読み込み、
`PRINT_GUIDE_ja.txt` の「未確認」が残っていないか確かめてから印刷してください。

### 環境変数

| 環境変数 | 既定 | 意味 |
| --- | --- | --- |
| `SPATIALVIBE_HOME` | `./data/mcp_projects` | プロジェクトと版の保存先（変えると、元の場所の版は見えなくなります。doctor が知らせます） |
| `SPATIALVIBE_PRINTER` | なし | 既定のプリンター（`a1mini` / `WxDxH`） |
| `SPATIALVIBE_PUBLISH` | `icloud` | AR ファイルの置き場所（`icloud` / `dir:/path`） |
| `SPATIALVIBE_TIMEOUT` | `180` | 1 回の実行の制限秒数 |

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

## テスト

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## 限界

写真 1 枚から正確な寸法はわかりません。AR は見た目と大きさの確認で、強度や取り付けの保証ではありません。
スライスと印刷は各自のプリンタで行います（屋外は PETG / ASA 推奨）。

経緯: 最初は Web アプリ（[spatial-vibe-modeling-app](https://github.com/tomiyasu0428/spatial-vibe-modeling-app)）として作り、2026-11-04 に MCP サーバーへ移りました。
