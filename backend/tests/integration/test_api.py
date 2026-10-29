"""API integration tests: products and imports."""
from __future__ import annotations

import io
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.integrations.file_import import (
    ImportError,
    generate_csv_template,
    generate_json_template,
    generate_synthetic_products,
    validate_and_parse_csv,
    validate_and_parse_json,
)
from app.schemas.schemas import ProductCreate


class TestCSVImport:
    def test_valid_csv_parses_correctly(self):
        csv_content = b"""name,brand,category,price,currency,color
Test Widget,WidgetCo,electronics,29.99,USD,Black
Another Product,BrandX,fashion,49.99,USD,Red
"""
        products, errors = validate_and_parse_csv(csv_content)
        assert len(products) == 2
        assert products[0].name == "Test Widget"
        assert products[0].brand == "WidgetCo"
        assert products[0].price == 29.99
        assert products[1].name == "Another Product"
        assert len(errors) == 0

    def test_missing_name_field_is_skipped(self):
        csv_content = b"""name,brand,price
,BrandX,19.99
Valid Product,BrandY,29.99
"""
        products, errors = validate_and_parse_csv(csv_content)
        assert len(products) == 1
        assert products[0].name == "Valid Product"
        assert len(errors) == 1
        assert "name" in errors[0].lower()

    def test_missing_required_column_raises(self):
        csv_content = b"""brand,category,price
BrandX,electronics,19.99
"""
        with pytest.raises(ImportError, match="name"):
            validate_and_parse_csv(csv_content)

    def test_malformed_csv_raises(self):
        with pytest.raises(ImportError):
            validate_and_parse_csv(b"\x00\x01\x02 not csv at all \xff\xfe")

    def test_pipe_delimited_features(self):
        csv_content = b"""name,features
Widget,Feature A|Feature B|Feature C
"""
        products, _ = validate_and_parse_csv(csv_content)
        assert products[0].features == ["Feature A", "Feature B", "Feature C"]

    def test_float_parsing_weight(self):
        csv_content = b"""name,weight_kg,price
Widget,1.5,29.99
"""
        products, _ = validate_and_parse_csv(csv_content)
        assert products[0].weight_kg == 1.5

    def test_invalid_float_skips_gracefully(self):
        csv_content = b"""name,price
Widget,not-a-number
"""
        products, errors = validate_and_parse_csv(csv_content)
        # Should parse but with None price
        assert len(products) == 1
        assert products[0].price is None

    def test_source_name_is_set(self):
        csv_content = b"""name,brand
Widget,Brand
"""
        products, _ = validate_and_parse_csv(csv_content)
        assert products[0].source_name == "csv_import"

    def test_csv_template_is_valid(self):
        template = generate_csv_template()
        products, errors = validate_and_parse_csv(template)
        assert len(products) >= 1
        assert len(errors) == 0

    def test_partial_row_errors_dont_stop_import(self):
        csv_content = b"""name,price
Good Product 1,19.99
,29.99
Good Product 2,39.99
"""
        products, errors = validate_and_parse_csv(csv_content)
        assert len(products) == 2
        assert len(errors) == 1


class TestJSONImport:
    def test_valid_json_array_parses(self):
        data = [
            {"name": "Widget A", "brand": "BrandX", "price": 29.99},
            {"name": "Widget B", "category": "tech"},
        ]
        products, errors = validate_and_parse_json(json.dumps(data).encode())
        assert len(products) == 2
        assert products[0].name == "Widget A"
        assert products[0].price == 29.99
        assert len(errors) == 0

    def test_json_products_wrapper(self):
        data = {"products": [{"name": "Widget A", "price": 19.99}]}
        products, errors = validate_and_parse_json(json.dumps(data).encode())
        assert len(products) == 1

    def test_malformed_json_raises(self):
        with pytest.raises(ImportError, match="JSON parse error"):
            validate_and_parse_json(b"{not valid json")

    def test_missing_name_skipped_with_error(self):
        data = [{"brand": "NoBrand", "price": 9.99}]
        products, errors = validate_and_parse_json(json.dumps(data).encode())
        assert len(products) == 0
        assert len(errors) == 1

    def test_features_list_preserved(self):
        data = [{"name": "Widget", "features": ["F1", "F2", "F3"]}]
        products, _ = validate_and_parse_json(json.dumps(data).encode())
        assert products[0].features == ["F1", "F2", "F3"]

    def test_json_template_is_valid(self):
        template = generate_json_template()
        products, errors = validate_and_parse_json(template)
        assert len(products) >= 1
        assert len(errors) == 0

    def test_non_array_non_dict_raises(self):
        with pytest.raises(ImportError):
            validate_and_parse_json(b'"just a string"')

    def test_raw_source_data_preserved(self):
        data = [{"name": "Widget", "custom_field": "value123"}]
        products, _ = validate_and_parse_json(json.dumps(data).encode())
        assert products[0].raw_source_data is not None
        assert products[0].raw_source_data.get("custom_field") == "value123"


class TestSyntheticDataset:
    def test_generates_requested_count(self):
        products = generate_synthetic_products(30)
        assert len(products) == 30

    def test_all_marked_as_synthetic(self):
        products = generate_synthetic_products(10)
        assert all(p.is_synthetic for p in products)

    def test_all_have_names(self):
        products = generate_synthetic_products(20)
        assert all(p.name for p in products)

    def test_multiple_categories(self):
        products = generate_synthetic_products(55)
        categories = {p.category for p in products if p.category}
        assert len(categories) >= 5, f"Expected 5+ categories, got {categories}"

    def test_unique_external_ids(self):
        products = generate_synthetic_products(50)
        ids = [p.external_id for p in products]
        assert len(ids) == len(set(ids))

    def test_source_name_is_synthetic(self):
        products = generate_synthetic_products(5)
        assert all(p.source_name == "synthetic" for p in products)

    def test_deterministic_output(self):
        """Same call twice should produce same results."""
        p1 = generate_synthetic_products(10)
        p2 = generate_synthetic_products(10)
        assert [p.name for p in p1] == [p.name for p in p2]


