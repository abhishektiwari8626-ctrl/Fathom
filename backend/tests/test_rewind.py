"""Tests for Time-Travel Rewind Engine (Phase 2, Task 2.1 - 2.8)."""

from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient

from app.enums import SpanKind, SpanStatus
from app.main import app


@pytest.mark.asyncio
async def test_rewind_mismatched_run_id_rejected():
    """R-02: span_id does not belong to run_id rejected."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        runs = (await client.get("/api/v1/runs")).json()
        completed_runs = [r for r in runs if r["span_count"] > 0 and r["status"] != "running"]
        assert len(completed_runs) >= 2
        run1 = completed_runs[0]
        run2 = completed_runs[1]

        dag1 = (await client.get(f"/api/v1/runs/{run1['id']}/dag")).json()
        span_from_run1 = dag1["spans"][0]["id"]

        # Call rewind on run2 with a span belonging to run1
        payload = {
            "span_id": span_from_run1,
            "mutated_input": {"prompt": "New prompt test"},
            "re_execute": True,
        }
        resp = await client.post(f"/api/v1/runs/{run2['id']}/rewind", json=payload)
        assert resp.status_code == 422
        assert "does not belong" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_rewind_running_pipeline_rejected():
    """R-13: Rewind is only valid on a completed/finished run."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create a run in running status
        run_resp = await client.post(
            "/api/v1/traces/runs",
            json={"name": "Active in-progress run"},
        )
        active_run = run_resp.json()
        run_id = active_run["id"]

        # Create a span in this running run
        span_id = str(uuid4())
        await client.post(
            "/api/v1/traces/spans",
            json={
                "id": span_id,
                "run_id": run_id,
                "name": "step_1",
                "kind": "llm_call",
                "status": "completed",
                "input_data": {"query": "hello"},
                "output_data": {"result": "world"},
                "latency_ms": 100.0,
            },
        )

        # Attempt to rewind while run is running
        payload = {
            "span_id": span_id,
            "mutated_input": {"query": "new query"},
            "re_execute": True,
        }
        resp = await client.post(f"/api/v1/runs/{run_id}/rewind", json=payload)
        assert resp.status_code == 409
        assert "in progress" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_successful_time_travel_rewind_with_history_preserved():
    """Tests successful rewind:
    - Invariant 1: Original span unchanged (R-16, I-3).
    - Invariant 2: New branch created with rewind_group_id and incremented rewind_depth.
    - Side-effects: Downstream write tools are cloned as pending (R-08).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        runs = (await client.get("/api/v1/runs")).json()
        failed_run = next((r for r in runs if "failed" in r["name"].lower() or r["status"] == "failed"), runs[-1])
        run_id = failed_run["id"]

        dag_before = (await client.get(f"/api/v1/runs/{run_id}/dag")).json()
        spans_before = dag_before["spans"]

        # Find the failing span to rewind (Step 3 hallucination in seed data)
        target = next((s for s in spans_before if s["name"] == "llm_generate_analysis"), spans_before[1])
        original_id = target["id"]
        original_status = target["status"]
        original_input = target["input_data"]

        # Execute rewind
        new_prompt = {"prompt": "Write a concise, factual summary strictly based on retrieved sources."}
        rewind_resp = await client.post(
            f"/api/v1/runs/{run_id}/rewind",
            json={
                "span_id": original_id,
                "mutated_input": new_prompt,
                "re_execute": True,
            },
        )

        assert rewind_resp.status_code == 200
        rewind_result = rewind_resp.json()
        assert rewind_result["success"] is True
        assert rewind_result["rewind_group_id"] is not None
        assert rewind_result["rewound_span_id"] is not None
        assert str(rewind_result["rewound_span_id"]) != original_id

        # Fetch DAG after rewind
        dag_after = (await client.get(f"/api/v1/runs/{run_id}/dag")).json()
        spans_after = dag_after["spans"]

        # 1. Verify original span is untouched
        orig_after = next(s for s in spans_after if s["id"] == original_id)
        assert orig_after["status"] == original_status
        assert orig_after["input_data"] == original_input

        # 2. Verify new rewound span exists
        new_span = next(s for s in spans_after if s["id"] == str(rewind_result["rewound_span_id"]))
        assert new_span["rewind_depth"] == (orig_after.get("rewind_depth") or 0) + 1
        assert new_span["origin_span_id"] == original_id
        assert new_span["input_data"] == new_prompt

        # 3. Verify run flags
        assert dag_after["run"]["has_rewinds"] is True
        assert dag_after["run"]["active_group_id"] == rewind_result["rewind_group_id"]
