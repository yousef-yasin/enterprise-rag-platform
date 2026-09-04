"""HTTP boundary (docs/ARCHITECTURE.md §3.2, §23).

Routing, DTO validation, middleware and the error envelope. Route handlers contain
no business logic — they parse, call a service, and serialise.
"""
