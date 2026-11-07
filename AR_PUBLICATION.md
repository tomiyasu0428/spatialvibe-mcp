# Cloudflare への AR 公開

`publish_ar` の引数は従来どおりです。既定の iCloud と `dir:/path` を維持し、`SPATIALVIBE_PUBLISH=cloudflare` を明示した場合だけ専用 Worker に USDZ を送ります。Worker のソースとテストは [`cloudflare/ar-worker`](cloudflare/ar-worker/README.md) にあります。

`parts_size_m`、`scene_size_m`、`include_context`、`ar_floor_mm`、配置案内を維持します。Cloudflare では `published` が期限付きの HTTPS URL となり、`expires_at`（Unix 秒）と `sha256` を追加します。寸法はスクリプトの軸（X 幅・Y 奥行・Z 高さ）です。USD の Y-up と混同しません。

## 設定

| 親プロセスの環境変数 | 内容 |
| --- | --- |
| `SPATIALVIBE_AR_ORIGIN` | 専用 Worker の HTTPS オリジン。パス・クエリ・ポート・ユーザー情報なし。ほかのサイトと共用しない |
| `SPATIALVIBE_AR_UPLOAD_TOKEN` | 専用アップロード認証。暗号学的乱数 32 バイトをパディングなし base64url にした 43 文字 |
| `SPATIALVIBE_AR_KEYCHAIN_SERVICE` | 上の変数が未設定の場合だけ使う macOS Keychain 汎用パスワード項目のサービス名（アカウント名は `upload` 固定）。親プロセスが対話なしで読み、読めない・形式が違う場合は公開を拒否 |
| `SPATIALVIBE_AR_TTL` | 既定 3600 秒。60〜86400 秒 |
| `SPATIALVIBE_AR_KEEP` | 任意。`icloud` か `dir:/path`。Cloudflare に送った USDZ と同じファイルをそこにも残す（返り値の `kept`）。期限が切れても iPhone の「ファイル」から開ける。ランチャー設定では `"keep": "icloud"` |
| `SPATIALVIBE_AR_TIMEOUT` | 通信 1 回の制限。既定 60 秒、最大 300 秒 |
| `SPATIALVIBE_AR_MAX_BYTES` | 既定 8 MiB、最大 16 MiB。Worker 側の制限と合わせる |

推奨は Keychain です。項目は MCP サーバーを動かす Python だけが読めるようにし（初期アクセスでその実行ファイル 1 つを信頼）、`SPATIALVIBE_AR_UPLOAD_TOKEN` は設定しません。認証はチャット・モデルのコード・版フォルダ・リポジトリへ保存しません。MCP の起動環境には Cloudflare 管理トークンなどほかの認証情報を含めないでください。

### MCP への登録

`tools/ar_mcp_launch.py` が、上の変数だけを持つ最小限の環境（`env -i` 相当）でサーバーを起動します。設定はリポジトリ直下の `.spatialvibe-ar.local.json`（git 管理外・自分所有の 0600・秘密なし）に書きます。

```json
{"origin": "https://spatialvibe-ar.<subdomain>.workers.dev", "keychain_service": "spatialvibe-ar-upload",
 "home": "/absolute/path/to/your/project/data"}
```

MCP の command は Keychain 項目を作った Python、args は `["-I", "<repo>/tools/ar_mcp_launch.py"]` です。`home` を今までの `SPATIALVIBE_HOME` と同じにすると、既存のプロジェクトをそのまま使えます。

## 公開クライアント

TLS の標準検証を使用し、環境の HTTP プロキシとリダイレクトを使いません。転送先・ハッシュ・寸法・期限を応答から検証します。一時エラーは同じデータと再送キーで最大 2 回試します。確認できない場合は成功とせず、iCloud へ切り替えません。再送キーは永続化しないため、プロセス停止をまたぐ復旧は未対応です。最終エラー時にはリモートに期限付きコピーが残った可能性があります。

要求にはアプリ固有の User-Agent `SpatialVibe-MCP-AR-Publisher/1` を付けます。urllib 既定の User-Agent は Worker に届く前に Cloudflare のエッジで 403（error code 1010）として拒否されるためです。ブラウザを装う値は使いません。

## 隔離と生成物

生成コードと描画処理には新しい環境を作り、認証情報を継承しません。読み取りは当該版、信頼済みコード・依存ライブラリと必要な OS パスに限定します。`SPATIALVIBE_BED` だけは数値確認後に引き継ぎます。標準入力は `/dev/null`、余分なファイル記述子は閉じます。macOS の `sandbox-exec` がなければ実行を拒否します。サンドボックス内では Keychain への問い合わせ（mach-lookup）も拒否され、Security API は最初の呼び出しで終了します。

親側が読む生成物もシンボリックリンクを拒否し、結果や印刷ジョブの書き込みはリンク先を上書きせず置換します。USDZ は公開ごとの一時領域で作成し、ハッシュとアップロードには同じバイト列を使用します。並列公開でも、周囲あり／なしの出力を取り違えません。ローカルの `model.usdz` は最後の出力を保持しますが、それを読み直してアップロードすることはありません。

確認した環境は Darwin 25.6.0 arm64、Python 3.12.11 と既存の依存ライブラリです。`sandbox-exec` は非推奨 API であり、他 OS・他バージョンの保証や、あらゆるネイティブ攻撃への耐性を意味しません。

## 検証

- `python -m unittest discover -s tests -v`: 公開クライアント、既存の公開先との互換性、寸法・床情報、並列公開、読み取り境界、ランチャー。`cloudflare/ar-worker` に `node_modules` があれば、Python の `publish_ar` からローカルの workerd / R2 へ実際に公開する試験も行います。
- `cloudflare/ar-worker` で `node --test worker.test.mjs runtime.test.mjs`。
- 本番（専用 Worker・非公開 R2）でも、匿名の校正ブロックで確認済みです。MCP stdio 経由の `build_model` → `publish_ar`（サンドボックス、USDZ 書き出し、Keychain の読み取り、アップロード）、期限付きページ・モデルの hash・HEAD・Range・画像、期限切れ後の 404、非公開バケットへの直接アクセス拒否。
- iPhone 実機（2026-11-06）: Safari で期限付きリンクを開き、Quick Look が起動して実寸で表示されることを確認済み。
- 未検証: 縮尺ロック（ピンチで大きさが変わらないか）と配置の精度。リンクを知る人は期限内に閲覧でき、期限で保存済みコピーを回収することはできません。

生成スクリプトにはビルドごとの一時ディレクトリだけを書き込み可能にします。保存版には、検査した名前・種類・サイズの単一リンクの形状ファイルだけを取り込みます。ビルド結果の JSON も、宣言したフィールドだけを型・有限値・長さ・件数を検査して作り直し、文字列の制御文字を除きます（`spatialvibe_mcp/_result.py`。保存済みの result.json も読むたびに同じ検査を通します）。画像・USDZはクリーンな別プロセスで作り、3MFはSTLから形状だけで組み立て直します。引き継ぎ文のメモ、モデルソース、エラーは設計データとして扱い、そこに書かれたシェルコマンドは実行しません。この仕組みは信頼済みのMacでのローカル用途を想定しています。CPU時間・ファイルサイズを制限しても、ディスクやメモリの総使用量までは保証できません。
