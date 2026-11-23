# DeQu（Decide Queue）

[English](README.md)

DeQu は、コーディングエージェントからの判断依頼をブラウザで確認し、回答を返せるツールです。
エージェントは質問をカードにして送り、回答を待つ間も進められる作業を続けます。

```
エージェント ──ask──▶ DeQu サーバー ◀──answer── 人（ブラウザ）
   ▲                    │
   └──wait（答え）──────┘
```

- エージェントは MCP（`/mcp`）か HTTP（`/api/...`、シェルからは `dequ wait`）でサーバーとやり取りします。
- カードには、エージェントが何をしているか、どこで止まっているか、質問が載ります。選択式のカードには2〜4個の選択肢とそれぞれを選んだときに起きること、エージェントのおすすめが付き、文章で答えてほしいカードには選択肢がありません。
- 答えを待つ間、エージェントは答えに関係しない作業を続けます。答えのないカードを承認として扱うことはありません。

このリリースは手元のPCで動きます。
既定の設定では、カードはPC内に保存され、アカウントやトークンは不要です。

## 必要なもの

- Linux か macOS
- [uv](https://docs.astral.sh/uv/)（Python 3.12 以上も uv が入れます）
- 画面のビルドに Node.js `^22.22.2`・`^24.15.0`・`>=26.0.0` のどれかと npm

## はじめ方

リポジトリを取得し、`dequ` コマンドを入れます。

```sh
git clone https://github.com/ibukimatsubara/dequ-local.git
cd dequ-local
uv tool install ./server
```

`uv tool install` は `dequ` を `~/.local/bin` に置きます。
このフォルダが `PATH` にない場合は、`uv tool update-shell` を実行してシェルを開き直してください。

画面をビルドします。

```sh
cd web
npm ci
npm run build
cd ..
```

ビルドしたファイルは `web/dist` にできます。

設定用のディレクトリを作ります。

```sh
mkdir -p ~/.config/dequ
```

`~/.config/dequ/config.toml` を書きます。`/path/to/dequ` は取得したフォルダに置き換えてください。

```toml
web_dir = "/path/to/dequ/web/dist"
```

サーバーを起動します。

```sh
dequ serve --config ~/.config/dequ/config.toml
```

サーバーは `http://127.0.0.1:8790` で待ち受けます。
同じPCのブラウザでこのアドレスを開くと、判断カードが表示されます。
このPCの画面とMCP、CLIはトークンなしで使えます。
以前トークンを設定したPCでは、サーバーの環境から `DEQU_TOKEN` を外し、エージェントの接続設定からBearerトークンの指定を外して、両方を再起動してください。

### curl で試す

別のシェルでカードをキューに入れます。

```sh
curl -s http://127.0.0.1:8790/api/health
curl -s -H 'Content-Type: application/json' \
  http://127.0.0.1:8790/api/cards --data '{
    "key": "readme/try-it",
    "agent": {"kind": "other", "name": "curl", "where": "my laptop"},
    "task": "Try DeQu",
    "progress": "The server is running",
    "blocked": "Needs a human answer",
    "question": "Does DeQu work?",
    "options": [
      {"id": "yes", "label": "Yes", "effect": "Keep going"},
      {"id": "no", "label": "No", "effect": "Check the logs"}
    ],
    "recommended": "yes",
    "reason": "The health check passed"
  }'
```

返事にカードの id が入ります。例: `{"id":"jbo3Vnviexpr2rx3mQypnQ","created":true,"status":"pending"}`
同じ `key` でもう一度出すと、重複を作らずに同じカードが返ります。

エージェントと同じように答えを待ちます。

```sh
dequ wait <id>
```

サーバーのアドレスを変えた場合は `DEQU_URL` に設定します。
カードに答えが付くまで待ち、答えを JSON で表示します。
終了コードは、答えが付いたら `0`、カードがなくなったら（期限切れか引っ込め）`3`、トークンがないか違うときは `2` です。

画面で答えるか、3つ目のシェルから答えます。

```sh
curl -s -H 'Content-Type: application/json' \
  http://127.0.0.1:8790/api/cards/<id>/answer --data '{"option": "yes", "comment": "Looks good"}'
```

すると `dequ wait` が `{"id": "<id>", "status": "answered", "answer": {"option": "yes", "comment": "Looks good"}}` を表示します。

## エージェントをつなぐ

Codexの場合は次のコマンドで登録し、新しいCodexセッションを開きます。

```sh
codex mcp add dequ --url http://127.0.0.1:8790/mcp
```

Claude Code・Codex・`curl` を使えるエージェントのつなぎ方は [docs/agents](docs/agents/README.md) にあります（英語）。
カードの書き方の決まり [skill/SKILL.md](skill/SKILL.md) も、エージェントに渡してください。

## 任意の設定でスマホから自分のサーバーにつなぐ

両方の端末に [Tailscale](https://tailscale.com/) を入れます。
Tailscaleなどのリバースプロキシでほかの端末とキューを共有する前に、サーバーにトークンを設定します。
次のコマンドで、本人だけが読めるファイルに初回のトークンを保存します。
すでにトークンを作った場合は、そのファイルを使います。

```sh
(umask 077; set -C; printf 'DEQU_TOKEN=%s\n' "$(dequ token)" > ~/.config/dequ/env)
```

ローカルで起動したサーバーを止め、トークンを読み込んで起動し直します。

```sh
set -a && . ~/.config/dequ/env && set +a
dequ serve --config ~/.config/dequ/config.toml
```

スマホで初めて画面を開いたときに、同じトークンを入力します。

スマホからは HTTPS でつなぎます。ホーム画面のアプリと通知は、ブラウザが安全なページでしか許さないためです。
`tailscale serve` を使うと、tailnet の端末だけが開ける HTTPS の住所がサーバーに付きます。

```sh
tailscale serve --bg 8790
tailscale serve status
```

`tailscale serve status` に `https://my-machine.my-tailnet.ts.net` のような住所が出ます。
スマホで Tailscale アプリをつないだ状態でその住所を開き、ホーム画面に追加します。
止めるときは `tailscale serve --https=443 off` を実行します。

ほかのマシンのエージェントは `https://my-machine.my-tailnet.ts.net/mcp` の MCP につなぎます。
MCP は、ホスト名が `127.0.0.1`・`[::1]`・`localhost`・`allowed_hosts` のどれかでないと `421` を返します。
そのため、設定ファイルに tailnet のホスト名を足してサーバーを起動し直します。

```toml
allowed_hosts = ["my-machine.my-tailnet.ts.net"]
```

ホスト名には `https://` も末尾の点も付けません。

## 動かし続ける

systemd のユーザーサービスにすると、起動時に立ち上がり、落ちても再起動します。
次の内容を `~/.config/systemd/user/dequ.service` に保存します。

```ini
[Unit]
Description=DeQu server
After=network-online.target

[Service]
ExecStart=%h/.local/bin/dequ serve --config %h/.config/dequ/config.toml
Restart=on-failure

[Install]
WantedBy=default.target
```

この設定は、同じLinux PCだけで使う場合のものです。
ほかの端末と共有する場合は、`[Service]` に `EnvironmentFile=%h/.config/dequ/env` を追加して、共有用のトークンを読み込みます。
サービスは同じポートを使うので、先にクイックスタートで起動した `dequ serve` を `Ctrl-C` で止めます。
そのあと有効にし、ログアウト中もユーザーサービスが動くようにします。

```sh
systemctl --user daemon-reload
systemctl --user enable --now dequ.service
loginctl enable-linger
systemctl --user status dequ.service
```

サーバーは**1つのプロセス**で動かしてください。
答えが付いたことを待っているエージェントに知らせる仕組みは同じプロセスの中でしか働きません。
同じ `data_dir` で `dequ serve` を複数起動したり、ロードバランサーの後ろに並べたりしないでください。

## 設定ファイル

`dequ serve --config <file>` は TOML のファイルを読みます。
どの設定も省略できます。

| 設定 | 既定値 | 意味 |
| --- | --- | --- |
| `data_dir` | `~/.local/share/dequ` | SQLite のデータベース（`dequ.sqlite3`）を置くフォルダ。なければ作ります。 |
| `web_dir` | なし | ビルドした画面のフォルダ（`web/dist`）。省くと `/api` と `/mcp` だけを出します。 |
| `allowed_hosts` | `[]` | MCP が `127.0.0.1`・`[::1]`・`localhost` のほかに受け付けるホスト名。`name:*` と書くと任意のポートを許します。 |
| `[retention] answered` | `PT1H`（1時間） | 答えたカードを、答えてから残しておく時間。 |
| `[retention] pending` | `P3D`（3日） | 答えのないカードを、作ってから残しておく時間。 |

時間は ISO 8601（`PT30M`、`PT1H`、`P3D`）か秒数で書きます。
トークンは環境変数 `DEQU_TOKEN` からだけ読みます。ファイルに `token` を書いても使いません。

全部を書いた例です。

```toml
data_dir = "~/.local/share/dequ"
web_dir = "/path/to/dequ/web/dist"
allowed_hosts = ["my-machine.my-tailnet.ts.net"]

[retention]
answered = "PT1H"
pending = "P3D"
```

## 安全の考え方

DeQu は、1人の人と自分のエージェントが、閉じたネットワークで使うことを前提にしています。

- **同じPCで使う場合。** `DEQU_TOKEN` を設定しなければ、このPC上のプロセスはループバックアドレスでカードを読んだり回答したりできます。
- **ほかの端末と共有する場合。** トークンを設定すると、`/api` と `/mcp` へのリクエストには `Authorization: Bearer <token>` が必要です。例外は `/api/health` だけです。画面とすべてのエージェントが同じトークンを使います。トークンを持つ人は全カードを読んで答えられるので、リポジトリやカードに書かないでください。漏れたら、新しいトークンを `~/.config/dequ/env` に書き、サーバーを再起動し（`systemctl --user restart dequ.service`）、画面とすべてのエージェントのトークンを差し替えます。古いトークンは再起動するまで使えます。
- **CORS なし。** サーバーは CORS のヘッダーを返しません。ほかのサイトのページからブラウザ経由で API を呼べません。
- **厳しい Content-Security-Policy。** ページはスクリプト・スタイル・通信先をサーバー自身からしか読み込みません（インラインのスタイルと `data:` の画像は許可）。ほかのサイトに埋め込まれず、リファラーも送りません。
- **短い保存期間。** 既定では、答えたカードは1時間後、答えのないカードは3日後に消えます。期限を過ぎたカードは次にストアを操作したときにディスクから消えるので、カードの中身がたまりません。
- **ネットワーク。** 既定では `127.0.0.1` だけで待ち受けます。ほかの端末からは、公開のアドレスで待ち受けるのではなく `tailscale serve` を通してつなぎます。

エージェントには、カードに秘密を書かないよう伝えています。ただし、DeQu がカードの中身に秘密が含まれていないか調べることはしません。

## 開発

```sh
(cd server && uv run --extra firestore pytest)
(cd web && npm test)
```

## ライセンス

DeQu Source-Available License です。[LICENSE](LICENSE) を見てください。
