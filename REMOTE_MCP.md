# 外出先の Claude / ChatGPT から Mac の Pittari（spatialvibe）MCP を使う

スマホの Claude や ChatGPT に「この形を作って」と頼み、返ってきたリンクを開いて実寸 AR を確認する構成です。
制作（build123d の実行と USDZ の生成）は自宅の Mac で行い、Cloudflare の Worker が入口になります。

```
Claude / ChatGPT ──OAuth 2.1──▶ ゲートウェイ Worker ──専用クレデンシャル──▶ Cloudflare Tunnel ──▶ Mac の MCP サーバー
   (スマホ)                        cloudflare/mcp-gateway                    (cloudflared)        127.0.0.1:8765 /mcp
                                                                                                    │ build_model / preview
                                                                                                    ▼ publish_ar（Keychain の鍵）
iPhone の Safari ◀──期限付き AR リンク──────────────────────────────────── AR Worker（cloudflare/ar-worker, R2）
```

- ① 依頼: Claude / ChatGPT のコネクタ（カスタム MCP）としてゲートウェイを登録する。認証は OAuth 2.1（PKCE）。
- ② 生成: Mac 上の `spatialvibe_mcp` が `transport: http` で動き、Tunnel 経由の `/mcp` だけを受ける。生成コードの `sandbox-exec` 隔離は従来どおり。
- ③④ 公開と閲覧: 既存の AR Worker。鍵は Mac の Keychain から読むので、クラウドセッションのプロキシ注入は使わない。

ユーザーや OAuth トークンは Mac に届きません。Mac が受け付けるのはゲートウェイだけが持つ 43 文字の専用クレデンシャル 1 つです。

## 必要なもの

| 場所 | もの |
| --- | --- |
| Cloudflare | Worker `spatialvibe-mcp`（ゲートウェイ）、KV 名前空間 `OAUTH_KV`、Tunnel 1 本とそのホスト名（自分のドメインの CNAME） |
| Mac | `cloudflared`、Keychain 項目 2 つ（AR 公開用 `spatialvibe-ar-upload` と上流用 `spatialvibe-mcp-upstream`）、launchd の常駐 2 つ |
| 秘密 | `LOGIN_PASSWORD`（同意画面で入力する自分のパスフレーズ）、`UPSTREAM_TOKEN`（Worker と Mac の Keychain に同じ値） |

秘密の値はチャット・リポジトリ・シェル履歴に残さないでください。`wrangler secret put` は標準入力から読みます。

## 手順

### 1. Mac 側の鍵

```bash
# 上流クレデンシャル（32 バイト乱数 → 43 文字）。画面に出さずクリップボードへ。
.venv/bin/python -c 'import secrets;print(secrets.token_urlsafe(32), end="")' | pbcopy
# Keychain に登録（-w を値なしで付けると対話入力になるので、プロンプトに貼り付ける。引数や履歴に残らない）
security add-generic-password -s spatialvibe-mcp-upstream -a mcp-upstream -T "$(pwd)/.venv/bin/python" -w
```

- 同じ値を手順 3 の `wrangler secret put UPSTREAM_TOKEN` にも貼り付け、終わったら `pbcopy < /dev/null` でクリップボードを消します。
- Keychain 項目のアクセス制御は MCP を動かす Python 1 つだけに限定します（`-T`）。AR 公開用の既存項目 `spatialvibe-ar-upload`（アカウント `upload`）はそのままです。

### 2. Tunnel

```bash
brew install cloudflared
cloudflared tunnel login
cloudflared tunnel create spatialvibe-mcp
cloudflared tunnel route dns spatialvibe-mcp spatialvibe-mcp.example.com   # 自分のドメイン
cp mac/cloudflared-config.example.yml ~/.cloudflared/config.yml            # UUID・ユーザー名・ホスト名を置換
```

`config.yml` は `/mcp` だけを `http://127.0.0.1:8765` に通し、それ以外は 404 です。

### 3. ゲートウェイ Worker

```bash
cd cloudflare/mcp-gateway
pnpm install && node --test gateway.test.mjs
cp wrangler.example.jsonc wrangler.jsonc        # account_id, workers.dev サブドメイン, UPSTREAM_ORIGIN=https://<Tunnel ホスト名>
wrangler kv namespace create OAUTH_KV           # 出力の id を wrangler.jsonc に
wrangler secret put LOGIN_PASSWORD              # 12 文字以上のパスフレーズ
wrangler secret put UPSTREAM_TOKEN              # 手順 1 の値（クリップボードから）
wrangler deploy
```