class TestAPIEndpoints:
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "provider" in data

    @pytest.mark.asyncio
    async def test_list_products_empty(self, client):
        resp = await client.get("/api/v1/products")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_csv_template_download(self, client):
        resp = await client.get("/api/v1/import/templates/csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert len(resp.content) > 0

    @pytest.mark.asyncio
    async def test_json_template_download(self, client):
        resp = await client.get("/api/v1/import/templates/json")
        assert resp.status_code == 200
        assert "json" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_synthetic_import(self, client):
        resp = await client.post("/api/v1/import/synthetic?count=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 10
        assert data["source"] == "synthetic"

    @pytest.mark.asyncio
    async def test_duplicate_synthetic_import_skipped(self, client):
        await client.post("/api/v1/import/synthetic?count=5")
        resp2 = await client.post("/api/v1/import/synthetic?count=5")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["skipped_duplicates"] == 5
        assert data["imported"] == 0

    @pytest.mark.asyncio
    async def test_list_products_after_import(self, client):
        await client.post("/api/v1/import/synthetic?count=15")
        resp = await client.get("/api/v1/products")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 15

    @pytest.mark.asyncio
    async def test_get_product_not_found(self, client):
        resp = await client.get(f"/api/v1/products/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_generate_description_demo_mode(self, client):
        # Import a product first
        import_resp = await client.post("/api/v1/import/synthetic?count=1")
        product_id = import_resp.json()["product_ids"][0]

        # Generate description
        resp = await client.post(
            f"/api/v1/products/{product_id}/generate",
            json={"product_id": product_id, "settings": {"brand_voice": "professional"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_demo"] is True
        assert data["provider"] == "demo"
        assert data["content"]["title"]
        assert data["quality_score"] is not None
        assert isinstance(data["factual_warnings"], list)

    @pytest.mark.asyncio
    async def test_csv_file_import(self, client):
        csv_data = b"name,brand,price\nTest Product,TestBrand,99.99\n"
        resp = await client.post(
            "/api/v1/import/csv",
            files={"file": ("test.csv", csv_data, "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] >= 1

    @pytest.mark.asyncio
    async def test_json_file_import(self, client):
        json_data = json.dumps([{"name": "JSON Widget", "price": 19.99}]).encode()
        resp = await client.post(
            "/api/v1/import/json",
            files={"file": ("test.json", json_data, "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] >= 1

    @pytest.mark.asyncio
    async def test_analytics_endpoint(self, client):
        resp = await client.get("/api/v1/analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_products" in data
        assert "total_generated" in data
        assert "active_provider" in data

    @pytest.mark.asyncio
    async def test_provider_status_endpoint(self, client):
        resp = await client.get("/api/v1/provider/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "demo"
        assert data["is_demo_mode"] is True
        assert data["is_operational"] is True

    @pytest.mark.asyncio
    async def test_review_decision_approved(self, client):
        import_resp = await client.post("/api/v1/import/synthetic?count=1")
        product_id = import_resp.json()["product_ids"][0]

        gen_resp = await client.post(
            f"/api/v1/products/{product_id}/generate",
            json={"product_id": product_id, "settings": {}},
        )
        desc_id = gen_resp.json()["id"]

        review_resp = await client.post(
            f"/api/v1/products/descriptions/{desc_id}/review",
            json={"status": "approved", "reviewer_notes": "Looks good!"},
        )
        assert review_resp.status_code == 200
        data = review_resp.json()
        assert data["review_status"] == "approved"

    @pytest.mark.asyncio
    async def test_categories_endpoint(self, client):
        await client.post("/api/v1/import/synthetic?count=20")
        resp = await client.get("/api/v1/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "category" in data[0]
        assert "count" in data[0]

    @pytest.mark.asyncio
    async def test_export_csv(self, client):
        import_resp = await client.post("/api/v1/import/synthetic?count=3")
        product_id = import_resp.json()["product_ids"][0]
        await client.post(
            f"/api/v1/products/{product_id}/generate",
            json={"product_id": product_id, "settings": {}},
        )
        resp = await client.post(
            "/api/v1/export",
            json={"format": "csv", "approved_only": False},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_export_json(self, client):
        import_resp = await client.post("/api/v1/import/synthetic?count=3")
        product_id = import_resp.json()["product_ids"][0]
        await client.post(
            f"/api/v1/products/{product_id}/generate",
            json={"product_id": product_id, "settings": {}},
        )
        resp = await client.post(
            "/api/v1/export",
            json={"format": "json", "approved_only": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "products" in data

    @pytest.mark.asyncio
    async def test_pagination_products(self, client):
        await client.post("/api/v1/import/synthetic?count=25")
        resp = await client.get("/api/v1/products?page=1&page_size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 10
        assert data["total"] == 25

    @pytest.mark.asyncio
    async def test_batch_submit_and_get(self, client):
        import_resp = await client.post("/api/v1/import/synthetic?count=3")
        product_ids = import_resp.json()["product_ids"]

        batch_resp = await client.post(
            "/api/v1/batch-jobs",
            json={"product_ids": product_ids, "settings": {}},
        )
        assert batch_resp.status_code == 202
        job_data = batch_resp.json()
        job_id = job_data["id"]
        assert job_data["total_items"] == 3

        # Get job status
        get_resp = await client.get(f"/api/v1/batch-jobs/{job_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == job_id
