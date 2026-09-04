"""Application services — use-case orchestration (docs/ARCHITECTURE.md §3.2, §4.1).

Services depend on ``core`` interfaces and receive concrete implementations by
dependency injection. Phase 0 ships only :class:`~app.services.health.HealthService`.
"""
