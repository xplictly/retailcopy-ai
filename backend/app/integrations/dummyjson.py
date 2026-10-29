"""DummyJSON product catalog integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.schemas.schemas import ProductCreate

logger = logging.getLogger(__name__)
_settings = get_settings()

SOURCE_NAME = "dummyjson"


def _normalize_product(raw: dict[str, Any]) -> ProductCreate:
    """Normalize a DummyJSON product object to our canonical schema."""
    dimensions_raw = raw.get("dimensions", {})
    dimensions_cm: str | None = None
    if isinstance(dimensions_raw, dict):
        w = dimensions_raw.get("width")
        h = dimensions_raw.get("height")
        d = dimensions_raw.get("depth")
        if any(v is not None for v in [w, h, d]):
            dimensions_cm = f"{w}W x {h}H x {d}D cm"

    # DummyJSON weight is in kg
    weight_raw = raw.get("weight")
    weight_kg: float | None = None
    if weight_raw is not None:
        try:
            weight_kg = float(weight_raw)
        except (ValueError, TypeError):
            pass

    # Features from reviews or tags
    tags = raw.get("tags", []) or []
    features = tags[:6] if tags else None

    # Specifications from meta
    meta = raw.get("meta", {}) or {}
    specs: dict[str, Any] = {}
    if "barcode" in meta:
        specs["barcode"] = meta["barcode"]
    if "qrCode" in meta:
        specs["qr_code"] = meta["qrCode"]
    if raw.get("stock") is not None:
        specs["stock"] = raw["stock"]
    if raw.get("sku"):
        specs["sku"] = raw["sku"]
    if raw.get("warrantyInformation"):
        specs["warranty"] = raw["warrantyInformation"]
    if raw.get("shippingInformation"):
        specs["shipping"] = raw["shippingInformation"]
    if raw.get("availabilityStatus"):
        specs["availability"] = raw["availabilityStatus"]

    return ProductCreate(
        source_name=SOURCE_NAME,
        external_id=str(raw["id"]),
        name=raw.get("title", "Unknown Product"),
        brand=raw.get("brand"),
        category=raw.get("category"),
        original_description=raw.get("description"),
        features=features,
        specifications=specs or None,
        weight_kg=weight_kg,
        dimensions_cm=dimensions_cm,
        price=float(raw["price"]) if raw.get("price") is not None else None,
        currency="USD",
        quantity=int(raw["stock"]) if isinstance(raw.get("stock"), (int, float)) else None,
        target_keywords=tags[:5] if tags else None,
        image_url=(raw.get("images", [None]) or [None])[0],
        raw_source_data=raw,
        is_synthetic=False,
    )


async def _fetch_page(
    client: httpx.AsyncClient,
    base_url: str,
    limit: int,
    skip: int,
    retries: int,
    backoff: float,
) -> dict[str, Any]:
    url = f"{base_url}/products"
    params = {"limit": limit, "skip": skip, "select": "id,title,brand,category,description,price,images,tags,weight,dimensions,meta,stock,sku,warrantyInformation,shippingInformation,availabilityStatus"}
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, params=params, timeout=_settings.http_timeout_seconds)
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if attempt < retries:
                wait = backoff ** (attempt + 1)
                logger.warning("DummyJSON fetch attempt %d failed: %s. Retrying in %.1fs", attempt + 1, exc, wait)
                await asyncio.sleep(wait)
            else:
                raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500 and attempt < retries:
                await asyncio.sleep(backoff ** (attempt + 1))
            else:
                raise
    return {}


async def fetch_all_products(
    max_records: int | None = None,
    page_size: int | None = None,
) -> list[ProductCreate]:
    """Fetch all products from DummyJSON using paginated requests."""
    limit = min(page_size or _settings.import_page_size, 100)
    max_rec = max_records or _settings.import_max_records
    retries = _settings.http_max_retries
    backoff = _settings.batch_retry_backoff_base
    base_url = _settings.dummyjson_base_url

    products: list[ProductCreate] = []
    skip = 0

    async with httpx.AsyncClient(timeout=_settings.http_timeout_seconds) as client:
        # First request to get total
        data = await _fetch_page(client, base_url, limit, 0, retries, backoff)
        total = data.get("total", 0)
        fetched = data.get("products", [])
        products.extend(_normalize_product(p) for p in fetched)
        skip = len(fetched)

        logger.info("DummyJSON: total=%d, fetched first page=%d", total, len(fetched))

        while skip < min(total, max_rec) and len(products) < max_rec:
            remaining = min(max_rec - len(products), limit)
            data = await _fetch_page(client, base_url, remaining, skip, retries, backoff)
            page = data.get("products", [])
            if not page:
                break
            products.extend(_normalize_product(p) for p in page)
            skip += len(page)
            logger.info("DummyJSON: fetched %d products so far (skip=%d)", len(products), skip)

    logger.info("DummyJSON: total fetched=%d", len(products))
    return products[:max_rec]


async def fetch_product_by_id(product_id: int) -> ProductCreate | None:
    """Fetch a single product by external ID."""
    base_url = _settings.dummyjson_base_url
    try:
        async with httpx.AsyncClient(timeout=_settings.http_timeout_seconds) as client:
            resp = await client.get(f"{base_url}/products/{product_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return _normalize_product(resp.json())
    except Exception as exc:
        logger.error("DummyJSON fetch product %d failed: %s", product_id, exc)
        return None


async def fetch_categories() -> list[str]:
    """Fetch available product categories."""
    base_url = _settings.dummyjson_base_url
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base_url}/products/category-list")
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.error("DummyJSON categories fetch failed: %s", exc)
        return []
