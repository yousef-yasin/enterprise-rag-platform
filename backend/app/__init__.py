"""enterprise-rag-platform backend package.

Layering (docs/ARCHITECTURE.md §3.2), dependency arrow points inward:

    api  ->  schemas / services  ->  core (domain + interfaces)  <-  providers / infra

`core` imports nothing outward. `providers` and `infra` implement `core` interfaces.
"""

__version__ = "0.0.0"  # bumped at release (Phase 10)
