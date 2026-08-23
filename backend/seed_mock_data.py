"""Seed PostgreSQL with realistic multi-step AI agent trace data.

Creates 3 runs with different topologies so all team members can test:
  1. Clean linear run (4 steps, all pass) — for Swastika's DAG rendering
  2. Branching run (fan-out to 2 parallel steps, warning on one) — for Rushikesh's DAG assembly
  3. Failed run (failure at step 3 with hallucination) — for Abhishek's evaluator & Rushikesh's rewind

Run with:
    cd backend
    python seed_mock_data.py
"""

import asyncio
import random
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, engine, Base
from app.models import TraceRun, TraceSpan, Evaluation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _random_embedding(dim: int = 384) -> list[float]:
    """Generate a random 384-dim vector (simulates MiniLM output)."""
    random.seed(42)  # Reproducible
    return [round(random.uniform(-1, 1), 6) for _ in range(dim)]


async def seed():
    """Main seeding function."""
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        # Check if data already exists
        result = await db.execute(text("SELECT COUNT(*) FROM trace_runs"))
        count = result.scalar()
        if count and count > 0:
            print(f"⚠️  Database already has {count} runs. Skipping seed.")
            print("   To re-seed, drop the tables first: DROP TABLE evaluations, trace_spans, trace_runs CASCADE;")
            return

        print("🌱 Seeding database with realistic trace data...\n")

        await _seed_run_1_linear_success(db)
        await _seed_run_2_branching_warning(db)
        await _seed_run_3_failed_hallucination(db)

        await db.commit()
        print("\n✅ Seeding complete! 3 runs with spans and evaluations created.")


# ──────────────────────────────────────────
# Run 1: Clean Linear Success (Search → Extract → Summarize → Email)
# ──────────────────────────────────────────

async def _seed_run_1_linear_success(db: AsyncSession):
    """4-step linear pipeline, all steps pass."""
    print("  📗 Run 1: Clean linear pipeline (4 steps, all pass)")

    run_id = uuid.uuid4()
    run = TraceRun(
        id=run_id,
        name="Customer Support — Find & Email FAQ Answer",
        status="completed",
        total_tokens=1850,
        total_latency_ms=3420.5,
        metadata_={"agent": "support-bot-v2", "customer_id": "cust_12345"},
    )
    db.add(run)

    # Span 1: Web Search (root)
    s1_id = uuid.uuid4()
    s1 = TraceSpan(
        id=s1_id, run_id=run_id, parent_span_id=None,
        name="web_search",
        kind="tool_call", status="completed",
        input_data={"query": "How to reset password on Acme Portal", "max_results": 5},
        output_data={
            "results": [
                {"title": "Acme Portal Password Reset Guide", "url": "https://help.acme.com/password-reset", "snippet": "To reset your password, go to Settings > Security > Reset Password..."},
                {"title": "Acme Account Recovery", "url": "https://help.acme.com/account-recovery", "snippet": "If you forgot your password, click 'Forgot Password' on the login page..."},
            ]
        },
        latency_ms=820.3, token_count=0,
        metadata_={"api": "google_search", "status_code": 200},
    )

    # Span 2: Extract relevant content (child of s1)
    s2_id = uuid.uuid4()
    s2 = TraceSpan(
        id=s2_id, run_id=run_id, parent_span_id=s1_id,
        name="extract_content",
        kind="processing", status="completed",
        input_data={"urls": ["https://help.acme.com/password-reset"]},
        output_data={"extracted_text": "To reset your password: 1) Go to Settings, 2) Click Security, 3) Click Reset Password, 4) Enter your email, 5) Check your inbox for the reset link."},
        latency_ms=450.1, token_count=0,
    )

    # Span 3: Summarize with LLM (child of s2)
    s3_id = uuid.uuid4()
    s3 = TraceSpan(
        id=s3_id, run_id=run_id, parent_span_id=s2_id,
        name="summarize_answer",
        kind="llm_call", status="completed",
        input_data={"system": "You are a helpful support agent. Summarize this clearly.", "content": "To reset your password: 1) Go to Settings..."},
        output_data={"summary": "To reset your Acme Portal password: Go to Settings → Security → Reset Password. Enter your email and check your inbox for the reset link."},
        latency_ms=1200.0, token_count=1450, model_name="gpt-4o",
        embedding=_random_embedding(),
    )

    # Span 4: Send email (child of s3)
    s4_id = uuid.uuid4()
    s4 = TraceSpan(
        id=s4_id, run_id=run_id, parent_span_id=s3_id,
        name="send_email_response",
        kind="tool_call", status="completed",
        input_data={"to": "customer@example.com", "subject": "Your Password Reset Instructions", "body": "To reset your Acme Portal password: Go to Settings → Security → Reset Password..."},
        output_data={"email_id": "msg_abc123", "status": "sent"},
        latency_ms=950.1, token_count=400,
        metadata_={"provider": "sendgrid", "status_code": 200},
    )

    db.add_all([s1, s2, s3, s4])
    await db.flush()

    # Evaluations for all spans — all pass
    for span_id in [s1_id, s2_id, s3_id, s4_id]:
        evals = [
            Evaluation(span_id=span_id, phase="tool_check", verdict="pass", score=1.0,
                       details={"schema_valid": True, "http_status": 200}, summary=None),
            Evaluation(span_id=span_id, phase="semantic_drift", verdict="pass", score=0.92,
                       details={"cosine_similarity": 0.92, "drift_threshold": 0.70, "drift_detected": False}, summary=None),
            Evaluation(span_id=span_id, phase="judge_llm", verdict="pass", score=0.95,
                       details={"judge_model": "gpt-4o-mini", "reasoning": "Output is accurate and well-structured."},
                       summary="This step completed correctly. The output accurately reflects the input data."),
        ]
        db.add_all(evals)


