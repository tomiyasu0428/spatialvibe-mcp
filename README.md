# Pittari（ぴったり）

**写真と目的から、その場所にぴったり合う 3D プリント部品を Claude と一緒に決めて作る MCP サーバー。**

製品名は Pittari。コード上の名前（パッケージ `spatialvibe_mcp`、環境変数 `SPATIALVIBE_*`、MCP サーバー名 `spatialvibe`）は開発中の旧名のまま使っています。

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
| `build_model(project, code, note, printer?)` | build123d スクリプトを別プロセスで実行。`parts`（印刷するもの）と `context`（周囲：パイプ・箱など）を STL/STEP に。形の有効性・体積・外形・**穴と長穴の中心座標**（`hole_list`）・**STL が閉じているか**・**ベッドに入るか**・部品全体の大きさ、**部品と周囲の重なり**（計算できなかった組は `interference_unchecked` ＝ 未判定）と **`warnings`** を返す。失敗した版には部品ファイルが残らず、プレビューも AR 公開もできない。任意で `dims`（**合わせる寸法**: 穴の間隔・口の幅・厚み・角度・周囲とのすき間をツールが形から測り、シートに青で描く。`expect` とずれたら警告）、`origin`（原点の説明）、`print_pose`（印刷の向き）、`hardware`（買うもの）、`checks`（印刷前に確認）を書ける。版ごと（v001, v002…）に保存。`printer`（`a1mini` か `WxDxH` mm）を渡すと部品ごとに**造形範囲チェック**（入る / 超過 / プリンター未設定）を返す |
| `preview(project, version?)` | 4 方向の画像と寸法シート 2 枚。**sheet.png**（1 枚目・スマホ向け: 買うもの、印刷前に確認、大事な合わせる寸法とその OK の範囲、取り付けたところの絵）と **sheet_detail.png**（2 枚目: 部品ごとの全寸法、測る場所の拡大図、3 面図、穴の位置など印刷する人向けの情報）。スクリプトに `print_settings` や `steps` があれば **sheet_build.png**（3 枚目: 印刷の設定と、絵つきの取り付け手順）も出す。ビルドのたびに、全部品を刷る向きで 1 枚に並べた **print_plate.3mf**（どのスライサーでも開ける）を作る。あわせて **print_job.json**（印刷を担当する AI 向け: ファイル・向き・設定・合わせる寸法・買うもの・手順）も作り、`get_print_job(project, version?)` で取り出せる。向きの約束: 使う人は −Y 側に立って +Y を見る（右手が +X） |
| `publish_ar(project, version?)` | 実寸 USDZ（m, Y-up）を作り iCloud Drive の `SpatialVibe/` に置く → iPhone の「ファイル」からタップで AR。回線を問わない。`SPATIALVIBE_PUBLISH=cloudflare` なら専用 Worker に送り、期限付きの HTTPS リンクを返す（Safari で開いて AR、[AR_PUBLICATION.md](AR_PUBLICATION.md)）。`SPATIALVIBE_AR_KEEP=icloud` を足すと、同じ USDZ を iCloud Drive にも残す（スマホホルダー・ラズパイ・AIO など、版ごとに溜まる）。スクリプトに `ar_floor`（床の Z, mm）を書くと、床の板と柱が入り、床に置くだけでパイプなど宙にある取付け場所の高さに出る |
| `export_print(project, version?, printer?, quantities?, material?, hardware?, notes?, part_notes?, include_zip?)` | 印刷準備への引き継ぎ。印刷姿勢の STL・STEP・スクリプト・`manifest.json`・日本語の案内・`AI_HANDOFF.txt` を 1 つのフォルダにまとめ、AI がそのまま続けられる形で返す（下記） |
| `list_projects` / `get_code` | 版の一覧、過去のスクリプト |

サーバーのエラー文（「その版はない」「名前は英数字で」など）は MCP の `ToolError` として返るので、Claude にそのまま届きます。

macOS では生成コードと描画処理を `sandbox-exec` で囲み、ネットワーク、他の実行ファイル、許可したコード・依存ライブラリ・作業用の一時領域以外のファイル内容の読み取りを制限します。子へ渡す環境変数も限定します。隔離を利用できない環境では実行を拒否します。検証済みの範囲と Cloudflare 公開の条件は [AR_PUBLICATION.md](AR_PUBLICATION.md) に記載しています。

### プリンターと印刷姿勢

- プリンターは機種を問いません。造形サイズを `printer="256x256x256"`（mm、幅×奥行×高さ）で指定します。
  よく使う機種はプリセット名でも書けます（現在のプリセットは `a1mini` = Bambu Lab A1 mini、180×180×180 mm の 1 つ）。
  指定がなければ環境変数 `SPATIALVIBE_PRINTER` を使い、それもなければ「未設定（未確認）」と返します（勝手に機種を仮定しません）。
