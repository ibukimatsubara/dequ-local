# Connect your agent to DeQu

Start the server on the same computer as your agent, following the main README. Local connections work without credentials.
The examples use `http://127.0.0.1:8790`.
When the agent runs on another machine, configure the shared token as described in the README, use your `tailscale serve` address, and add that host name to `allowed_hosts` in the server's config file and restart the server; otherwise MCP rejects the request with `421 Invalid Host header`. The REST API does not need this.

| Agent | How it asks | How it waits | Guide |
| --- | --- | --- | --- |
| Claude Code | MCP `ask` | `dequ wait <id>` in the background | [claude-code.md](claude-code.md) |
| Codex | MCP `ask` | MCP `wait` | [codex.md](codex.md) |
| Anything else | `POST /api/cards` | `GET /api/results?ids=...&wait=50` | [rest-api.md](rest-api.md) |

Give the agent the card rules too: copy [`skill/SKILL.md`](../../skill/SKILL.md) into its skills folder, or paste it into its instructions.

## What a pending card means

A pending card is never an approval.
The agent keeps working on everything that does not depend on the answer and acts on the decision only after you answer.
DeQu does not decide what an agent may do on its own; that stays with your agent's own rules and permissions.
