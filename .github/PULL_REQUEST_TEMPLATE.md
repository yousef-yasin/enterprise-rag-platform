## What & why

<!-- One paragraph: what changed and why. Link an issue/ADR if relevant. -->

## Checklist

- [ ] `make check` passes (ruff, ruff format, mypy strict, unit tests)
- [ ] `make test-integration` passes (if this touches ingestion/retrieval/DB/API)
- [ ] `make frontend-check` passes (if this touches `frontend/`)
- [ ] New behaviour has tests; new config has a default + an entry in `.env.example`
- [ ] `CHANGELOG.md` updated under `## [Unreleased]`
- [ ] If this contradicts `docs/ARCHITECTURE.md`, an ADR is included or the doc is updated in this PR

## Screenshots (frontend changes)

<!-- Before/after, if the UI changed. -->