# ──────────────────────────────────────────
# Run 2: Branching with Warning (Search → [Branch A: News Summary, Branch B: Sentiment])
# ──────────────────────────────────────────

async def _seed_run_2_branching_warning(db: AsyncSession):
    """Branching pipeline: 1 root fans out to 2 parallel branches. Warning on Branch B."""
    print("  📙 Run 2: Branching pipeline (fan-out, warning on sentiment branch)")

    run_id = uuid.uuid4()
    run = TraceRun(
        id=run_id,
        name="Market Research — News Analysis with Sentiment",
        status="completed",
        total_tokens=2200,
        total_latency_ms=4100.0,
        metadata_={"agent": "research-bot-v1", "market": "AI/ML"},
    )
    db.add(run)

    # Root: Search for news
    root_id = uuid.uuid4()
    root = TraceSpan(
        id=root_id, run_id=run_id, parent_span_id=None,
        name="search_news",
        kind="tool_call", status="completed",
        input_data={"query": "latest AI regulations 2026", "sources": ["reuters", "techcrunch"]},
        output_data={"articles": [
            {"title": "EU AI Act Enforcement Begins", "source": "reuters"},
            {"title": "OpenAI Responds to New Compliance Requirements", "source": "techcrunch"},
        ]},
        latency_ms=900.0, token_count=0,
        metadata_={"api": "news_api", "status_code": 200},
    )

    # Branch A: Summarize news (child of root) — passes
    branch_a_id = uuid.uuid4()
    branch_a = TraceSpan(
        id=branch_a_id, run_id=run_id, parent_span_id=root_id,
        name="summarize_news",
        kind="llm_call", status="completed",
        input_data={"articles": ["EU AI Act Enforcement Begins", "OpenAI Responds to New Compliance Requirements"]},
        output_data={"summary": "The EU has begun enforcing the AI Act, requiring companies to comply with transparency and risk assessment rules. OpenAI has published their compliance roadmap."},
        latency_ms=1400.0, token_count=1200, model_name="gpt-4o",
        embedding=_random_embedding(),
    )

    # Branch B: Sentiment analysis (child of root) — warning (mild drift)
    branch_b_id = uuid.uuid4()
    branch_b = TraceSpan(
        id=branch_b_id, run_id=run_id, parent_span_id=root_id,
        name="analyze_sentiment",
        kind="llm_call", status="completed",
        input_data={"text": "EU AI Act Enforcement Begins. OpenAI Responds to New Compliance Requirements."},
        output_data={"sentiment": "cautiously_optimistic", "confidence": 0.72, "note": "Market sees regulation as positive long-term but costly short-term. Some analysts predict a 15% increase in compliance spending."},
        latency_ms=1100.0, token_count=800, model_name="gpt-4o",
        embedding=_random_embedding(),
    )

    # Final: Decision node (child of both branches — uses branch_a as parent for simplicity)
    decision_id = uuid.uuid4()
    decision = TraceSpan(
        id=decision_id, run_id=run_id, parent_span_id=branch_a_id,
        name="decide_report_action",
        kind="agent_decision", status="completed",
        input_data={"summary": "EU AI Act enforcement...", "sentiment": "cautiously_optimistic"},
        output_data={"action": "generate_weekly_report", "priority": "medium"},
        latency_ms=700.0, token_count=200,
    )

    db.add_all([root, branch_a, branch_b, decision])
    await db.flush()

    # Evaluations
    # Root + Branch A + Decision: all pass
    for span_id in [root_id, branch_a_id, decision_id]:
        db.add_all([
            Evaluation(span_id=span_id, phase="tool_check", verdict="pass", score=1.0,
                       details={"schema_valid": True, "http_status": 200}),
            Evaluation(span_id=span_id, phase="semantic_drift", verdict="pass", score=0.88,
                       details={"cosine_similarity": 0.88, "drift_threshold": 0.70, "drift_detected": False}),
            Evaluation(span_id=span_id, phase="judge_llm", verdict="pass", score=0.90,
                       details={"judge_model": "gpt-4o-mini"},
                       summary="Step completed correctly with accurate output."),
        ])

    # Branch B: WARNING — mild semantic drift
    db.add_all([
        Evaluation(span_id=branch_b_id, phase="tool_check", verdict="pass", score=1.0,
                   details={"schema_valid": True}),
        Evaluation(span_id=branch_b_id, phase="semantic_drift", verdict="warning", score=0.73,
                   details={"cosine_similarity": 0.73, "drift_threshold": 0.70, "drift_detected": False,
                            "note": "Output includes analyst predictions not present in input"}),
        Evaluation(span_id=branch_b_id, phase="judge_llm", verdict="warning", score=0.68,
                   details={"judge_model": "gpt-4o-mini",
                            "reasoning": "The output mentions a '15% increase in compliance spending' which is not supported by the input articles. This may be a hallucination."},
                   summary="Warning: The sentiment analysis added a claim about '15% increase in compliance spending' that wasn't in the original articles. This might be made up by the AI. The rest of the analysis looks correct."),
    ])


