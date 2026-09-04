# Screenshots

Captured from a real local run (`docker compose up`, fake providers,
`docs/ARCHITECTURE.md` §2 Path A) and referenced from the README's
[Demo](../../README.md#demo) section:

1. `01-login.png` — **Login / registration** — the auth screen.
2. `02-knowledge-bases.png` — **Knowledge bases** — list + create form.
3. `03-document-ready.png` — **Document upload** — a document that reached
   `ready` after ingestion.
4. `04-chat-citations.png` — **Chat** — a streamed answer with `[[n]]`
   citation chips and the source panel.

Not yet captured (see [How to capture](#how-to-capture) below):

5. **Member management** — the owner/editor/viewer role UI.
6. **A deliberately-failed upload** showing a failure reason.
7. **Abstention** — an off-topic question correctly refused.
8. **Evaluation** — the runs list with bootstrap 95% confidence intervals
   (needs a real `rag eval run`, not the fake-provider smoke flow).

## How to capture

```bash
make dev            # or: make e2e (leave the stack up by dropping the teardown)
```

Then open <http://127.0.0.1:8080>, walk through the flow above, and save each
shot as `docs/screenshots/<0N>-<name>.png` (PNG, browser window cropped, no
personal data in the URL bar or bookmarks). Reference them from the README's
Demo section once added, e.g.:

```markdown
![Chat with citations](docs/screenshots/04-chat-citations.png)
```

A short (15–30s) screen recording converted to GIF works well for the same
section instead of / alongside the stills.
