"""Optional Redis-backed cache. Falls back to a no-op when Redis is unreachable."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import redis

from app.config import get_settings
from app.monitoring.logger import get_logger

log = get_logger(__name__)


def _hash_key(*parts: str) -> str:
    h = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()
    return h[:32]


class RedisCache:
    def __init__(self) -> None:
        settings = get_settings()
        try:
            self._client: redis.Redis | None = redis.Redis.from_url(
                settings.redis_url, decode_responses=False, socket_connect_timeout=1.5
            )
            self._client.ping()
            self._enabled = True
            log.info("Redis cache connected: %s", settings.redis_url)
        except Exception as e:  # pragma: no cover - depends on environment
            log.warning("Redis unavailable, caching disabled: %s", e)
            self._client = None
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get_json(self, namespace: str, *key_parts: str) -> Any | None:
        if not self._enabled or self._client is None:
            return None
        try:
            raw = self._client.get(f"{namespace}:{_hash_key(*key_parts)}")
            return json.loads(raw) if raw else None
        except Exception as e:  # pragma: no cover
            log.warning("Redis get failed: %s", e)
            return None

    def set_json(
        self, namespace: str, value: Any, *key_parts: str, ttl_seconds: int = 3600
    ) -> None:
        if not self._enabled or self._client is None:
            return
        try:
            self._client.setex(
                f"{namespace}:{_hash_key(*key_parts)}",
                ttl_seconds,
                json.dumps(value),
            )
        except Exception as e:  # pragma: no cover
            log.warning("Redis set failed: %s", e)


_singleton: RedisCache | None = None


def get_cache() -> RedisCache:
    global _singleton
    if _singleton is None:
        _singleton = RedisCache()
    return _singleton
