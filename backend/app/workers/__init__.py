"""Background worker (docs/ARCHITECTURE.md §22, ADR 0002).

Shares the API image; entrypoint ``arq app.workers.worker.WorkerSettings``. Phase 0
has no task functions — ingestion tasks (Phase 2) and the reconciliation / trace-GC
cron jobs (Phases 2, 9) are added later.
"""
