from openai import OpenAI

from app.config import get_settings

REWRITE_SYSTEM = """You rewrite vague analytics questions into precise, search-friendly questions for a SQL retrieval system.

Rules:
- Preserve user intent. Do not invent metrics that were not implied.
- Resolve relative time references ("recently", "last quarter") into explicit windows.
- Expand abbreviations and ambiguous nouns into the likely business term.
- Output ONLY the rewritten question on a single line. No prefix, no quotes.
"""


class QueryRewriter:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self._model = settings.openai_chat_model

    def rewrite(self, query: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": query},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or query
