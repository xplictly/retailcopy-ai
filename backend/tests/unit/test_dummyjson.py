"""Unit tests: DummyJSON integration."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from app.integrations.dummyjson import (
    _normalize_product,
    fetch_all_products,
    fetch_categories,
    fetch_product_by_id,
)

# ── Sample Data ───────────────────────────────────────────────────────────────

SAMPLE_PRODUCT = {
    "id": 1,
    "title": "iPhone 9",
    "brand": "Apple",
    "category": "smartphones",
    "description": "An apple mobile which is nothing like apple.",
    "price": 549.99,
    "stock": 94,
    "sku": "RCH45Q1A",
    "weight": 0.5,
    "warrantyInformation": "1 year warranty",
    "shippingInformation": "Ships in 2-3 days",
    "availabilityStatus": "In Stock",
    "dimensions": {"width": 7.0, "height": 14.0, "depth": 0.8},
    "images": ["https://cdn.dummyjson.com/product-images/1/1.jpg"],
    "tags": ["smartphone", "apple"],
    "meta": {"barcode": "1234567890", "qrCode": "https://qr.dummyjson.com/1"},
}

SAMPLE_PAGE_1 = {
    "products": [SAMPLE_PRODUCT],
    "total": 3,
    "skip": 0,
    "limit": 1,
}

SAMPLE_PAGE_2 = {
    "products": [
        {**SAMPLE_PRODUCT, "id": 2, "title": "MacBook Pro", "price": 1999.99},
    ],
    "total": 3,
    "skip": 1,
    "limit": 1,
}

SAMPLE_PAGE_3 = {
    "products": [
        {**SAMPLE_PRODUCT, "id": 3, "title": "Samsung Galaxy", "brand": "Samsung", "price": 699.99},
    ],
    "total": 3,
    "skip": 2,
    "limit": 1,
}


class TestNormalization:
    def test_basic_normalization(self):
        product = _normalize_product(SAMPLE_PRODUCT)
        assert product.name == "iPhone 9"
        assert product.brand == "Apple"
        assert product.category == "smartphones"
        assert product.price == 549.99
        assert product.currency == "USD"
        assert product.external_id == "1"
        assert product.source_name == "dummyjson"
        assert product.is_synthetic is False

    def test_weight_normalization(self):
        product = _normalize_product(SAMPLE_PRODUCT)
        assert product.weight_kg == 0.5

    def test_dimensions_normalization(self):
        product = _normalize_product(SAMPLE_PRODUCT)
        assert product.dimensions_cm is not None
        assert "7.0" in product.dimensions_cm
        assert "14.0" in product.dimensions_cm

    def test_specifications_extraction(self):
        product = _normalize_product(SAMPLE_PRODUCT)
        assert product.specifications is not None
        assert "barcode" in product.specifications
        assert product.specifications["barcode"] == "1234567890"
        assert "warranty" in product.specifications

    def test_tags_as_features(self):
        product = _normalize_product(SAMPLE_PRODUCT)
        assert product.features is not None
        assert "smartphone" in product.features

    def test_image_url_extraction(self):
        product = _normalize_product(SAMPLE_PRODUCT)
        assert product.image_url == "https://cdn.dummyjson.com/product-images/1/1.jpg"

    def test_raw_source_preserved(self):
        product = _normalize_product(SAMPLE_PRODUCT)
        assert product.raw_source_data is not None
        assert product.raw_source_data["id"] == 1

    def test_missing_optional_fields(self):
        minimal = {"id": 99, "title": "Minimal Product"}
        product = _normalize_product(minimal)
        assert product.name == "Minimal Product"
        assert product.brand is None
        assert product.category is None
        assert product.price is None
        assert product.weight_kg is None
        assert product.dimensions_cm is None


class TestPagination:
    @pytest.mark.asyncio
    async def test_pagination_fetches_multiple_pages(self):
        """Verify real pagination logic — all pages are fetched."""
        call_count = [0]

        async def mock_fetch_page(client, base_url, limit, skip, retries, backoff):
            call_count[0] += 1
            if skip == 0:
                return SAMPLE_PAGE_1
            elif skip == 1:
                return SAMPLE_PAGE_2
            else:
                return SAMPLE_PAGE_3

        with patch("app.integrations.dummyjson._fetch_page", side_effect=mock_fetch_page):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                with patch("app.integrations.dummyjson._fetch_page", side_effect=mock_fetch_page):
                    products = await fetch_all_products(max_records=3, page_size=1)

        assert len(products) == 3
        names = {p.name for p in products}
        assert "iPhone 9" in names
        assert "MacBook Pro" in names
        assert "Samsung Galaxy" in names

    @pytest.mark.asyncio
    async def test_pagination_respects_max_records(self):
        """Should stop fetching once max_records is reached."""
        responses = [
            {"products": [{**SAMPLE_PRODUCT, "id": i} for i in range(10)], "total": 100},
            {"products": [{**SAMPLE_PRODUCT, "id": i} for i in range(10, 15)], "total": 100},
        ]
        call_count = [0]

        async def mock_fetch(client, base_url, limit, skip, retries, backoff):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(responses):
                return responses[idx]
            return {"products": [], "total": 100}

        with patch("app.integrations.dummyjson._fetch_page", side_effect=mock_fetch):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                with patch("app.integrations.dummyjson._fetch_page", side_effect=mock_fetch):
                    products = await fetch_all_products(max_records=12, page_size=10)

        assert len(products) <= 12

    @pytest.mark.asyncio
    async def test_empty_response_handling(self):
        async def mock_fetch(client, base_url, limit, skip, retries, backoff):
            return {"products": [], "total": 0}

        with patch("app.integrations.dummyjson._fetch_page", side_effect=mock_fetch):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                with patch("app.integrations.dummyjson._fetch_page", side_effect=mock_fetch):
                    products = await fetch_all_products(max_records=50, page_size=10)

        assert products == []


class TestImport50Products:
    @pytest.mark.asyncio
    async def test_import_at_least_50_distinct_products(self):
        """Integration acceptance: simulate fetching 50+ distinct products via pagination."""
        all_products = [
            {**SAMPLE_PRODUCT, "id": i, "title": f"Product {i}", "price": float(10 + i)}
            for i in range(1, 51)
        ]

        pages = []
        page_size = 10
        for i in range(0, 50, page_size):
            pages.append({
                "products": all_products[i:i+page_size],
                "total": 50,
                "skip": i,
                "limit": page_size,
            })

        page_idx = [0]

        async def mock_fetch(client, base_url, limit, skip, retries, backoff):
            idx = skip // page_size
            if idx < len(pages):
                return pages[idx]
            return {"products": [], "total": 50}

        with patch("app.integrations.dummyjson._fetch_page", side_effect=mock_fetch):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                with patch("app.integrations.dummyjson._fetch_page", side_effect=mock_fetch):
                    products = await fetch_all_products(max_records=50, page_size=10)

        assert len(products) == 50
        # Verify distinct external IDs
        external_ids = {p.external_id for p in products}
        assert len(external_ids) == 50, f"Expected 50 distinct products, got {len(external_ids)}"
