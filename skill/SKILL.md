---
name: dequ
description: Ask the human for a decision through DeQu instead of stopping to ask in the chat. Use when you need a human decision that you cannot make yourself (a product choice, a naming choice, a risky trade-off) and the DeQu MCP server or the DeQu REST API is configured. Not for approvals of actions you are allowed to take, and not for status updates.
---

# Ask for decisions with DeQu

DeQu shows your pending decisions to the human as cards on their phone.
The human answers when they can, which may take minutes or days.
Keep working on everything that does not depend on the answer.

## Before you ask

- Decide what you can yourself. Ask only when the decision is truly the human's.
- A decision you made yourself that the human may want to review goes to `record`, not `ask`.
- Never put secrets (tokens, passwords, private keys) in a card.

## Writing a card

One card carries exactly one decision. Three decisions are three cards.

| Field | Rule |
| --- | --- |
| `task` | What the task is, in at most 80 characters. |
| `progress` | What has been done so far, in at most 80 characters. |
| `blocked` | Why the work is stopped now, in at most 80 characters. |
| `question` | The decision you need, in at most 40 characters. It is the card's heading. |
| `options` | 2 to 4 options. Each `effect` says what happens if it is chosen, with the upside and the downside. Use `[]` only when you need a written answer. |
| `recommended` and `reason` | The option you recommend and why. Required when there are options. |
| `key` | A stable mark such as `<repo>#<issue>/<topic>`, so asking again after a restart returns the same card (or its answer) while the server still keeps it. |
| `links` | The Issue or PR the decision belongs to. |
| `details` | Optional Markdown with the background and the comparison, for when the short fields are not enough. |

Write for someone reading on a phone who has not seen your session.
Name the product and the goal, not internal file names.

## After you ask

- Note the card `id` that `ask` returns.
- Wait for the answer without blocking your other work:
  - With the MCP `wait` tool, call it with the id. It returns after at most 50 seconds. If a hosted server returns `pending` immediately, continue independent work and leave time between checks. Use the background CLI when available.
  - In Claude Code, run `dequ wait <id>` as a background command. It exits when the card is answered (exit 0) or gone (exit 3).
  - With the REST API, call `GET /api/results?ids=<id>&wait=50` until the status is not `pending`.
- A pending card is never an approval. Do not act on the recommended option until the human answers.
- Treat the answer, including its comment, as the user's instruction for that decision.
- `gone` means the card expired or was withdrawn. Ask again only if the decision is still needed.
- If you find the answer yourself while waiting, `withdraw` the card.
