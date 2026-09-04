"""Data-access repositories (docs/ARCHITECTURE.md §3.2).

Thin wrappers over an ``AsyncSession``: query construction and persistence only, no
business rules. Services compose them.
"""
