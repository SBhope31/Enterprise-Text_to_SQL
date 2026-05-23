"""Streamlit frontend for the Text-to-SQL platform.

Runs the agent pipeline in-process (no HTTP hop) and renders the SQL,
explanation, live query results, and the per-agent trace.

Run locally:
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.agents.orchestrator import get_full_pipeline
from app.db.models import Base, SCHEMA_DESCRIPTIONS

st.set_page_config(
    page_title="Text-to-SQL Intelligence",
    page_icon="🧮",
    layout="wide",
)

SAMPLES = [
    "How many customers do we have in total?",
    "Top 5 customers by revenue in the last 3 months",
    "What is the monthly revenue trend for the last 12 months?",
    "Which products had the highest return rate last year?",
    "Average delivery time by carrier",
    "Payment success rate by method this month",
]


@st.cache_resource(show_spinner=False)
def _pipeline():
    """Build the LangGraph pipeline once. Connects to Qdrant on first build."""
    return get_full_pipeline()


def _set_query(text: str) -> None:
    st.session_state["query"] = text


# ---- Sidebar ----
with st.sidebar:
    st.header("⚙️ Settings")
    rewrite = st.toggle(
        "Rewrite query before retrieval",
        value=True,
        help="Expand vague questions and resolve relative dates before schema retrieval.",
    )
    top_k = st.slider("Schema retrieval top-K", 1, 20, 5)
    st.divider()
    st.subheader("Try a sample")
    for s in SAMPLES:
        st.button(
            s, key=f"sample_{s}",
            on_click=_set_query, args=(s,),
            use_container_width=True,
        )

# ---- Main ----
st.title("🧮 Enterprise Text-to-SQL")
st.caption(
    "Ask a question in plain English. The agent pipeline rewrites it, retrieves schema "
    "context (hybrid dense + BM25), generates SQL, validates it (sqlglot AST + LIMIT "
    "enforcement), self-corrects on failure, and runs it."
)

# ---- About this demo (schema scope) ----
_table_names = sorted(Base.metadata.tables.keys())
with st.expander(
    f"📚 About this demo — connected to a sample e-commerce DB ({len(_table_names)} tables)",
    expanded=True,
):
    st.markdown(
        "This is a **schema-grounded** Text-to-SQL agent: it answers questions "
        "against a specific database, not generic SQL questions. The deployed demo "
        "is wired to a seeded e-commerce dataset with the tables below. "
        "**Ask questions about customers, products, orders, returns, payments, "
        "shipments, or employees** — anything outside this schema will produce "
        "stretched / incorrect SQL."
    )
    cols = st.columns(2)
    for i, t in enumerate(_table_names):
        desc = SCHEMA_DESCRIPTIONS.get(t, "").split(".")[0]
        cols[i % 2].markdown(f"**`{t}`** — {desc}")
    st.caption(
        "Want to use your own schema? See the README — the pipeline is "
        "schema-agnostic; only the seeded data is fixed."
    )

query = st.text_area(
    "Your question",
    key="query",
    placeholder="e.g. top 5 customers by revenue in the last 3 months",
    height=90,
)
ask = st.button("Ask", type="primary")

if ask:
    if not query or not query.strip():
        st.warning("Type a question first.")
        st.stop()

    try:
        pipe = _pipeline()
    except Exception as e:
        st.error(
            f"Could not build the pipeline (is Qdrant running and embedded?): {e}"
        )
        st.stop()

    with st.spinner("Running the agent pipeline..."):
        try:
            state = pipe.run(
                {"query": query, "rewrite": rewrite, "top_k": top_k}
            )
        except Exception as e:
            st.error(f"Pipeline failed: {e}")
            st.stop()

    ctx = state.get("schema_context")
    if ctx is None or not getattr(ctx, "tables", None):
        st.error(
            "No schema context retrieved. Run `python -m scripts.embed_schema` "
            "to populate Qdrant, then try again."
        )
        st.stop()

    sql = state.get("sql", "") or ""
    explanation = state.get("explanation", "") or ""
    validation_ok = bool(state.get("validation_ok"))
    issues = list(state.get("validation_issues") or [])
    if state.get("execution_error"):
        issues.append(f"Execution error: {state.get('execution_error')}")
    opt_notes = state.get("optimization_notes") or []
    exec_result = state.get("execution_result")
    rewritten = state.get("rewritten_query", query)
    retries = int(state.get("retry_count", 0))

    # ---- Metrics row ----
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Validation", "Passed" if validation_ok else "Failed")
    c2.metric("Self-correct retries", retries)
    c3.metric(
        "Rows returned",
        exec_result.row_count if exec_result is not None else "—",
    )
    c4.metric(
        "Query latency",
        f"{exec_result.latency_ms:.0f} ms" if exec_result is not None else "—",
    )

    if rewrite and rewritten and rewritten.strip() != query.strip():
        st.caption(f"🔁 Rewritten for retrieval: *{rewritten}*")

    # ---- SQL ----
    st.subheader("Generated SQL")
    st.code(sql or "-- (no SQL generated)", language="sql")

    if explanation:
        st.info(explanation)

    if not validation_ok or issues:
        st.warning(
            "Validation / execution issues:\n\n"
            + "\n".join(f"- {i}" for i in issues)
        )

    if opt_notes:
        with st.expander("Optimization notes"):
            for n in opt_notes:
                st.write(f"- {n}")

    # ---- Results ----
    st.subheader("Results")
    if exec_result is not None and exec_result.rows:
        df = pd.DataFrame(exec_result.rows, columns=exec_result.columns)
        st.dataframe(df, use_container_width=True, hide_index=True)
        if exec_result.truncated:
            st.caption("Result set was truncated to the row cap.")
    elif exec_result is not None:
        st.caption("Query ran successfully but returned no rows.")
    else:
        st.caption("Query was not executed (validation failed).")

    # ---- Agent trace ----
    with st.expander(f"Agent trace ({len(state.trace)} steps)"):
        trace_rows = [
            {
                "step": i + 1,
                "agent": t.name,
                "latency_ms": round(t.latency_ms, 1),
                "wrote": ", ".join(t.output_keys),
                "notes": "; ".join(t.notes),
            }
            for i, t in enumerate(state.trace)
        ]
        st.dataframe(
            pd.DataFrame(trace_rows),
            use_container_width=True,
            hide_index=True,
        )

    # ---- Retrieved schema context ----
    with st.expander("Retrieved schema context"):
        st.text(ctx.render())
