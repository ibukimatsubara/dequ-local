# Claude Code

## Add the MCP server

Connect to the server on this computer.

```sh
claude mcp add --scope user --transport http dequ http://127.0.0.1:8790/mcp
```

For a protected server, use its URL and let Claude Code read the token from the environment.

```sh
claude mcp add-json --scope user dequ \
  '{"type":"http","url":"https://my-machine.my-tailnet.ts.net/mcp","headers":{"Authorization":"Bearer ${DEQU_TOKEN}"}}'
```

Claude Code expands `${DEQU_TOKEN}` when it connects, so start it from a shell where `DEQU_TOKEN` is exported.
Check the connection with `claude mcp list`; `dequ` should show as connected.

## Wait in the background

Claude Code does not keep an MCP call open while it works on something else, so it waits with the `dequ` command instead:

```sh
export DEQU_URL=http://127.0.0.1:8790   # the default; set it when the server is elsewhere
dequ wait <card id>
```

Run it as a background command.
It prints one JSON line and exits when the card is answered (exit 0) or gone (exit 3), and Claude Code is notified then.
`dequ` comes with the server package (`uv tool install ./server`), so install it on the machine where Claude Code runs.
For instant notifications from a hosted server, install with `uv tool install './server[firestore]'`.

## Add the card rules

```sh
mkdir -p ~/.claude/skills/dequ
cp skill/SKILL.md ~/.claude/skills/dequ/SKILL.md
```

## Try it

Ask Claude Code something like:

> Use the dequ ask tool to ask me which button color to use for the demo page (red or blue, recommend blue), then wait for my answer with `dequ wait` in the background.

Answer the card in your browser. Claude Code reports the option and your comment.
