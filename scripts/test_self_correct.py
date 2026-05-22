"""Deterministic test of the LangGraph self-correct retry loop against real Gemini.

The first SQL generation is force-failed (returns a query referencing a
non-existent column), which trips validation. The orchestrator's self-correct
edge then routes back through SQLGenerationAgent, which this time delegates
to the real Gemini-backed generator with the error in its prompt context.

A successful run shows:
  - trace contains a `self_correct` step
  - retry_count == 1
  - final validation_ok is True
  - final SQL no longer references the bad column
  - the query actually executes

Usage:
    python -m scripts.test_self_correct
"""
from __future__ import annotations

from app.agents import sql_agent
from app.agents.orchestrator import get_full_pipeline
from app.monitoring.logger import configure_logging

# Wrap the real SQLGenerationAgent so its FIRST call returns deliberately bad
# SQL. Subsequent calls (the self-correct retries) hit Gemini for real.
_orig_run = sql_agent.SQLGenerationAgent.run
_call_count: dict[str, int] = {"n": 0}


def _patched_run(self, state):  # type: ignore[no-untyped-def]
    _call_count["n"] += 1
    if _call_count["n"] == 1:
        # Hallucinated column. Validation will flag "Unknown columns: [customers.phone]"
        state.set("sql", "SELECT phone FROM customers LIMIT 5")
        state.set("explanation", "(forced first failure for self-correct test)")
        return
    return _orig_run(self, state)


def main() -> None:
    configure_logging()
    sql_agent.SQLGenerationAgent.run = _patched_run  # type: ignore[method-assign]
    # Pipeline is lru_cache'd; clear so it rebuilds with the patched class.
    get_full_pipeline.cache_clear()
    pipe = get_full_pipeline()

    state = pipe.run({
        "query": "How many customers are there in each region?",
        "rewrite": True,
        "top_k": 5,
    })

    print("=== final SQL ===")
    print(" ", state.get("sql"))
    print("=== retry_count ===", state.get("retry_count", 0))
    print("=== validation_ok ===", state.get("validation_ok"))
    print("=== validation_issues ===", state.get("validation_issues") or [])
    print("=== trace ===")
    for i, t in enumerate(state.trace):
        print(f"  {i+1}. {t.name:18s} {t.latency_ms:6.0f}ms  wrote={t.output_keys}")
    r = state.get("execution_result")
    print("=== execution result ===")
    if r is not None:
        print(f"  {r.row_count} row(s) in {r.latency_ms:.0f}ms")
        print(f"  cols={r.columns}")
        print(f"  rows={r.rows}")
    else:
        print("  not executed")

    # Sanity assertions
    assert _call_count["n"] >= 2, "SQL generation was only called once -- retry did not fire"
    assert state.get("retry_count", 0) >= 1, "retry_count should be >=1 after a forced failure"
    assert any(t.name == "self_correct" for t in state.trace), "self_correct node never fired"
    print("\nPASS: self-correct loop fired with real Gemini doing the recovery.")


if __name__ == "__main__":
    main()
