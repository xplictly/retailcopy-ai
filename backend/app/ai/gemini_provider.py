"""Gemini AI provider — primary hosted provider."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx

from app.ai.base import AIProvider
from app.ai.prompts import build_prompt
from app.core.config import get_settings
from app.schemas.schemas import GeneratedContent, GenerationSettings, ProductResponse

logger = logging.getLogger(__name__)
_settings = get_settings()

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from LLM response."""
    # Try direct parse
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    # Extract from markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # Find first {...}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"No JSON found in LLM response: {text[:200]}")


class GeminiProvider(AIProvider):
    """Google Gemini provider using direct REST API with HTTPX."""

    def __init__(self):
        self._api_key = _settings.gemini_api_key
        self._model = _settings.gemini_model or "gemini-1.5-flash"
        self._timeout = _settings.http_timeout_seconds
        self._max_retries = _settings.http_max_retries
        self._backoff_base = _settings.batch_retry_backoff_base

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_id(self) -> str | None:
        return self._model

    async def is_available(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, "GEMINI_API_KEY is not configured."
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_GEMINI_API_BASE}/models",
                    params={"key": self._api_key},
                )
                if resp.status_code == 200:
                    return True, f"Gemini operational. Model: {self._model}"
                elif resp.status_code == 401:
                    return False, "Gemini: Invalid API key (401)."
                elif resp.status_code == 403:
                    return False, "Gemini: API key lacks permission (403)."
                else:
                    return False, f"Gemini returned HTTP {resp.status_code}."
        except httpx.TimeoutException:
            return False, "Gemini: Connection timed out."
        except Exception as exc:
            return False, f"Gemini: {exc}"

    async def generate(
        self,
        product: ProductResponse,
        settings: GenerationSettings,
    ) -> GeneratedContent:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        prompt = build_prompt(product, settings)
        url = f"{_GEMINI_API_BASE}/models/{self._model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        }

        for attempt in range(1, self._max_retries + 2):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, json=payload, params={"key": self._api_key})

                if resp.status_code == 429:
                    if attempt <= self._max_retries:
                        wait = self._backoff_base ** attempt
                        logger.warning("Gemini rate limited, waiting %.1fs", wait)
                        await asyncio.sleep(wait)
                        continue
                    raise RuntimeError("Gemini: Rate limit exceeded after retries.")

                if resp.status_code == 401:
                    raise RuntimeError("Gemini: Invalid API key.")
                if resp.status_code == 403:
                    raise RuntimeError("Gemini: API key lacks permission or quota exhausted.")

                resp.raise_for_status()
                data = resp.json()

                # Extract text from Gemini response structure
                candidates = data.get("candidates", [])
                if not candidates:
                    raise ValueError("Gemini returned no candidates.")

                content_parts = candidates[0].get("content", {}).get("parts", [])
                if not content_parts:
                    raise ValueError("Gemini candidate has no content parts.")

                raw_text = content_parts[0].get("text", "")
                parsed = _extract_json(raw_text)
                return self._validate_content(parsed)

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt <= self._max_retries:
                    wait = self._backoff_base ** attempt
                    logger.warning("Gemini network error attempt %d: %s. Retrying in %.1fs", attempt, exc, wait)
                    await asyncio.sleep(wait)
                else:
                    raise RuntimeError(f"Gemini: Network error after {attempt} attempts: {exc}") from exc
            except (json.JSONDecodeError, ValueError) as exc:
                raise RuntimeError(f"Gemini: Failed to parse response: {exc}") from exc

        raise RuntimeError("Gemini: Exhausted all retry attempts.")

    def _validate_content(self, data: dict) -> GeneratedContent:
        required = ["title", "short_description", "long_description",
                    "feature_bullets", "seo_title", "seo_meta_description", "keywords"]
        for field in required:
            if field not in data:
                raise ValueError(f"Gemini response missing field: {field}")

        return GeneratedContent(
            title=str(data["title"])[:80],
            short_description=str(data["short_description"]),
            long_description=str(data["long_description"]),
            feature_bullets=[str(b) for b in data.get("feature_bullets", [])[:8]],
            seo_title=str(data["seo_title"])[:70],
            seo_meta_description=str(data["seo_meta_description"])[:160],
            keywords=[str(k) for k in data.get("keywords", [])[:15]],
        )
