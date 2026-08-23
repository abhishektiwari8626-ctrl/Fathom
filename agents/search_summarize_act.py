"""Multi-Step AI Agent Demo — Search -> Summarize -> Decide -> Act.

Demonstrates causal tracing using the Fathom SDK (@fathom_trace).
Supports both normal execution and intentional failure scenarios
(tool failure, semantic drift / hallucination, schema mismatch) for
demonstrating the 3-Phase Evaluation Engine and debugging workflow.

Owner: Abhishek
"""

import argparse
import sys
import time
from uuid import UUID

from fathom_sdk import FathomClient, current_run_id, fathom_trace

# Default client instance
client = FathomClient(endpoint="http://localhost:8000/api/v1", flush_interval_s=0.5)


# ──────────────────────────────────────────
# Step 1: Web Search (tool_call)
# ──────────────────────────────────────────
@fathom_trace(client=client, kind="tool_call", name="web_search", metadata={"expected_schema": {"query": "string", "limit": "integer"}})
def web_search(query: str, limit: int = 5, simulate_failure: bool = False) -> dict:
    """Execute external search API to retrieve knowledge items."""
    time.sleep(0.05)  # Simulate network latency

    if simulate_failure:
        return {
            "status_code": 500,
            "status": "error",
            "error": "Upstream search service unavailable",
            "results": [],
        }

    return {
        "status_code": 200,
        "status": "success",
        "query": query,
        "results": [
            {
                "title": f"Official Guide for {query}",
                "snippet": f"Detailed step-by-step instructions regarding {query}. First verify identity, then apply changes.",
                "url": "https://docs.example.com/guide",
            },
            {
                "title": f"Troubleshooting {query}",
                "snippet": f"Common resolution paths for {query} issues with high priority resolution flags.",
                "url": "https://docs.example.com/troubleshoot",
            },
        ],
    }


# ──────────────────────────────────────────
# Step 2: Summarize (llm_call)
# ──────────────────────────────────────────
@fathom_trace(client=client, kind="llm_call", name="summarize_search_results", model="gpt-4o")
def summarize_search_results(search_data: dict, simulate_hallucination: bool = False) -> dict:
    """Summarize retrieved information using LLM."""
    time.sleep(0.08)

    if simulate_hallucination:
        # Intentionally produce hallucinated output completely unrelated to query
        return {
            "summary": "Medieval French castles were constructed primarily from limestone and timber during the 12th century under King Philip II.",
            "confidence": 0.42,
            "hallucination_injected": True,
        }

    results = search_data.get("results", [])
    snippets = " ".join(r.get("snippet", "") for r in results)
    summary_text = f"Summary of search results: {snippets}" if snippets else "No relevant information found."

    return {
        "summary": summary_text,
        "confidence": 0.96,
        "source_count": len(results),
    }


# ──────────────────────────────────────────
# Step 3: Decide Action (agent_decision)
# ──────────────────────────────────────────
@fathom_trace(client=client, kind="agent_decision", name="decide_next_action")
def decide_next_action(summary_data: dict, simulate_invalid_decision: bool = False) -> dict:
    """Determine downstream action based on LLM summary."""
    time.sleep(0.04)

    summary = summary_data.get("summary", "")

    if simulate_invalid_decision:
        return {
            "action": "unknown_operation_xyz",
            "reason": "Faulty decision tree triggered invalid routing.",
            "target": None,
        }

    if "priority" in summary.lower() or "urgent" in summary.lower() or "troubleshoot" in summary.lower():
        action = "escalate_ticket"
        target = "engineering_support"
    else:
        action = "notify_user"
        target = "user_inbox"

    return {
        "action": action,
        "target": target,
        "reason": f"Routing determined from summary keywords: {action}",
    }


# ──────────────────────────────────────────
# Step 4: Act (tool_call)
# ──────────────────────────────────────────
@fathom_trace(client=client, kind="tool_call", name="execute_action", metadata={"expected_schema": {"action": "string", "target": "string"}})
def execute_action(decision: dict, simulate_action_error: bool = False) -> dict:
    """Execute decided action via downstream service."""
    time.sleep(0.06)

    action = decision.get("action")
    target = decision.get("target")

    if simulate_action_error or not target:
        return {
            "status_code": 400,
            "status": "bad_request",
            "error": f"Invalid action payload: action={action}, target={target}",
        }

    return {
        "status_code": 200,
        "status": "sent",
        "action_executed": action,
        "recipient": target,
        "confirmation_id": "act_987654321",
    }


# ──────────────────────────────────────────
# Full Pipeline (processing root)
# ──────────────────────────────────────────
@fathom_trace(client=client, kind="processing", name="search_summarize_act_pipeline")
def run_search_summarize_act_pipeline(query: str, scenario: str = "success") -> dict:
    """Run full multi-step agent pipeline with parent-child span hierarchy."""
    scenario = scenario.lower()

    # Step 1: Search
    search_data = web_search(
        query=query,
        limit=5,
        simulate_failure=(scenario == "tool_error"),
    )

    if search_data.get("status_code", 200) >= 400:
        return {
            "success": False,
            "error": "Pipeline halted at web search step",
            "search_data": search_data,
        }

    # Step 2: Summarize
    summary_data = summarize_search_results(
        search_data=search_data,
        simulate_hallucination=(scenario == "hallucination"),
    )

    # Step 3: Decide
    decision = decide_next_action(
        summary_data=summary_data,
        simulate_invalid_decision=(scenario == "bad_decision"),
    )

    # Step 4: Act
    action_result = execute_action(
        decision=decision,
        simulate_action_error=(scenario == "action_error" or scenario == "bad_decision"),
    )

    return {
        "success": action_result.get("status_code", 200) < 400,
        "query": query,
        "scenario": scenario,
        "summary": summary_data.get("summary"),
        "decision": decision,
        "action_result": action_result,
    }


def main():
    parser = argparse.ArgumentParser(description="Run Fathom Search-Summarize-Act Demo Agent")
    parser.add_argument("--query", type=str, default="Fix deployment authentication error", help="Query to run")
    parser.add_argument(
        "--scenario",
        type=str,
        choices=["success", "tool_error", "hallucination", "bad_decision", "action_error"],
        default="success",
        help="Execution scenario to simulate",
    )
    parser.add_argument("--endpoint", type=str, default="http://localhost:8000/api/v1", help="Fathom API endpoint")

    args = parser.parse_args()

    client.endpoint = args.endpoint
    client.start()

    run_name = f"Demo Agent — {args.scenario.upper()} ({args.query[:30]})"
    try:
        run_id = client.create_run(run_name, metadata={"scenario": args.scenario, "query": args.query})
        print(f"🚀 Started trace run {run_id}: {run_name}")
    except Exception as e:
        print(f"⚠️ Could not create run via API ({e}). Running locally with mock run ID.")
        from uuid import uuid4
        run_id = uuid4()

    # Set active run ID in context
    token = current_run_id.set(run_id)
    try:
        result = run_search_summarize_act_pipeline(query=args.query, scenario=args.scenario)
        print(f" Pipeline finished with result: {result.get('success', False)}")
        print(f"📋 Output: {result}")
    finally:
        current_run_id.reset(token)
        print(" Flushing spans...")
        client.shutdown()
        print("✅ Finished.")


if __name__ == "__main__":
    main()
