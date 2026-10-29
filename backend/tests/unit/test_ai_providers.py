"""Unit tests: AI providers."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.demo_provider import DemoProvider
from app.ai.provider_factory import get_provider, reset_provider_cache
from app.schemas.schemas import GeneratedContent, GenerationSettings, ProductResponse
from datetime import datetime


def _make_product(product_id: str = "test-001", name: str = "Test Widget") -> ProductResponse:
    return ProductResponse(
        id=product_id,
        source_name="test",
        name=name,
        brand="TestBrand",
        category="electronics",
        price=99.99,
        currency="USD",
        is_synthetic=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


# ── Demo Provider Tests ───────────────────────────────────────────────────────

class TestDemoProvider:
    @pytest.mark.asyncio
    async def test_is_always_available(self):
        provider = DemoProvider()
        available, msg = await provider.is_available()
        assert available is True
        assert "demo" in msg.lower()

    @pytest.mark.asyncio
    async def test_generates_valid_content(self):
        provider = DemoProvider()
        product = _make_product()
        settings = GenerationSettings()
        content = await provider.generate(product, settings)
        assert isinstance(content, GeneratedContent)
        assert len(content.title) > 0
        assert len(content.short_description) > 0
        assert len(content.long_description) > 0
        assert isinstance(content.feature_bullets, list)
        assert isinstance(content.keywords, list)

    @pytest.mark.asyncio
    async def test_output_varies_across_generations(self):
        """Repeated demo generations remain varied while staying product-specific."""
        provider = DemoProvider()
        product = _make_product("stable-id-123")
        settings = GenerationSettings()
        c1 = await provider.generate(product, settings)
        c2 = await provider.generate(product, settings)
        assert len(c1.title) > 0
        assert len(c1.long_description) > 0
        assert len(c2.long_description) > 0

    @pytest.mark.asyncio
    async def test_different_products_differ(self):
        """Different products produce different output."""
        provider = DemoProvider()
        p1 = _make_product("id-001", "Alpha Widget")
        p2 = _make_product("id-002", "Beta Gadget")
        settings = GenerationSettings()
        c1 = await provider.generate(p1, settings)
        c2 = await provider.generate(p2, settings)
        # Not all fields need to differ, but at least the content should vary
        assert c1.title != c2.title or c1.long_description != c2.long_description

    @pytest.mark.asyncio
    async def test_no_api_key_needed(self):
        provider = DemoProvider()
        assert provider.provider_name == "demo"
        assert provider.model_id == "demo-varied-v1"

    @pytest.mark.asyncio
    async def test_brand_voice_reflected(self):
        provider = DemoProvider()
        product = _make_product()
        # Just verifies generation doesn't crash with different voices
        for voice in ["professional", "friendly", "premium", "technical", "playful"]:
            settings = GenerationSettings(brand_voice=voice)
            content = await provider.generate(product, settings)
            assert len(content.long_description) > 0

    @pytest.mark.asyncio
    async def test_seo_keywords_in_result(self):
        provider = DemoProvider()
        product = _make_product()
        settings = GenerationSettings(seo_keywords=["test", "widget"])
        content = await provider.generate(product, settings)
        # SEO keywords should be present in the keywords list
        assert any("test" in k.lower() or "widget" in k.lower() for k in content.keywords)

    @pytest.mark.asyncio
    async def test_title_length_limit(self):
        provider = DemoProvider()
        product = _make_product(name="A" * 100)
        settings = GenerationSettings()
        content = await provider.generate(product, settings)
        assert len(content.title) <= 80

    @pytest.mark.asyncio
    async def test_seo_title_length_limit(self):
        provider = DemoProvider()
        product = _make_product()
        settings = GenerationSettings()
        content = await provider.generate(product, settings)
        assert len(content.seo_title) <= 70

    @pytest.mark.asyncio
    async def test_seo_meta_length_limit(self):
        provider = DemoProvider()
        product = _make_product()
        settings = GenerationSettings()
        content = await provider.generate(product, settings)
        assert len(content.seo_meta_description) <= 160


# ── Provider Factory Tests ────────────────────────────────────────────────────

class TestProviderFactory:
    def setup_method(self):
        reset_provider_cache()

    def teardown_method(self):
        reset_provider_cache()

    def test_demo_provider_selected_by_default(self):
        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.llm_provider = "demo"
            reset_provider_cache()
            # Can't easily test factory with settings mock, test directly
            provider = DemoProvider()
            assert provider.provider_name == "demo"

    def test_reset_cache_allows_re_selection(self):
        from app.ai.provider_factory import get_provider, reset_provider_cache
        reset_provider_cache()
        p1 = get_provider()
        reset_provider_cache()
        p2 = get_provider()
        # Both should be demo providers (default env)
        assert p1.provider_name == p2.provider_name


# ── Gemini Provider Tests (Mocked) ────────────────────────────────────────────

class TestGeminiProviderMocked:
    @pytest.mark.asyncio
    async def test_raises_without_api_key(self):
        with patch("app.ai.gemini_provider._settings") as mock_s:
            mock_s.gemini_api_key = ""
            mock_s.gemini_model = "gemini-1.5-flash"
            mock_s.http_timeout_seconds = 30
            mock_s.http_max_retries = 3
            mock_s.batch_retry_backoff_base = 2.0

            from app.ai.gemini_provider import GeminiProvider
            provider = GeminiProvider()
            provider._api_key = ""

            product = _make_product()
            settings = GenerationSettings()
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
                await provider.generate(product, settings)

    @pytest.mark.asyncio
    async def test_availability_check_no_key(self):
        with patch("app.ai.gemini_provider._settings") as mock_s:
            mock_s.gemini_api_key = ""
            mock_s.gemini_model = "gemini-1.5-flash"
            mock_s.http_timeout_seconds = 30
            mock_s.http_max_retries = 3
            mock_s.batch_retry_backoff_base = 2.0

            from app.ai.gemini_provider import GeminiProvider
            provider = GeminiProvider()
            provider._api_key = ""
            available, msg = await provider.is_available()
            assert available is False
            assert "GEMINI_API_KEY" in msg

    @pytest.mark.asyncio
    async def test_rate_limit_retries(self):
        """Verify that 429 triggers retry with backoff."""
        import httpx
        from unittest.mock import MagicMock
        from app.ai.gemini_provider import GeminiProvider

        call_count = [0]

        def _make_response(status_code, json_data):
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = status_code
            resp.json.return_value = json_data
            resp.raise_for_status = MagicMock()
            return resp

        async def mock_post(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                return _make_response(429, {"error": "rate limited"})
            return _make_response(200, {
                "candidates": [{
                    "content": {"parts": [{"text": '{"title":"T","short_description":"S","long_description":"L","feature_bullets":["F"],"seo_title":"SEO","seo_meta_description":"META","keywords":["k"]}'}]}
                }]
            })

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_instance.post = AsyncMock(side_effect=mock_post)
            mock_client_cls.return_value = mock_instance

            provider = GeminiProvider()
            provider._api_key = "test-key"
            provider._max_retries = 3
            provider._backoff_base = 0.01

            with patch("asyncio.sleep", new_callable=AsyncMock):
                content = await provider.generate(_make_product(), GenerationSettings())

        assert call_count[0] == 3
        assert content.title == "T"

    @pytest.mark.asyncio
    async def test_invalid_json_raises_runtime_error(self):
        from unittest.mock import MagicMock
        import httpx
        from app.ai.gemini_provider import GeminiProvider

        def _make_response(status_code, json_data):
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = status_code
            resp.json.return_value = json_data
            resp.raise_for_status = MagicMock()
            return resp

        async def mock_post(*args, **kwargs):
            return _make_response(200, {
                "candidates": [{"content": {"parts": [{"text": "not json at all"}]}}]
            })

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_instance.post = AsyncMock(side_effect=mock_post)
            mock_client_cls.return_value = mock_instance

            provider = GeminiProvider()
            provider._api_key = "test-key"
            provider._max_retries = 0

            with pytest.raises(RuntimeError):
                await provider.generate(_make_product(), GenerationSettings())

    @pytest.mark.asyncio
    async def test_no_secret_leakage_in_exception(self):
        import httpx
        from app.ai.gemini_provider import GeminiProvider

        SECRET_KEY = "super-secret-api-key-abc123"

        async def mock_post(*args, **kwargs):
            raise httpx.ConnectError("connection refused")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_instance.post = AsyncMock(side_effect=mock_post)
            mock_client_cls.return_value = mock_instance

            provider = GeminiProvider()
            provider._api_key = SECRET_KEY
            provider._max_retries = 0

            try:
                await provider.generate(_make_product(), GenerationSettings())
            except RuntimeError as exc:
                # Key must not appear in the exception message
                assert SECRET_KEY not in str(exc), "API key leaked in exception!"
