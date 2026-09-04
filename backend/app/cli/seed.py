"""Demo-corpus seeding for ``rag bootstrap`` when ``SEED_ON_BOOTSTRAP=true``
(docs/ARCHITECTURE.md §35).

Idempotent: a "demo" knowledge base and its documents are created once, owned by
the first admin user. Re-running is a no-op. Separate from the evaluation corpus
under ``eval/`` — this exists only so a fresh install has something to query.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import structlog

from app.config import Settings
from app.core.enums import KBRole
from app.core.hashing import content_sha256
from app.infra.db.models import KnowledgeBase, KnowledgeBaseMember, User
from app.infra.db.repositories.documents import DocumentRepository, IngestionJobRepository
from app.infra.db.session import session_scope
from app.infra.storage import build_object_storage
from app.services.ingestion import IngestionPipeline

_log = structlog.get_logger("app.seed")

DEMO_SLUG = "demo"
_SUPPORTED = {".md", ".markdown", ".txt", ".pdf", ".docx"}


def _corpus_dir() -> Path:
    root = Path(__file__).resolve().parents[3] / "seed" / "corpus"
    if root.exists():
        return root
    return Path(__file__).resolve().parents[2] / "seed" / "corpus"


async def seed_corpus(settings: Settings) -> None:
    corpus = _corpus_dir()
    files = sorted(p for p in corpus.glob("**/*") if p.suffix.lower() in _SUPPORTED)
    if not files:
        _log.warning("seed.no_corpus", path=str(corpus))
        return

    async with session_scope(settings) as session:
        from sqlalchemy import select

        admin = (
            await session.execute(
                select(User).where(User.is_admin.is_(True)).order_by(User.created_at).limit(1)
            )
        ).scalar_one_or_none()
        if admin is None:
            _log.warning("seed.no_admin — skipping demo corpus")
            return

        kb = (
            await session.execute(select(KnowledgeBase).where(KnowledgeBase.slug == DEMO_SLUG))
        ).scalar_one_or_none()
        if kb is not None:
            _log.info("seed.kb_exists", kb_id=str(kb.id))
            return

        kb = KnowledgeBase(
            owner_id=admin.id,
            name="Demo",
            slug=DEMO_SLUG,
            description="Sample corpus loaded at bootstrap (SEED_ON_BOOTSTRAP).",
        )
        session.add(kb)
        await session.flush()
        session.add(
            KnowledgeBaseMember(knowledge_base_id=kb.id, user_id=admin.id, role=KBRole.OWNER)
        )
        kb_id = kb.id

    storage = build_object_storage(settings)
    pipeline = IngestionPipeline(settings)
    for path in files:
        data = path.read_bytes()
        key = uuid.uuid4().hex
        await storage.put(key, data, content_type="text/markdown")
        async with session_scope(settings) as session:
            doc = DocumentRepository(session).add(
                kb_id=kb_id,
                filename=path.name,
                content_hash=content_sha256(data),
                mime="text/markdown"
                if path.suffix.lower() in {".md", ".markdown"}
                else "text/plain",
                size_bytes=len(data),
                storage_key=key,
            )
            await session.flush()
            IngestionJobRepository(session).add(doc.id)
            doc_id = str(doc.id)
        result = await pipeline.run(doc_id)
        _log.info("seed.document", filename=path.name, result=result)

    _log.info("seed.done", kb_id=str(kb_id), documents=len(files))