確認: `https://spatialvibe-mcp.<サブドメイン>.workers.dev/.well-known/oauth-authorization-server` が JSON を返し、`/mcp` に素の POST をすると 401 と `WWW-Authenticate` が返ること。

### 4. Mac の MCP サーバーを http モードで常駐

`.spatialvibe-ar.local.json`（0600、git 管理外）に 4 項目を足します。

```json
{"origin": "https://spatialvibe-ar.<サブドメイン>.workers.dev", "keychain_service": "spatialvibe-ar-upload",
 "home": "/Users/you/spatialvibe-data", "printer": "a1mini",
 "transport": "http", "public_host": "spatialvibe-mcp.example.com",
 "upstream_keychain_service": "spatialvibe-mcp-upstream", "http_port": 8765}
```

```bash
# まず手動で起動して 127.0.0.1:8765 を確認（Ctrl-C で停止）
.venv/bin/python -I tools/ar_mcp_launch.py
curl -sS -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8765/mcp -H 'Content-Type: application/json' -d '{}'   # 401

# 常駐（ログイン中のユーザーセッションで動かす。Keychain を読むため gui ドメイン）
cp mac/com.spatialvibe.mcp.plist mac/com.spatialvibe.cloudflared.plist ~/Library/LaunchAgents/   # REPLACE を置換してから
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.spatialvibe.mcp.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.spatialvibe.cloudflared.plist
```

外出中も動かすための Mac 側設定:

- システム設定 → 省エネルギー（またはバッテリー）で「ディスプレイがオフのときに自動でスリープさせない」をオン。ノートなら電源接続時のみで十分です。`sudo pmset -c sleep 0 disksleep 0` でも同じです。
- 停電・再起動後も自動で戻るよう、自動ログインを有効にするか、再起動後に一度ログインします（LaunchAgent はログイン後に起動し、FileVault 有効時は必ずログインが要ります）。
- Wi-Fi より有線、ルーターの省電力設定もオフ。Mac が落ちれば ① ② は止まります（AR リンクの閲覧 ③④ は Cloudflare 側だけで動き続けます）。

### 5. Claude と ChatGPT に登録

- claude.ai: 設定 → コネクタ → カスタムコネクタを追加 → URL `https://spatialvibe-mcp.<サブドメイン>.workers.dev/mcp`。OAuth は自動検出され、同意画面でパスフレーズを入力します。Claude アプリ（スマホ）でも同じコネクタが使えます。
- ChatGPT: 設定 → コネクタ（開発者モード）→ 新規 → 同じ URL。ChatGPT は Client ID Metadata Document で登録するため、Worker 側の `global_fetch_strictly_public` フラグが必要です（`wrangler.example.jsonc` に設定済み）。
- 最初の会話で `build_model` → `preview` → `publish_ar` が通り、返ってきたリンクを iPhone の Safari で開いて AR になれば完成です。

## 動作の要点と制限

- Mac のサーバーは `Host` ヘッダーが `public_host` でないリクエストと、上流クレデンシャル以外の Bearer を拒否します（DNS リバインディング対策と `TransportSecuritySettings`）。アクセスログは出しません。
- ゲートウェイは MCP に必要なヘッダーだけを中継し、Cookie・OAuth トークン・`CF-*` は通しません。Mac が落ちていれば 503、クレデンシャル不一致なら 502 で、クライアントに再認証ループを起こさせません。
- パスフレーズ 1 つで全部が守られます。漏れた疑いがあれば `wrangler secret put LOGIN_PASSWORD` で差し替え、KV 名前空間を作り直して既存の許可を無効化してください。
- `build_model` は数分かかることがあり、Worker はストリームをそのまま通しますが、Claude / ChatGPT 側のツール実行時間の上限は別にあります。
- このブランチはクラウドセッションから Cloudflare にデプロイできないため、デプロイと Mac 側の設定はユーザーが行います。デプロイ前の検証は `node --test gateway.test.mjs` と `tests/test_remote.py`、デプロイ後は上の確認コマンドで行います。