# ──────────────────────────────────────────
# Run 3: Failed Run (Search → Summarize → ❌ Hallucinated Action → Crash)
# ──────────────────────────────────────────

async def _seed_run_3_failed_hallucination(db: AsyncSession):
    """Failed pipeline: step 3 hallucinates, step 4 crashes."""
    print("  📕 Run 3: Failed pipeline (hallucination at step 3, crash at step 4)")

    run_id = uuid.uuid4()
    run = TraceRun(
        id=run_id,
        name="Lead Qualification — Enrich & Score Prospect",
        status="failed",
        total_tokens=1600,
        total_latency_ms=5200.0,
        metadata_={"agent": "sales-bot-v1", "lead_id": "lead_99887"},
    )
    db.add(run)

    # Step 1: CRM Lookup (root)
    s1_id = uuid.uuid4()
    s1 = TraceSpan(
        id=s1_id, run_id=run_id, parent_span_id=None,
        name="crm_lookup",
        kind="tool_call", status="completed",
        input_data={"lead_id": "lead_99887", "fields": ["name", "company", "industry", "annual_revenue"]},
        output_data={"name": "Jane Smith", "company": "NovaTech", "industry": "FinTech", "annual_revenue": 5_000_000},
        latency_ms=300.0, token_count=0,
        metadata_={"api": "salesforce", "status_code": 200},
    )

    # Step 2: Web enrichment (child of s1)
    s2_id = uuid.uuid4()
    s2 = TraceSpan(
        id=s2_id, run_id=run_id, parent_span_id=s1_id,
        name="web_enrich_company",
        kind="retrieval", status="completed",
        input_data={"company": "NovaTech", "search_query": "NovaTech FinTech company overview"},
        output_data={"description": "NovaTech is a Series B FinTech startup focused on payment processing for SMBs.", "employee_count": 120, "funding": "$25M Series B"},
        latency_ms=650.0, token_count=0,
    )

    # Step 3: LLM scoring — HALLUCINATED (child of s2)
    s3_id = uuid.uuid4()
    s3 = TraceSpan(
        id=s3_id, run_id=run_id, parent_span_id=s2_id,
        name="score_lead_with_llm",
        kind="llm_call", status="completed",
        input_data={"lead_name": "Jane Smith", "company": "NovaTech", "industry": "FinTech", "revenue": 5_000_000, "context": "Series B startup, 120 employees"},
        output_data={
            "score": 92,
            "tier": "Enterprise",
            "reasoning": "NovaTech recently closed a $100M Series C round and is expanding to 500 employees. They are a Fortune 500 company with strong enterprise purchasing power.",
            "recommended_action": "Assign to Enterprise sales team immediately"
        },
        latency_ms=1800.0, token_count=1200, model_name="gpt-4o",
        embedding=_random_embedding(),
    )

    # Step 4: Auto-assign to sales team — CRASHED (child of s3)
    s4_id = uuid.uuid4()
    s4 = TraceSpan(
        id=s4_id, run_id=run_id, parent_span_id=s3_id,
        name="assign_to_sales_team",
        kind="tool_call", status="failed",
        input_data={"lead_id": "lead_99887", "team": "Enterprise", "priority": "urgent", "score": 92},
        output_data={},
        error_message='Traceback (most recent call last):\n  File "agents/sales_bot.py", line 87, in assign_to_sales_team\n    team = crm.get_team(team_name="Enterprise")\n  File "lib/crm_client.py", line 42, in get_team\n    raise TeamNotFoundError(f"Team \'{team_name}\' does not exist")\nTeamNotFoundError: Team \'Enterprise\' does not exist. Available teams: SMB, MidMarket, Strategic.',
        latency_ms=2450.0, token_count=400,
        metadata_={"api": "salesforce", "status_code": 404},
    )

    db.add_all([s1, s2, s3, s4])
    await db.flush()

    # Evaluations
    # Steps 1 & 2: pass
    for span_id in [s1_id, s2_id]:
        db.add_all([
            Evaluation(span_id=span_id, phase="tool_check", verdict="pass", score=1.0,
                       details={"schema_valid": True, "http_status": 200}),
            Evaluation(span_id=span_id, phase="semantic_drift", verdict="pass", score=0.91,
                       details={"cosine_similarity": 0.91, "drift_threshold": 0.70, "drift_detected": False}),
            Evaluation(span_id=span_id, phase="judge_llm", verdict="pass", score=0.93,
                       details={"judge_model": "gpt-4o-mini"},
                       summary="Step completed correctly."),
        ])

    # Step 3: FAILURE — major hallucination
    db.add_all([
        Evaluation(span_id=s3_id, phase="tool_check", verdict="pass", score=1.0,
                   details={"schema_valid": True}),
        Evaluation(span_id=s3_id, phase="semantic_drift", verdict="failure", score=0.41,
                   details={"cosine_similarity": 0.41, "drift_threshold": 0.70, "drift_detected": True,
                            "note": "Output contains major claims not present in input: $100M Series C, 500 employees, Fortune 500"}),
        Evaluation(span_id=s3_id, phase="judge_llm", verdict="failure", score=0.25,
                   details={"judge_model": "gpt-4o-mini",
                            "reasoning": "The LLM fabricated multiple facts: NovaTech is a Series B company with $25M funding and 120 employees, but the output claims it closed a '$100M Series C round', is 'expanding to 500 employees', and is a 'Fortune 500 company'. None of these claims exist in the input data. The lead was scored as 'Enterprise' tier based on hallucinated data, leading to incorrect downstream routing."},
                   summary="FAILURE: The AI completely made up facts about NovaTech. It said the company raised $100M in Series C funding, has 500 employees, and is a Fortune 500 company — none of which is true. The real data says it's a Series B startup with $25M funding and 120 employees. Because of these made-up facts, the lead got an inflated score of 92 and was wrongly classified as 'Enterprise' tier."),
    ])

    # Step 4: FAILURE — tool error caused by step 3's hallucination
    db.add_all([
        Evaluation(span_id=s4_id, phase="tool_check", verdict="failure", score=0.0,
                   details={"schema_valid": True, "http_status": 404,
                            "error": "Team 'Enterprise' does not exist. Available: SMB, MidMarket, Strategic"}),
        Evaluation(span_id=s4_id, phase="semantic_drift", verdict="failure", score=0.0,
                   details={"note": "Span failed before producing output"}),
        Evaluation(span_id=s4_id, phase="judge_llm", verdict="failure", score=0.15,
                   details={"judge_model": "gpt-4o-mini",
                            "reasoning": "This step crashed because it tried to assign the lead to an 'Enterprise' sales team that doesn't exist in the CRM. The root cause is the previous step (score_lead_with_llm) which hallucinated that NovaTech is an enterprise-grade company. The available teams are: SMB, MidMarket, Strategic."},
                   summary="FAILURE: This step crashed because it tried to assign the lead to an 'Enterprise' sales team — but that team doesn't exist. The available teams are SMB, MidMarket, and Strategic. This happened because the previous step (AI scoring) made up false facts and wrongly classified the lead as 'Enterprise'. Fix the scoring step first, then this step should work."),
    ])


# ──────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(seed())
