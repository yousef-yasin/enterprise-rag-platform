"""Infrastructure adapters (docs/ARCHITECTURE.md §3.2).

Implements ``app.core`` interfaces against concrete technology (PostgreSQL, Qdrant,
Redis, object storage). Phase 0 contains only reachability probes for readiness
reporting — no ORM models, clients or repositories yet.
"""
