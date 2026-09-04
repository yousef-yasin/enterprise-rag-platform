"""Offline evaluation primitives (docs/ARCHITECTURE.md §33).

Pure, dependency-light functions: retrieval + answer + citation + abstention
metrics, and bootstrap confidence intervals. The orchestration that runs a
dataset through the live pipeline lives in ``app.services.evaluation``.
"""
