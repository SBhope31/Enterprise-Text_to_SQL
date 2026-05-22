import json
from dataclasses import dataclass

from openai import OpenAI

from app.config import get_settings
from app.sql_generation.prompts import build_system_prompt, build_user_prompt


@dataclass
class GeneratedSQL:
    sql: str
    explanation: str
    raw: str


class SQLGenerator:
    def __init__(self, dialect: str = "postgres") -> None:
        settings = get_settings()
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self._model = settings.openai_chat_model
        self._system_prompt = build_system_prompt(dialect)

    def generate(self, question: str, schema_context: str) -> GeneratedSQL:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": build_user_prompt(question, schema_context)},
            ],
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"sql": "", "explanation": "Model did not return valid JSON."}
        sql = (data.get("sql") or "").strip().rstrip(";")
        return GeneratedSQL(
            sql=sql,
            explanation=(data.get("explanation") or "").strip(),
            raw=raw,
        )
