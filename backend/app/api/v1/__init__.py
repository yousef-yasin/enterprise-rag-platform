"""Versioned API router, mounted at ``/api/v1`` (docs/ARCHITECTURE.md section 23)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    api_keys,
    auth,
    chat,
    conversations,
    documents,
    evaluation,
    knowledge_bases,
    search,
)

api_router = APIRouter()
for module in (auth, knowledge_bases, api_keys, documents, search, chat, conversations, evaluation):
    api_router.include_router(module.router)