- スクリプトは組付けた姿勢で書きます。印刷する向きは `print_orientation = {"部品名": (rx, ry, rz)}`（度、build123d の `Rot` と同じ）か `print_pose` で指定します。
  プレビューと AR は組付け姿勢のまま、印刷用 STL だけが回転して床（z=0）に置かれます。指定のない部品は「印刷姿勢 未確認」と記録されます。
- 「超過」はその向きでの外形が大きいという意味です。90° 回せば入る場合はヒントを返します。斜め置きや分割で入ることもあるので、印刷不可とは断定しません。

### 印刷準備への引き継ぎ（`export_print`）

設計が決まったら、AI が `export_print` で印刷用ファイルと条件をまとめ、そのまま印刷準備を続けます。人は条件を確認するのが役目です。

1. 版フォルダの中に `<project>_vNNN_print/` を作ります（この Mac の中だけ）。
2. AI は返り値（条件 `manifest`、各ファイルの絶対パス、`unconfirmed`、`next_steps`）を読み、条件を短く示します。未確認項目や不足する機種・スライサー設定のうち、なお必要な情報だけを人に聞きます。造形サイズだけでは機種やプロファイルは特定できません。
3. AI がスライサーやプリンターと連携できる場合は、この STL と条件で準備を続け、**実際に得られた値だけ**示します。**この MCP 自体はスライスも印刷もしません。** 連携がなければここで止まります。
4. 別の AI に頼むときは `AI_HANDOFF.txt`（返り値の `handoff` と同じ）を渡します。

```
<project>_vNNN_print/
  manifest.json       条件の正本：プリンター/造形範囲・材料・部品ごとの個数/印刷姿勢/外形/判定・金具・注意点・未確認・未実施の工程
  PRINT_GUIDE_ja.txt  同じ条件を人向けに書いた日本語の案内
  AI_HANDOFF.txt      別の AI に渡す短い引き継ぎ文
  stl/                <部品名>.stl。印刷姿勢・z=0 接地・mm
  step/               組付け姿勢、編集用
  source/model.py     この版のスクリプト
```

- 周囲（context）は入れません。渡されなかった個数・材料・金具は「未確認」と書きます。
- 失敗した版、形が壊れている部品、造形範囲を超える部品があると出力せず、理由を返します。
- ZIP は `include_zip=true` のときだけ作ります。ZIP なしで出力し直すと古い ZIP は削除します。

## セットアップ（macOS）

### 1. 取得と前提

```bash
git clone https://github.com/tomiyasu0428/spatialvibe-mcp.git
cd spatialvibe-mcp
```

macOS、git、[uv](https://docs.astral.sh/uv/)（`brew install uv`。Python 3.12 は uv が用意します）、Claude Code または Claude Desktop。

### 2. セットアップと点検

```bash
scripts/setup.sh                 # 何度実行しても OK。.venv（Python 3.12）作成 → 依存を入れる → doctor
scripts/setup.sh --printer a1mini   # 任意：既定のプリンターを表示される設定に含める
```

最後に doctor が Python・依存パッケージ・sandbox・保存先・AR の置き場所・試しのビルドを点検し、下の接続設定をこの checkout の絶対パスで表示します。
**Claude の設定ファイルは書き換えません。** 点検だけなら `.venv/bin/python -m spatialvibe_mcp.doctor`、Desktop 用 JSON だけなら `--json`。

### 3. Claude につなぐ

```bash
claude mcp add --scope user -e PYTHONPATH=$(pwd) -- spatialvibe $(pwd)/.venv/bin/python -m spatialvibe_mcp
```

Claude Desktop では `claude_desktop_config.json` の `mcpServers` に同じコマンドを書きます（doctor が JSON を表示します）。
Cloudflare 公開を使うときは `tools/ar_mcp_launch.py` 経由で起動します（[AR_PUBLICATION.md](AR_PUBLICATION.md)）。

| 環境変数 | 既定 | 意味 |
| --- | --- | --- |
| `SPATIALVIBE_HOME` | `./data/mcp_projects` | プロジェクトと版の保存先 |
| `SPATIALVIBE_PUBLISH` | `icloud` | AR ファイルの置き場所（`icloud` / `dir:/path` / `cloudflare`）。既定は変更していません |
| `SPATIALVIBE_TIMEOUT` | `180` | 1 回の実行の制限秒数 |
| `SPATIALVIBE_BED` | `256,256,256` | プリンタの造形範囲 mm（`fits_bed` の判定） |
| `SPATIALVIBE_PRINTER` | 未設定 | `build_model` / `export_print` の `printer` を省略したときのプリンター（`a1mini` または `WxDxH`）。未設定なら造形範囲の判定は `printer_not_set` |

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
