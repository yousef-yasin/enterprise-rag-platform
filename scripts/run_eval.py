#!/usr/bin/env python
"""Seed a KB from eval/corpus/<dataset> and run an evaluation split end to end.

Used by the eval-nightly workflow; also handy locally:

    cd backend && uv run python ../scripts/run_eval.py --dataset handbook --split smoke

Writes the run metrics to backend/eval-result.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.core.enums import KBRole  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.infra.db.models import KnowledgeBase, KnowledgeBaseMember, User  # noqa: E402
from app.infra.db.session import session_scope  # noqa: E402
from app.services.evaluation import EvaluationService  # noqa: E402
from app.services.ingestion import IngestionPipeline  # noqa: E402


async def _seed_kb(dataset: str) -> uuid.UUID:
    settings = get_settings()
    corpus_dir = REPO_ROOT / "eval" / "corpus" / dataset
    files = sorted(p for p in corpus_dir.glob("**/*") if p.suffix in {".md", ".txt", ".pdf", ".docx"})
    if not files:
        raise SystemExit(f"no corpus files under {corpus_dir}")

    async with session_scope(settings) as session:
        user = User(
            email="eval-runner@localhost",
            password_hash=hash_password(uuid.uuid4().hex),
            display_name="Eval Runner",
            is_admin=True,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        kb = KnowledgeBase(
            owner_id=user.id, name=f"Eval {dataset}", slug=f"eval-{dataset}-{uuid.uuid4().hex[:8]}"
        )
        session.add(kb)
        await session.flush()
        session.add(
            KnowledgeBaseMember(knowledge_base_id=kb.id, user_id=user.id, role=KBRole.OWNER)
        )
        kb_id = kb.id

    from app.infra.storage import build_object_storage
    from app.infra.db.repositories.documents import DocumentRepository, IngestionJobRepository

    storage = build_object_storage(settings)
    for path in files:
        data = path.read_bytes()
        key = uuid.uuid4().hex
        await storage.put(key, data, content_type="text/markdown")
        async with session_scope(settings) as session:
            doc = DocumentRepository(session).add(
                kb_id=kb_id,
                filename=path.name,
                content_hash=uuid.uuid4().hex,
                mime="text/markdown",
                size_bytes=len(data),
                storage_key=key,
            )
            await session.flush()
            IngestionJobRepository(session).add(doc.id)
            doc_id = str(doc.id)
        await IngestionPipeline(settings).run(doc_id)
    return kb_id


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="handbook")
    parser.add_argument("--split", default="smoke")
    args = parser.parse_args()

    kb_id = await _seed_kb(args.dataset)
    run_id = await EvaluationService(get_settings()).run(
        knowledge_base_id=kb_id,
        dataset=args.dataset,
        split=args.split,
        config_label=f"nightly/{args.split}",
        judge_enabled=True,
    )

    from app.infra.db.models import EvalRun

    async with session_scope(get_settings()) as session:
        run = await session.get(EvalRun, run_id)
        metrics = run.metrics if run else {}

    out = Path("eval-result.json")
    out.write_text(json.dumps({"run_id": str(run_id), "metrics": metrics}, indent=2, default=str))
    print(json.dumps(metrics, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
