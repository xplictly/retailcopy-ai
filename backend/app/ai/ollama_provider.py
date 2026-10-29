"""Ollama local provider — optional, detection-first."""
from __future__ import annotations

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


class OllamaProvider(AIProvider):
    def __init__(self):
        self._base_url = _settings.ollama_base_url.rstrip("/")
        self._model = _settings.ollama_model
        self._timeout = _settings.http_timeout_seconds * 2  # Local models can be slow

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_id(self) -> str | None:
        return self._model

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    async def is_available(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code != 200:
                    return False, f"Ollama returned HTTP {resp.status_code}."
                models = resp.json().get("models", [])
                model_names = [m["name"] for m in models]
                if not model_names:
                    return False, "Ollama is running but no models are installed."
                if self._model and not any(self._model in m for m in model_names):
                    return False, (
                        f"Model '{self._model}' not found in Ollama. "
                        f"Available: {', '.join(model_names[:5])}"
                    )
                # Quick inference test
                test_resp = await client.post(
                    f"{self._base_url}/api/generate",
                    json={"model": self._model, "prompt": "Say OK", "stream": False},
                    timeout=30,
                )
                if test_resp.status_code == 200:
                    return True, f"Ollama operational. Model: {self._model}. Available: {model_names}"
                return False, f"Ollama inference test failed: HTTP {test_resp.status_code}"
        except httpx.ConnectError:
            return False, f"Ollama not reachable at {self._base_url}. Is it running?"
        except Exception as exc:
            return False, f"Ollama error: {exc}"

    async def generate(self, product: ProductResponse, settings: GenerationSettings) -> GeneratedContent:
        prompt = build_prompt(product, settings)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/api/generate",
                json={"model": self._model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            data = resp.json()
            raw_text = data.get("response", "")
            parsed = _extract_json(raw_text)
            return self._validate(parsed)

    def _validate(self, data: dict) -> GeneratedContent:
        for f in ["title", "short_description", "long_description",
                  "feature_bullets", "seo_title", "seo_meta_description", "keywords"]:
            if f not in data:
                raise ValueError(f"Missing: {f}")
        return GeneratedContent(
            title=str(data["title"])[:80],
            short_description=str(data["short_description"]),
            long_description=str(data["long_description"]),
            feature_bullets=[str(b) for b in data.get("feature_bullets", [])[:8]],
            seo_title=str(data["seo_title"])[:70],
            seo_meta_description=str(data["seo_meta_description"])[:160],
            keywords=[str(k) for k in data.get("keywords", [])[:15]],
        )
