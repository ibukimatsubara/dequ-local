# DeQu (Decide Queue)

[日本語](README.ja.md)

DeQu lets coding agents send you questions while they keep working.
An agent puts a decision card in the queue, you answer it in your browser, and the answer goes back to the agent.

```
agent ──ask──▶ DeQu server ◀──answer── you (browser)
  ▲                │
  └──wait (answer)─┘
```

- Agents talk to the server over MCP (`/mcp`) or plain HTTP (`/api/...`, or `dequ wait` from a shell).
- Each card says what the agent is doing, where it is stuck, and the question. A multiple-choice card has 2–4 options with what each one does and the option the agent recommends; a card that asks for a written answer has no options.
- While a card is pending, the agent keeps working on anything that does not depend on the answer. A pending card never counts as approval.

This release runs on your computer. The default setup uses local storage and requires no account or token.

## Requirements

- Linux or macOS
- [uv](https://docs.astral.sh/uv/) (installs Python 3.12+ for you)
- Node.js `^22.22.2`, `^24.15.0` or `>=26.0.0` and npm, to build the web app

## Quick start

Clone the repository and install the `dequ` command:

```sh
git clone https://github.com/ibukimatsubara/dequ-local.git
cd dequ-local
uv tool install ./server
```

`uv tool install` puts `dequ` in `~/.local/bin`.
If that folder is not on your `PATH`, run `uv tool update-shell` and open a new shell.

Build the web app:

```sh
cd web
npm ci
npm run build
cd ..
```

The built files are in `web/dist`.

Create the configuration directory.

```sh
mkdir -p ~/.config/dequ
```

Write `~/.config/dequ/config.toml`, replacing `/path/to/dequ` with the folder you cloned:

```toml
web_dir = "/path/to/dequ/web/dist"
```

Start the server:

```sh
dequ serve --config ~/.config/dequ/config.toml
```

The server listens on `http://127.0.0.1:8790`.
Open that address in a browser on the same computer to see your queue.
The default local setup uses no token for the web app, MCP or CLI.
If you previously set up a token and want to use this local mode, remove `DEQU_TOKEN` from the server environment and the bearer setting from your agent, then restart both.

### Try it with curl

In another shell, put a card in the queue.

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

The reply contains the card id, for example `{"id":"jbo3Vnviexpr2rx3mQypnQ","created":true,"status":"pending"}`.
Asking again with the same `key` returns the same card instead of a duplicate.

Wait for the answer the way an agent would:

```sh
dequ wait <id>
```

Set `DEQU_URL` when the server is at another address.
It waits until the card is answered, then prints the answer as JSON.
Its exit code is `0` when the card was answered, `3` when the card is gone (expired or withdrawn), and `2` for a missing or wrong token.

Answer the card in the web app, or from a third shell:

```sh
curl -s -H 'Content-Type: application/json' \
  http://127.0.0.1:8790/api/cards/<id>/answer --data '{"option": "yes", "comment": "Looks good"}'
```

`dequ wait` then prints `{"id": "<id>", "status": "answered", "answer": {"option": "yes", "comment": "Looks good"}}`.

## Connect your agent

For Codex, run the following command and start a new Codex session:

```sh
codex mcp add dequ --url http://127.0.0.1:8790/mcp
```

Setup guides for Claude Code, Codex and any agent that can run `curl` are in [docs/agents](docs/agents/README.md).
Give the agent the card rules in [skill/SKILL.md](skill/SKILL.md) as well.

## Optional: reach your own server from your phone

Install [Tailscale](https://tailscale.com/) on both devices.
Set a shared token before exposing the queue through Tailscale or another reverse proxy.
Create it once in a private file. If you already have one, reuse it.

```sh
(umask 077; set -C; printf 'DEQU_TOKEN=%s\n' "$(dequ token)" > ~/.config/dequ/env)
```

Stop the local server and start it in the token-protected mode.

```sh
set -a && . ~/.config/dequ/env && set +a
dequ serve --config ~/.config/dequ/config.toml
```

Enter the same token in the browser on your phone when prompted.

The phone needs HTTPS: browsers allow the home-screen app and notifications only on secure pages.
`tailscale serve` gives the server an HTTPS address that only devices in your tailnet can open.

```sh
tailscale serve --bg 8790
tailscale serve status
```

`tailscale serve status` shows the address, such as `https://my-machine.my-tailnet.ts.net`.
Open it on your phone (with the Tailscale app connected) and add it to the home screen.
To stop serving, run `tailscale serve --https=443 off`.

Agents on other machines reach the MCP endpoint at `https://my-machine.my-tailnet.ts.net/mcp`.
The MCP endpoint accepts only the host names `127.0.0.1`, `[::1]`, `localhost` and those in `allowed_hosts`, and answers `421` otherwise, so add the tailnet host name to the configuration file and restart the server:

```toml
allowed_hosts = ["my-machine.my-tailnet.ts.net"]
```

Write the host name without `https://` and without the trailing dot.

## Keep it running

Run the server as a systemd user service so it starts at boot and restarts after a crash.
Save this as `~/.config/systemd/user/dequ.service`:

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

This unit is for the same-PC setup on Linux with systemd.
For a queue shared with other devices, add `EnvironmentFile=%h/.config/dequ/env` to `[Service]` so systemd loads the shared token.
Stop the `dequ serve` you started in the quick start (`Ctrl-C`) first, because the service uses the same port.
Then enable it, and let your user services run while you are logged out:

```sh
systemctl --user daemon-reload
systemctl --user enable --now dequ.service
loginctl enable-linger
systemctl --user status dequ.service
```

Run the server as a **single process**.
An answer wakes up the waiting agents only inside the same process, so do not start several `dequ serve` processes on the same `data_dir` or put them behind a load balancer.

## Configuration file

`dequ serve --config <file>` reads a TOML file.
Every setting is optional.

| Setting | Default | Meaning |
| --- | --- | --- |
| `data_dir` | `~/.local/share/dequ` | Folder for the SQLite database (`dequ.sqlite3`). Created if missing. |
| `web_dir` | none | Folder of the built web app (`web/dist`). Without it, the server serves only `/api` and `/mcp`. |
| `allowed_hosts` | `[]` | Extra host names the MCP endpoint accepts, besides `127.0.0.1`, `[::1]`, and `localhost`. Add `name:*` to allow any port. |
| `[retention] answered` | `PT1H` (1 hour) | How long an answered card is kept after it was answered. |
| `[retention] pending` | `P3D` (3 days) | How long an unanswered card is kept after it was created. |

Durations are ISO 8601 (`PT30M`, `PT1H`, `P3D`) or a number of seconds.
The token is read only from the `DEQU_TOKEN` environment variable; a `token` line in the file is ignored.

A full example:

```toml
data_dir = "~/.local/share/dequ"
web_dir = "/path/to/dequ/web/dist"
allowed_hosts = ["my-machine.my-tailnet.ts.net"]

[retention]
answered = "PT1H"
pending = "P3D"
```

## Security model

DeQu is built for one person and their own agents on a private network.

- **Same computer.** With no `DEQU_TOKEN` set, local processes can read and answer cards through the loopback address.
- **Shared queue.** When you set a token, every `/api` and `/mcp` request needs `Authorization: Bearer <token>` except for `/api/health`. The web app and all agents use the same token. Anyone with the token can read and answer every card, so keep it out of repositories and cards. If it leaks, write a new token into `~/.config/dequ/env`, restart the server (`systemctl --user restart dequ.service`), and update the token in the web app and every agent; the old token stops working only after the restart.
- **No CORS.** The server sends no CORS headers, so web pages from other sites cannot call the API from a browser.
- **Strict Content-Security-Policy.** Pages load scripts, styles and connections only from the server itself (inline styles and `data:` images are allowed), cannot be framed by other sites, and send no referrer.
- **Short retention.** Answered cards are deleted after 1 hour and unanswered cards after 3 days by default, and expired cards are removed from disk on the next store operation, so card contents do not pile up.
- **Network.** The server listens on `127.0.0.1` by default. Reach it from other devices through `tailscale serve` rather than by listening on a public address.

Agents are told never to put secrets in a card, but DeQu does not check card contents for secrets.

## Development

```sh
(cd server && uv run --extra firestore pytest)
(cd web && npm test)
```

## License

DeQu Source-Available License. See [LICENSE](LICENSE).
