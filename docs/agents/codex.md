# Codex

## Add the MCP server

Add the local server to `~/.codex/config.toml`.

```toml
[mcp_servers.dequ]
url = "http://127.0.0.1:8790/mcp"
```

Or with the CLI:

```sh
codex mcp add dequ --url http://127.0.0.1:8790/mcp
```

For a protected server, use its MCP URL, add `--bearer-token-env-var DEQU_TOKEN` and start Codex from a shell where that token is exported.

## Wait for the answer

Codex waits with the MCP `wait` tool.
Each call returns after at most 50 seconds. A hosted server can return `pending` immediately. Leave time between checks, or run `dequ wait <id>` in the background to receive the answer.
For the hosted CLI, set `DEQU_URL` to the same server URL without the trailing `/mcp`, and export the same `DEQU_TOKEN`.

## Add the card rules

```sh
mkdir -p ~/.codex/skills/dequ
cp skill/SKILL.md ~/.codex/skills/dequ/SKILL.md
```

## Try it

```sh
codex exec "Use the dequ ask tool to ask me which button color to use for the demo page (red or blue, recommend blue), then call the dequ wait tool until the card is answered and report the result."
```

Answer the card in your browser. Codex prints the option and your comment.
