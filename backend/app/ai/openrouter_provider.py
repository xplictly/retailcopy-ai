"""OpenRouter AI provider (optional)."""
from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx

from app.ai.base import AIProvider
from app.ai.prompts import build_prompt
from app.core.config import get_settings
from app.schemas.schemas import GeneratedContent, GenerationSettings, ProductResponse

logger = logging.getLogger(__name__)
_settings = get_settings()


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"No JSON: {text[:200]}")


class OpenRouterProvider(AIProvider):
    def __init__(self):
        self._api_key = _settings.openrouter_api_key
        self._model = _settings.openrouter_model
        self._timeout = _settings.http_timeout_seconds
        self._max_retries = _settings.http_max_retries
        self._backoff_base = _settings.batch_retry_backoff_base

    @property
    def provider_name(self) -> str:
        return "openrouter"

    @property
    def model_id(self) -> str | None:
        return self._model

    async def is_available(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, "OPENROUTER_API_KEY is not configured."
        return True, f"OpenRouter configured. Model: {self._model}"

    async def generate(self, product: ProductResponse, settings: GenerationSettings) -> GeneratedContent:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured.")
        prompt = build_prompt(product, settings)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": "https://retailcopy.ai",
            "X-Title": "RetailCopy AI",
        }
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.7,
        }
        for attempt in range(1, self._max_retries + 2):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                if resp.status_code == 429:
                    if attempt <= self._max_retries:
                        await asyncio.sleep(self._backoff_base ** attempt)
                        continue
                    raise RuntimeError("OpenRouter rate limited.")
                resp.raise_for_status()
                data = resp.json()
                raw_text = data["choices"][0]["message"]["content"]
                parsed = _extract_json(raw_text)
                return self._validate(parsed)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt <= self._max_retries:
                    await asyncio.sleep(self._backoff_base ** attempt)
                else:
                    raise RuntimeError(f"OpenRouter network error: {exc}") from exc
        raise RuntimeError("OpenRouter: Exhausted retries.")

    def _validate(self, data: dict) -> GeneratedContent:
        for f in ["title", "short_description", "long_description",
                  "feature_bullets", "seo_title", "seo_meta_description", "keywords"]:
            if f not in data:
                raise ValueError(f"Missing field: {f}")
        return GeneratedContent(
            title=str(data["title"])[:80],
            short_description=str(data["short_description"]),
            long_description=str(data["long_description"]),
            feature_bullets=[str(b) for b in data.get("feature_bullets", [])[:8]],
            seo_title=str(data["seo_title"])[:70],
            seo_meta_description=str(data["seo_meta_description"])[:160],
            keywords=[str(k) for k in data.get("keywords", [])[:15]],
        )
