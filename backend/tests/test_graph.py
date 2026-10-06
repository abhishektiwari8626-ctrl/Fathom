"""Tests for Graph API and Root-Cause Attribution (Phase 1, Task 1.1 - 1.4)."""

import pytest
from httpx import ASGITransport, AsyncClient
from uuid import uuid4

from app.main import app
from app.enums import EvaluationVerdict


@pytest.mark.asyncio
async def test_list_runs_pagination_and_counts():
    """Test GET /api/v1/runs returns list of runs with span counts."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Fetch runs
        resp = await client.get("/api/v1/runs?limit=10&offset=0")
        assert resp.status_code == 200
        runs = resp.json()
        assert isinstance(runs, list)
        assert len(runs) >= 3

        # 2. Check fields and span_count
        first_run = runs[0]
        assert "id" in first_run
        assert "name" in first_run
        assert "status" in first_run
        assert "span_count" in first_run
        assert first_run["span_count"] > 0
        assert "has_rewinds" in first_run


@pytest.mark.asyncio
async def test_get_run_dag_structure_and_root_cause():
    """Test GET /api/v1/runs/{run_id}/dag returns complete tree, evaluations, and root-cause."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Fetch runs to get IDs
        runs_resp = await client.get("/api/v1/runs")
        runs = runs_resp.json()

        # Find the failed pipeline (Run 3)
        failed_run = next((r for r in runs if "failed" in r["name"].lower() or r["status"] == "failed"), runs[-1])
        run_id = failed_run["id"]

        # Fetch DAG
        dag_resp = await client.get(f"/api/v1/runs/{run_id}/dag")
        assert dag_resp.status_code == 200
        dag = dag_resp.json()

        assert "run" in dag
        assert "spans" in dag
        assert "root_span_ids" in dag
        assert len(dag["root_span_ids"]) >= 1

        # Check spans have no embeddings exposed
        for span in dag["spans"]:
            assert "embedding" not in span
            assert "effective_verdict" in span
            assert "evaluations" in span

        # For failed run, root cause attribution (F-01) must be computed
        assert dag["root_cause"] is not None
        assert "span_id" in dag["root_cause"]
        assert "explanation" in dag["root_cause"]
        assert "confidence" in dag["root_cause"]
        assert dag["root_cause"]["confidence"] > 0


@pytest.mark.asyncio
async def test_get_run_dag_not_found():
    """Test GET /api/v1/runs/{random_uuid}/dag returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing_id = str(uuid4())
        resp = await client.get(f"/api/v1/runs/{missing_id}/dag")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()
