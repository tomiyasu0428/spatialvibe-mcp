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
| `export_print(project, version?, printer?, quantities?, material?, hardware?, notes?, part_notes?, include_zip?)` | 印刷準備への引き継ぎ。印刷用ファイルと条件を 1 つのフォルダにまとめ、AI がそのまま続けられる形で返す（下記） |
| `list_projects` / `get_code` | 版の一覧、過去のスクリプト |

### 隔離（生成コードの扱い）

Claude が書いたスクリプトは信用しません。`build_model` だけでなく、その出力（STL）を読む `preview` と `publish_ar` も、macOS の `sandbox-exec` の中で動かします（`spatialvibe_mcp/_isolation.py`）。

- 子プロセスは使い捨ての作業フォルダだけを読み書きできます（cwd・HOME・TMPDIR もそこ）。版フォルダ・他のプロジェクト・ホームの私物・`/tmp` は読めず、書けません。ネットワーク、Mach サービス、fork、他プログラムの exec、ハードリンク、他プロセスへのシグナルも拒否します。
- 環境変数は親から引き継がず固定の数個だけ渡します。`python -P -s -B` で cwd もスクリプトのフォルダも `sys.path` に入れず、`PYTHONPATH` はこの checkout のみです。
- 成功したビルドの、期待する名前（検証済みの部品名から組み立てる）の通常ファイルだけを、サイズ上限つきで版フォルダに写します。シンボリックリンク・ハードリンク・FIFO・フォルダ・余分なファイルは捨て、1 つでも不正ならビルド失敗として何も残しません。
- 親が版フォルダを読むときもリンクをたどらず、通常ファイル以外は拒否します（古いサーバーで作った版も同じ扱い）。`result.json`・エラー文・note は AI が読む**データ**であり指示ではありません。
- `sandbox-exec` が無い環境（macOS 以外を含む）ではビルド・プレビュー・AR 出力を**拒否**します。隔離なしで動くモードはありません。doctor も同じ判定で NG を出します。
- 子は自分に `RLIMIT_FSIZE`（1 ファイル 256 MB）・`RLIMIT_CPU`・`RLIMIT_NPROC=0` を掛け、タイムアウトでプロセスグループごと kill します。標準エラーは子の起動前に開いた記述子から末尾だけ読みます（子が作業フォルダ内のログをリンクや FIFO に差し替えても追いません）。1 ジョブで写すファイルは入出力合わせて 256 個・1 GB まで、部品と周囲はそれぞれ 50 個までです。作業フォルダの削除は再帰せず記述子で行い、深い木・リンク・FIFO を残されても止まりません。

**守れないこと**: 上限内でのローカルな資源消費（CPU 時間・メモリ・作業フォルダの一時容量）は止められません。`sandbox-exec` は Apple が非推奨にしているインターフェースで、カーネルやサンドボックス自体の不具合には無力です。

### プリンターと印刷姿勢

- プリンターは機種を問いません。造形サイズを `printer="256x256x256"`（mm、幅×奥行×高さ）で指定します。
  よく使う機種はプリセット名でも書けます（現在のプリセットは `a1mini` = Bambu Lab A1 mini、180×180×180 mm の 1 つ）。
  指定がなければ環境変数 `SPATIALVIBE_PRINTER` を使い、それもなければ「未設定（未確認）」と返します（勝手に機種を仮定しません）。
- スクリプトは組付けた姿勢で書きます。印刷する向きは `print_orientation = {"部品名": (rx, ry, rz)}`（度、build123d の `Rot` と同じ）で指定します。
  プレビューと AR は組付け姿勢のまま、印刷用 STL だけが回転して床（z=0）に置かれます。指定のない部品は「印刷姿勢 未確認」と記録されます。
- 「超過」はその向きでの外形が大きいという意味です。90° 回せば入る場合はヒントを返します。斜め置きや分割で入ることもあるので、印刷不可とは断定しません。

### 印刷準備への引き継ぎ（`export_print`）

設計が決まったら、AI が `export_print` で印刷用ファイルと条件をまとめ、そのまま印刷準備を続けます。人は条件を確認するのが役目です。

