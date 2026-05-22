from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.cache.redis_cache import get_cache
from app.config import get_settings


class OpenAIEmbedder:
    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self._model = model or settings.openai_embed_model
        self._cache = get_cache()
        self._dim_cache: int | None = None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _embed_uncached(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in resp.data]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float] | None] = [None] * len(texts)
        miss_indices: list[int] = []
        miss_texts: list[str] = []
        for i, t in enumerate(texts):
            cached = self._cache.get_json("emb", self._model, t)
            if cached is not None:
                results[i] = cached
            else:
                miss_indices.append(i)
                miss_texts.append(t)
        if miss_texts:
            fresh = self._embed_uncached(miss_texts)
            for idx, vec, txt in zip(miss_indices, fresh, miss_texts):
                results[idx] = vec
                self._cache.set_json("emb", vec, self._model, txt, ttl_seconds=7 * 24 * 3600)
        return [r for r in results if r is not None]  # type: ignore[return-value]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @property
    def model(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        """Embedding vector dimension. Known mappings cover the common OpenAI
        and Gemini models; unknown models are probed via a single API call and
        the result cached."""
        if self._dim_cache is not None:
            return self._dim_cache
        m = self._model.lower()
        if "3-large" in m:
            self._dim_cache = 3072
        elif "3-small" in m or "ada-002" in m:
            self._dim_cache = 1536
        elif "gemini-embedding" in m:
            self._dim_cache = 3072
        elif "embedding-004" in m:
            self._dim_cache = 768
        else:
            self._dim_cache = len(self._embed_uncached(["dim probe"])[0])
        return self._dim_cache
