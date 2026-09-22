"""Regression test for the eval-nightly KB seeding path (scripts/run_eval.py).

`_seed_kb` previously constructed `KnowledgeBaseMember` directly and omitted the
required `added_at`, which violates the NOT NULL constraint on
`knowledge_base_members.added_at`. It must seed members the same way the app's
normal path does (`KnowledgeBaseRepository.add_member`, which stamps `added_at`).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_eval import _seed_kb  # type: ignore[import-not-found]  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.infra.db.models import KnowledgeBaseMember  # noqa: E402


async def test_seed_kb_persists_member_with_added_at(db_session: AsyncSession) -> None:
    kb_id = await _seed_kb("handbook")

    db_session.expire_all()
    result = await db_session.execute(
        select(KnowledgeBaseMember).where(KnowledgeBaseMember.knowledge_base_id == kb_id)
    )
    members = result.scalars().all()

    assert len(members) == 1
    assert members[0].added_at is not None
