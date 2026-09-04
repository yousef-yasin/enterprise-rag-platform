# Screenshots

Not yet captured. This is the planned shot list for the README's
[Demo](../../README.md#demo) section and any external portfolio write-up.

1. **Login / registration** — the auth screen.
2. **Knowledge bases** — list + member management (owner/editor/viewer roles).
3. **Document upload** — a document moving through `pending` → `processing` →
   `ready`, including a deliberately-failed upload showing a failure reason.
4. **Chat** — a streamed answer with `[[n]]` citation chips, the source panel,
   and the feedback thumbs.
5. **Abstention** — an off-topic question correctly refused.
6. **Evaluation** — the runs list with bootstrap 95% confidence intervals.

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
