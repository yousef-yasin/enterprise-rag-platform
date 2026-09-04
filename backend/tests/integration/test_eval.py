"""Evaluation harness end-to-end on the `smoke` split (Phase 9 gate).

Runs the real retrieval + generation pipeline with fake providers; asserts the
run persists with bootstrap-CI metrics and is served by GET /eval/runs.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.config import get_settings
from app.services.evaluation import EvaluationService
from app.services.ingestion import IngestionPipeline
from tests.integration._helpers import create_kb, register_and_auth

_HANDBOOK = b"""# Acme Handbook

## Paid time off
Full-time employees accrue 25 days of paid annual leave per year.

## Sick leave
Employees receive 10 paid sick days per year.
"""

_SECURITY = b"""# Information Security Policy

## Passwords
Passwords must be at least 14 characters. Service accounts rotate credentials every 90 days.

## Incident response
Suspected security incidents must be reported within one hour of discovery.
"""


async def _seed(client: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    kb = await create_kb(client, headers, slug="eval-kb")
    for name, data in (("handbook.md", _HANDBOOK), ("security-policy.md", _SECURITY)):
        resp = await client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/documents",
            headers=headers,
            files={"file": (name, data, "text/markdown")},
        )
        await IngestionPipeline(get_settings()).run(resp.json()["id"])
    return uuid.UUID(str(kb["id"]))


async def test_smoke_eval_run_persists_with_cis(client: AsyncClient) -> None:
    headers = await register_and_auth(client, email="eval-admin@example.com")
    kb_id = await _seed(client, headers)

    run_id = await EvaluationService(get_settings()).run(
        knowledge_base_id=kb_id,
        dataset="handbook",
        split="smoke",
        config_label="ci-smoke",
        judge_enabled=True,
    )

    resp = await client.get(f"/api/v1/eval/runs/{run_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dataset"] == "handbook"
    assert body["split"] == "smoke"
    assert body["n_samples"] == 6
    metrics = body["metrics"]

    # abstention metrics are always computed (3 answerable + 3 unanswerable in the split)
    assert "abstention_precision" in metrics
    assert "abstention_recall" in metrics

    # retrieval metrics have bootstrap CIs
    assert "recall_at_k" in metrics
    rc = metrics["recall_at_k"]
    assert rc["ci_low"] <= rc["value"] <= rc["ci_high"]
    assert rc["n"] == 4  # 4 answerable samples carry relevant_doc_names

    # judge ran (FakeLLM structured output) -> judge_* keys present
    assert "judge_correct" in metrics

    # cost + token accounting
    assert "cost_usd_total" in metrics
    assert "prompt_tokens_mean" in metrics

    # listed by the runs endpoint
    listing = await client.get("/api/v1/eval/runs", headers=headers)
    assert run_id_str(run_id) in {r["id"] for r in listing.json()["items"]}

    # samples endpoint
    samples = await client.get(f"/api/v1/eval/runs/{run_id}/samples", headers=headers)
    assert samples.status_code == 200
    assert len(samples.json()["items"]) == 6


def run_id_str(run_id: uuid.UUID) -> str:
    return str(run_id)
