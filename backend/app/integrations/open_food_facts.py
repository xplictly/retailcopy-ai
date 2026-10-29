"""Open Food Facts integration — optional second data source."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.schemas.schemas import ProductCreate

logger = logging.getLogger(__name__)
_settings = get_settings()

SOURCE_NAME = "open_food_facts"
_USER_AGENT = "RetailCopyAI/1.0 (hackathon-demo; contact@example.com)"


def _normalize_product(raw: dict[str, Any]) -> ProductCreate | None:
    """Normalize an Open Food Facts product to our schema."""
    product = raw.get("product", raw)  # Handle both /product/{barcode} and search results

    name = (
        product.get("product_name_en")
        or product.get("product_name")
        or product.get("abbreviated_product_name")
    )
    if not name:
        return None  # Skip products with no name

    barcode = product.get("_id") or product.get("code")
    brand = product.get("brands", "").split(",")[0].strip() or None
    category_raw = product.get("categories", "") or product.get("main_category_en", "")
    category = category_raw.split(",")[0].strip() or "food"

    ingredients = product.get("ingredients_text_en") or product.get("ingredients_text")
    quantity = product.get("quantity")

    # Nutrition info
    nutriments = product.get("nutriments", {})
    specs: dict[str, Any] = {}
    for key in ["energy-kcal_100g", "fat_100g", "carbohydrates_100g", "proteins_100g", "salt_100g"]:
        if key in nutriments:
            specs[key] = nutriments[key]
    if quantity:
        specs["quantity"] = quantity
    if ingredients:
        specs["ingredients"] = ingredients[:500]  # Truncate for storage

    image_url = (
        product.get("image_url")
        or product.get("image_front_url")
    )

    features = []
    if ingredients:
        features.append(f"Ingredients: {ingredients[:100]}")
    if quantity:
        features.append(f"Quantity: {quantity}")
    nutriscore = product.get("nutriscore_grade") or product.get("nutrition_grade_fr")
    if nutriscore:
        features.append(f"Nutri-Score: {nutriscore.upper()}")

    original_description = ingredients or product.get("generic_name", "")

    return ProductCreate(
        source_name=SOURCE_NAME,
        external_id=barcode,
        name=name[:512],
        brand=brand,
        category=category[:256],
        original_description=original_description[:2000] if original_description else None,
        features=features[:6] if features else None,
        specifications=specs or None,
        image_url=image_url,
        raw_source_data={k: v for k, v in product.items() if not isinstance(v, (dict, list)) or k in ("nutriments",)},
        is_synthetic=False,
    )


async def search_products(
    query: str = "coffee",
    page: int = 1,
    page_size: int = 20,
) -> list[ProductCreate]:
    """Search Open Food Facts for products matching a query."""
    base_url = _settings.open_food_facts_base_url
    params = {
        "search_terms": query,
        "json": "1",
        "page": page,
        "page_size": page_size,
        "fields": "code,product_name,product_name_en,brands,categories,ingredients_text_en,quantity,nutriments,image_url,nutriscore_grade",
    }
    headers = {"User-Agent": _USER_AGENT}
    results: list[ProductCreate] = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{base_url}/cgi/search.pl",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            for raw in data.get("products", []):
                try:
                    p = _normalize_product(raw)
                    if p:
                        results.append(p)
                except Exception as exc:
                    logger.debug("OFF normalize error: %s", exc)
    except httpx.TimeoutException:
        logger.warning("Open Food Facts search timed out.")
    except Exception as exc:
        logger.error("Open Food Facts search error: %s", exc)
    return results


async def fetch_product_by_barcode(barcode: str) -> ProductCreate | None:
    """Fetch a single product by barcode."""
    base_url = _settings.open_food_facts_base_url
    headers = {"User-Agent": _USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{base_url}/api/v0/product/{barcode}.json",
                headers=headers,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == 0:
                return None
            return _normalize_product(data)
    except Exception as exc:
        logger.error("OFF barcode fetch error: %s", exc)
        return None


async def fetch_category_products(
    category: str = "beverages",
    max_records: int = 50,
    page_size: int = 20,
) -> list[ProductCreate]:
    """Fetch products from Open Food Facts by category."""
    base_url = _settings.open_food_facts_base_url
    headers = {"User-Agent": _USER_AGENT}
    results: list[ProductCreate] = []
    page = 1

    async with httpx.AsyncClient(timeout=30) as client:
        while len(results) < max_records:
            try:
                resp = await client.get(
                    f"{base_url}/category/{category}/{page}.json",
                    headers=headers,
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                products = data.get("products", [])
                if not products:
                    break
                for raw in products:
                    try:
                        p = _normalize_product(raw)
                        if p:
                            results.append(p)
                    except Exception:
                        pass
                page += 1
                await asyncio.sleep(0.5)  # Respect rate limits
            except Exception as exc:
                logger.error("OFF category fetch error page %d: %s", page, exc)
                break

    return results[:max_records]
