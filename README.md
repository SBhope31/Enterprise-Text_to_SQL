# Enterprise Text-to-SQL Intelligence Platform

A production-style Text-to-SQL system that converts plain-English business questions into validated, executable PostgreSQL queries. Built as a multi-agent pipeline on **LangGraph**, with **hybrid (dense + BM25) retrieval** over a Qdrant-backed schema, **AST-level SQL validation** via sqlglot, and a **self-correcting retry loop** that feeds error messages back to the LLM on failure.

The deployed demo runs on Render with Google Gemini's free tier; the same codebase runs unchanged against OpenAI by changing two env vars.

> *"How many customers do we have in each region?"* → SQL generated, validated, executed, results in 2 seconds.

## What it actually does

A `POST /ask` (or a click in Streamlit) walks the question through seven agents:

```
question → rewrite → schema retrieval (hybrid RAG) → SQL generation
                                                       │
                                                       ▼
                          ┌─── self-correct ◄───  validation (sqlglot AST + LIMIT enforcement)
                          │     (max 2 retries)         │
                          ▼                             ▼  (ok)
                    re-prompt with                  optimization (Postgres EXPLAIN)
                    failed SQL + error                  │
                                                        ▼
                                                    execution (read-only, time-bounded)
                                                        │
                                                        ▼
                                                    explanation → response
```

Every step is **traced**: the API and the Streamlit UI both surface a per-agent timeline so you can see exactly what fired, in what order, with what latency, and what it wrote into state.

## Key features

- **Hybrid retrieval over schema docs.** Dense vector search (Qdrant) fused with BM25 lexical search via **Reciprocal Rank Fusion**. Schema descriptions, column hints, business-glossary entries, and few-shot SQL examples are all embedded as separate documents so the relevant ones get pulled in based on the question.
- **AST-level SQL validation.** `sqlglot` parses the generated SQL; the validator blocks every non-SELECT statement type (INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/COPY/GRANT), rejects unknown tables/columns against the live SQLAlchemy schema, and auto-injects or clamps `LIMIT` so generated queries can't return millions of rows.
- **Self-correcting retry loop.** When validation fails or Postgres rejects the query, the orchestrator's LangGraph routes back to SQL generation with the error message appended to the prompt. Up to 2 retries before giving up. The retry edge is the reason LangGraph is here (rather than a flat for-loop).
- **Read-only, time-bounded execution.** Every query runs inside `SET TRANSACTION READ ONLY` with `statement_timeout`, fetches `max_rows + 1` to detect truncation, and converts non-JSON types (Decimal, date) before returning.
- **Provider-agnostic LLM.** The OpenAI SDK is the only client; `OPENAI_BASE_URL` lets it talk to OpenAI, Google Gemini, Groq, or anything else that speaks the OpenAI HTTP contract. The demo uses Gemini for free-tier deploy economics.
- **Evaluation harness included.** Golden-set + Spider benchmark runners, with retrieval (recall@k, MRR), SQL (exact-match, execution-accuracy, hallucination-rate), and latency metrics. An A/B harness (`scripts/run_ab_eval.py`) compares the LangGraph + self-correct pipeline against a flat baseline.

## Quickstart (local)

Prereqs: Python 3.11, Docker Desktop, a Gemini API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

```powershell
# 1. Clone and enter
git clone <repo-url> text-to-sql
cd text-to-sql

# 2. Virtualenv + deps
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# 3. .env — copy template and paste your Gemini key
copy .env.example .env
# edit .env: OPENAI_API_KEY=<your-gemini-key>

# 4. Boot Postgres + Qdrant + Redis
docker compose up -d

# 5. One-time data setup
venv\Scripts\python -m scripts.seed_database
venv\Scripts\python -m scripts.embed_schema

# 6. Run
venv\Scripts\streamlit run streamlit_app.py
# or the REST API:
# venv\Scripts\uvicorn app.main:app --reload
```

Streamlit opens at <http://localhost:8501>; FastAPI exposes Swagger UI at <http://localhost:8000/docs>.

## Try a question

In Streamlit, click any sample in the sidebar, or type your own. Some good ones for this dataset:

- *How many customers do we have in each region?*
- *Top 5 customers by revenue in the last 3 months*
- *What is the monthly revenue trend for the last 12 months?*
- *Average delivery time by carrier*
- *Payment success rate by method this month*

## Deployment (Render)

End-to-end deploy: Streamlit on Render's free plan, Postgres on Render's free managed plan, Qdrant on Qdrant Cloud's free tier, Gemini for the LLM.

**1. Create the external accounts (all free):**
- Gemini API key → [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- Qdrant Cloud 1GB cluster → [cloud.qdrant.io](https://cloud.qdrant.io) (after creation, go to **API Keys** → create one; copy both the cluster URL and the key)
- Render account → [render.com](https://render.com)

**2. Push this repo to GitHub.** `.env` is gitignored so local secrets stay local.

**3. Deploy with the Blueprint.** In Render: **New +** → **Blueprint** → connect this repo → **Apply**. Render reads `render.yaml` and provisions a managed Postgres + a Python web service running Streamlit. All Postgres env vars are auto-wired.

**4. Set the three secrets in the service's Environment tab:**
| Key | Value |
|---|---|
| `OPENAI_API_KEY` | Your Gemini API key |
| `QDRANT_URL` | Your Qdrant Cloud cluster URL (`https://...qdrant.io:6333`) |
| `QDRANT_API_KEY` | Your Qdrant Cloud API key |

**5. One-time data setup.** Open the service's **Shell** tab and run:
```bash
python -m scripts.seed_database     # creates tables + sample data
python -m scripts.embed_schema      # builds the Qdrant collection
```

**6. Open the service URL** from the Render dashboard.

### Notes
- **Cold start.** Render free web services sleep after 15 min idle; first wake takes ~30 s.
- **No Redis in prod.** `app/cache/redis_cache.py` detects this and silently disables the embedding cache. Not worth provisioning Redis for a demo.
- **Switching back to OpenAI.** Remove `OPENAI_BASE_URL`, set `OPENAI_CHAT_MODEL=gpt-4o-mini`, `OPENAI_EMBED_MODEL=text-embedding-3-small`, and re-run `embed_schema` (it drops + recreates the Qdrant collection at the new dim — OpenAI's `text-embedding-3-small` is 1536-dim, Gemini's `gemini-embedding-001` is 3072-dim).

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Web | FastAPI + Streamlit | FastAPI for the REST API, Streamlit for the demo UI. Streamlit imports the pipeline directly — no HTTP hop. |
| Agent orchestration | LangGraph | `StateGraph` with conditional edges — natural fit for the self-correct retry loop. |
| LLM client | `openai` SDK | OpenAI-compatible HTTP works with OpenAI, Gemini, Groq. Switch providers via `OPENAI_BASE_URL`. |
| Vector store | Qdrant | Fast ANN, has a payload filter — used by Spider eval to scope retrieval per database. |
| Lexical retrieval | `rank_bm25` | Pure Python BM25 over an in-memory corpus. Fused with dense via RRF. |
| SQL validation | `sqlglot` | AST parsing means we block destructive statements at the node level, not via regex. |
| App DB | PostgreSQL 16 | Real engine, with `EXPLAIN` used by the optimization agent. |
| Cache | Redis (optional) | Embedding cache. Falls back to no-op if Redis isn't reachable. |

## Evaluation

Two harnesses ship with the repo:

```powershell
# Golden-set eval against the bundled e-commerce DB
python -m scripts.run_eval --k 5 --out eval_report.json

# A/B compare: flat pipeline vs LangGraph + self-correct
python -m scripts.run_ab_eval

# Single deterministic test of the retry loop (forces a bad first SQL,
# verifies Gemini's second attempt recovers and executes)
python -m scripts.test_self_correct

# Optional: Spider benchmark (~1000 questions over ~200 SQLite DBs)
python -m scripts.download_spider  # prints download instructions
python -m scripts.embed_spider
python -m scripts.run_spider_eval --limit 100
```

`test_self_correct` is the proof that the LangGraph addition does real work: it deterministically forces a validation/execution failure and shows the loop firing and Gemini recovering on the retry.

### Spider benchmark results

Ran the Spider dev set against the deployed pipeline using `gemini-2.5-flash-lite` (Google's free tier). Sampled 110 questions over four daily batches (each capped at 20 questions to fit the free-tier daily quota); 57 ran end-to-end after quota errors. Results:

| Database | Execution accuracy | Sample |
|---|---|---|
| `concert_singer` | **86.4%** | 19/22 |
| `pets_1` | **45.0%** | 9/20 |
| `car_1` | **33.3%** | 5/15 |
| **Overall** | **57.9%** | **33/57** |

**Read of the result.** The pipeline architecture works correctly across all three databases — validation pass rate is 100% on the questions that completed, and the self-correct retry loop fires on hallucinated columns / execution errors and successfully recovers on a subset of them. The accuracy spread is **schema-difficulty-dependent**, not pipeline-dependent: easy single-table schemas land near state-of-the-art for small models; relational schemas with multi-table joins and ambiguous column names drop because `gemini-2.5-flash-lite` hallucinates columns more often. A larger model would close most of this gap with no code changes.

**Reproducing.** Each day's batch was produced with `python -m scripts.run_spider_eval --limit 20 --offset <N> --out spider_dN.json`, bumping `--offset` by 20 daily to ride out Gemini's 20-chat-request daily cap on the free tier. The raw per-question JSON files (`spider_50.json`, `spider_d2.json`, `spider_d3.json`, `spider_d4.json`) are gitignored but reproducible from any LLM provider that speaks the OpenAI HTTP contract.

## Project structure

```
text-to-sql/
├── streamlit_app.py              # Streamlit frontend (imports pipeline directly)
├── docker-compose.yml            # Postgres + Qdrant + Redis for local dev
├── render.yaml                   # Render deployment blueprint
├── DEPLOYMENT.md                 # Step-by-step Render deploy guide
├── app/
│   ├── main.py                   # FastAPI app entry
│   ├── config.py                 # Pydantic-settings env loader
│   ├── api/                      # FastAPI routes & schemas
│   ├── agents/                   # 7 pipeline agents + LangGraph orchestrator
│   │   ├── base.py               #   PipelineState, AgentTrace, Pipeline wrapper
│   │   ├── orchestrator.py       #   StateGraph with self-correct retry
│   │   ├── rewrite_agent.py
│   │   ├── schema_agent.py
│   │   ├── sql_agent.py
│   │   ├── validation_agent.py
│   │   ├── optimization_agent.py
│   │   ├── execution_agent.py
│   │   └── explanation_agent.py
│   ├── rag/                      # Hybrid retrieval
│   │   ├── embeddings.py         #   OpenAIEmbedder + Redis cache
│   │   ├── vector_store.py       #   Qdrant wrapper
│   │   ├── retriever.py          #   Dense + BM25 fusion via RRF
│   │   ├── query_rewriter.py     #   Pre-retrieval query expansion
│   │   └── knowledge.py          #   Business glossary + few-shot examples
│   ├── sql_generation/           # LLM-based SQL generator (dialect-aware)
│   ├── validation/               # sqlglot-based AST validator
│   ├── execution/                # SafeExecutor (read-only, time-bounded)
│   ├── db/                       # SQLAlchemy models + session
│   ├── cache/                    # Redis cache (graceful fallback)
│   ├── monitoring/               # Logging
│   └── eval/                     # Golden + Spider eval runners + metrics
├── scripts/
│   ├── seed_database.py          # Populate Postgres with sample data
│   ├── embed_schema.py           # Embed schema docs into Qdrant
│   ├── run_eval.py               # Golden-set evaluator
│   ├── run_ab_eval.py            # A/B compare flat vs LangGraph pipeline
│   ├── run_spider_eval.py        # Spider benchmark runner
│   ├── embed_spider.py
│   ├── download_spider.py
│   └── test_self_correct.py      # Deterministic retry-loop test vs real LLM
└── tests/
    ├── test_metrics.py
    └── test_validator.py
```

## License

MIT — see [LICENSE](LICENSE).
