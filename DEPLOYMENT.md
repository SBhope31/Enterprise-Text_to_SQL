# Deployment guide — Render

End-to-end deploy: Streamlit on Render's free plan, Postgres on Render's free
managed plan, Qdrant on Qdrant Cloud's free tier, Gemini for the LLM.

## 1. Create the external accounts (free)

- **Google AI Studio** → https://aistudio.google.com/apikey
  Generate a Gemini API key. Free tier is generous.
- **Qdrant Cloud** → https://cloud.qdrant.io
  Create a free 1GB cluster. Copy the cluster URL and create an API key.
- **Render** → https://render.com (Sign in with GitHub).

## 2. Push this repo to GitHub

```powershell
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<you>/text-to-sql.git
git push -u origin main
```

`.env` is gitignored, so your local secrets stay local.

## 3. Deploy with the Blueprint

In Render: **New +** → **Blueprint** → connect your GitHub repo → pick this
repo → **Apply**.

Render reads [render.yaml](render.yaml) and creates:
- A managed Postgres database (`textsql-db`).
- A Python web service (`text-to-sql`) running Streamlit.
- All Postgres env vars are auto-wired.

## 4. Set the three secrets

The Blueprint marks three env vars as `sync: false` — Render won't fill them.
In the service's **Environment** tab, set:

| Key | Value |
|---|---|
| `OPENAI_API_KEY`  | Your Gemini API key from step 1 |
| `QDRANT_URL`      | Your Qdrant Cloud cluster URL (`https://...qdrant.io:6333`) |
| `QDRANT_API_KEY`  | Your Qdrant Cloud API key |

Save → Render redeploys with the new env.

## 5. One-time data setup (Render Shell)

The service is live but Postgres is empty and Qdrant has no schema docs. Open
the service's **Shell** tab in Render and run:

```bash
python -m scripts.seed_database     # creates tables + sample data
python -m scripts.embed_schema      # builds Qdrant collection
```

Each takes a few seconds.

## 6. Open the app

The service URL is shown on the Render dashboard
(e.g. `https://text-to-sql.onrender.com`). Streamlit's UI loads there.

---

## Notes & gotchas

- **Cold start.** Render free web services sleep after 15 min idle. The first
  hit after sleep takes ~30s to wake. Subsequent hits are instant.
- **No Redis in prod.** `app/cache/redis_cache.py` detects the absence and
  silently disables caching. You pay a few extra cents/month in Gemini
  embedding calls; not worth provisioning Redis.
- **Switching back to OpenAI.** Remove `OPENAI_BASE_URL` (or set it to empty),
  change `OPENAI_CHAT_MODEL` to `gpt-4o-mini`, change `OPENAI_EMBED_MODEL` to
  `text-embedding-3-small`, set `OPENAI_API_KEY` to your OpenAI key, and
  re-run `python -m scripts.embed_schema` to rebuild the Qdrant collection at
  the new (1536) embedding dimension.
- **Embedding dimension.** Gemini's `gemini-embedding-001` is 3072-dim;
  OpenAI's `text-embedding-3-small` is 1536. The Qdrant collection is created
  at the embedder's dim on `scripts.embed_schema` run, so changing providers
  requires re-running that script (it drops + recreates the collection).
- **Build time.** First deploy installs the full `requirements.txt`. Several
  packages (`langchain*`, `deepeval`, `ragas`, `sentence-transformers`) are
  declared but not actually imported by runtime code; if Render's build times
  out, trim those from `requirements.txt`.