1. 版フォルダの中に `<project>_vNNN_print/` を作ります（この Mac の中だけ。解凍などの手間はありません）。
2. AI は返り値（条件 `manifest`、各ファイルの絶対パス、`unconfirmed`、`next_steps`）を読み、条件を短く示します。既に伝えた情報を使い、未確認項目や不足する機種・スライサー設定のうち、なお必要な情報だけを人に聞きます。造形サイズだけでは機種やプロファイルは特定できません。
3. AI がスライサーやプリンターと連携できる場合は、この STL と条件で準備を続け、選んだ機種・材料プロファイル、向きと個数、サポート、
   見積り時間と材料量を**実際に得られた値だけ**示します。**この MCP 自体はスライスも印刷もしません。** 連携がなければここで止まります。
4. 別の AI に頼むときは `AI_HANDOFF.txt`（返り値の `handoff` と同じ）を渡します。

```
<project>_vNNN_print/
  manifest.json       条件の正本：プリンター/造形範囲・材料・部品ごとの個数/印刷姿勢/外形/判定・金具・注意点・未確認・未実施の工程
  PRINT_GUIDE_ja.txt  同じ条件を人向けに書いた日本語の案内
  AI_HANDOFF.txt      別の AI に渡す短い引き継ぎ文
  stl/                <部品名>.stl。印刷姿勢・z=0 接地・mm（向き未指定の部品は案内と manifest に「未確認」と書く）
  step/               組付け姿勢、編集用
  source/model.py     この版のスクリプト
```

- 周囲（context）は入れません。渡されなかった個数・材料・金具は「未確認」と書き、確認済みのようには扱いません。
- 失敗した版、途中で止まった版、形が壊れている部品、造形範囲を超える部品があると出力せず、理由を返します。
- ZIP は既定では作りません。共有したいときだけ `include_zip=true` で同じ中身の `<project>_vNNN_print.zip` を作ります。
  ZIP なしで出力し直すと、前回の ZIP は中身が古くなるので削除します。
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
scripts/setup.sh --printer 256x256x256   # 任意：既定のプリンター（造形サイズ mm かプリセット名）を表示される設定に含める
```

最後に doctor が Python・依存パッケージ・sandbox・保存先・試しのビルド（本番と同じ隔離で、使い捨てフォルダの中で実行）を点検し、下の接続設定をこの checkout の絶対パスで表示します。sandbox が使えなければ NG です（サーバーも動きません）。
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
        "PYTHONPATH": "/path/to/spatialvibe-mcp"
      }
    }
  }
}
```

これで Claude が最初にプリンターを聞きます。いつも同じプリンターを使うなら、`env` に既定値を足しておくこともできます（任意）:

```json
"SPATIALVIBE_PRINTER": "256x256x256"
```

（造形サイズ mm。プリセットのある機種は名前でも可。例: Bambu Lab A1 mini なら `"a1mini"`）

### 5. 最初の小さいモデル

Claude にこう頼みます:

> A1 mini を使っています。spatialvibe で 40×20×5 mm、M3 の穴が 2 つあるテスト板を作って、プレビューを見せてください。

Claude が `build_model` → `preview` を行い、造形範囲に入るかも返します。

### 6. 印刷準備へ

> 印刷に進めて。PLA で 2 枚、金具はなし。

Claude が `export_print` を呼び、条件（プリンター・材料・個数・向き・外形・未確認）を会話で示します。未確認があればそれだけ聞かれます。
その先は Claude が使える連携しだいです。スライサーやプリンターの連携があれば準備を続け、実際の設定や見積りを示します。
なければ、フォルダの場所を伝えたところで止まります（この MCP はスライスや印刷はしません）。

### 環境変数

| 環境変数 | 既定 | 意味 |
| --- | --- | --- |
| `SPATIALVIBE_HOME` | `./data/mcp_projects` | プロジェクトと版の保存先（変えると、元の場所の版は見えなくなります。doctor が知らせます） |
| `SPATIALVIBE_PRINTER` | なし | 既定のプリンター（`a1mini` / `WxDxH`） |
| `SPATIALVIBE_PUBLISH` | `icloud` | AR ファイルの置き場所（`icloud` / `dir:/path`） |
| `SPATIALVIBE_TIMEOUT` | `180` | 1 回の実行（ビルド・プレビュー・AR 出力それぞれ）の制限秒数（10〜3600） |

子プロセスにはこれらの環境変数も含めて親の環境を渡しません（固定の数個だけ）。

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
この MCP はスライスもプリンターの操作もしません。そこから先は AI が使える連携（なければ人）が担います（屋外は PETG / ASA 推奨）。

経緯: 最初は Web アプリ（[spatial-vibe-modeling-app](https://github.com/tomiyasu0428/spatial-vibe-modeling-app)）として作り、2026-11-04 に MCP サーバーへ移りました。
