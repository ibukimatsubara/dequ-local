# Other agents (REST API)

Any agent that can run `curl` can use DeQu.
The examples connect to the local server. For a protected server, use its URL and add `-H "Authorization: Bearer $DEQU_TOKEN"` to each request.

## Ask

```sh
curl -s -X POST http://127.0.0.1:8790/api/cards \
  -H 'Content-Type: application/json' \
  -d '{
    "key": "demo/button-color",
    "agent": {"kind": "other", "name": "my-agent", "where": "laptop"},
    "task": "Build the demo page.",
    "progress": "The page and the button are done.",
    "blocked": "The button color is not decided.",
    "question": "Which button color?",
    "options": [
      {"id": "red", "label": "Red", "effect": "Stands out. Clashes with the logo."},
      {"id": "blue", "label": "Blue", "effect": "Matches the logo. Stands out less."}
    ],
    "recommended": "blue",
    "reason": "It matches the logo."
  }'
```

The response is `{"id": "...", "created": true, "status": "pending"}`.
Sending the same `key` again returns the same card (`"created": false`) while it is pending, and its answer after it was answered, as long as the server still keeps the card (by default 3 days unanswered, 1 hour after the answer). After that, the same `key` creates a new card.
A 422 response lists what to fix in `errors`.

## Wait

```sh
curl -s "http://127.0.0.1:8790/api/results?ids=<id>&wait=50"
```

The call returns as soon as a card is answered or gone, or after 50 seconds.

For hosted deployments, use `dequ wait <id>` to wait without holding an HTTP request open.
Run `uv tool install './server[firestore]'` from the repository root to enable Firestore notifications.
The CLI adds `notify=firestore` to its results request.
A compatible server returns a pending card's `notification` with its Firestore `project`, `database`, `bell` and `expires_at`.
The CLI watches the single document `bells/<bell>` without Google credentials and fetches the result again with the DeQu token when the document appears or the card expires.
Set `DEQU_URL` to the hosted server’s base URL.
If the notification dependency is missing or the connection fails, the CLI checks for the answer over HTTP every five seconds.
If you also develop against the Firebase Emulator, run `env -u FIRESTORE_EMULATOR_HOST dequ wait <id>` to receive notifications from the hosted database.
The self-hosted SQLite server keeps the ordinary long-poll behavior.
Repeat it while `status` is `pending`.

## Record and withdraw

- `POST /api/records` with `{agent, question, chose, why}` adds a decision the agent made itself to the history.
- `DELETE /api/cards/<id>` withdraws a pending card that is no longer needed. If the card was already answered, the server returns `409`; fetch its answer from `GET /api/results`.
