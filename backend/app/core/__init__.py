"""Domain core (docs/ARCHITECTURE.md §3.2).

Domain logic and provider *interfaces*. This layer imports only the standard
library, ``pydantic`` (for value objects) and its own submodules — never
``app.api``, ``app.services``, ``app.providers``, ``app.infra`` or a vendor SDK.
"""
