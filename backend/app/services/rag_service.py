"""Lightweight retrieval-augmented generation support.

This uses SQLite as the lexical retrieval index. Approved descriptions from the
same product category are retrieved as writing references; the target product
attributes remain the only source of factual claims.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import GeneratedDescription, Product
from app.schemas.schemas import ProductResponse


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


async def retrieve_rag_context(
    product: ProductResponse,
    db: AsyncSession,
    limit: int = 3,
) -> str:
    """Retrieve approved descriptions from the same category as lexical style references."""
    result = await db.execute(
        select(GeneratedDescription, Product)
        .join(Product, GeneratedDescription.product_id == Product.id)
        .where(GeneratedDescription.review_status == "approved")
        .order_by(GeneratedDescription.updated_at.desc())
        .limit(100)
    )

    target_category = (product.category or "").strip().lower()
    target_tokens = _tokens(
        " ".join(filter(None, [product.name, product.brand or "", product.category or "", product.original_description or ""]))
    )
    candidates: list[tuple[float, GeneratedDescription, Product]] = []

    for description, source_product in result.all():
        source_category = (source_product.category or "").strip().lower()
        source_text = " ".join(filter(None, [
            source_product.name,
            source_product.brand or "",
            source_product.category or "",
            source_product.original_description or "",
            description.title or "",
            description.short_description or "",
            description.long_description or "",
        ]))
        source_tokens = _tokens(source_text)

        category_match = 1.0 if target_category and source_category == target_category else 0.0
        overlap = len(target_tokens & source_tokens) / max(len(target_tokens), 1)
        score = category_match * 5.0 + overlap
        candidates.append((score, description, source_product))

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = [item for item in candidates if item[0] > 0][:limit]
    if not selected:
        return ""

    lines = ["Approved-category reference examples (style and structure only; never reuse their product facts):"]
    for _, description, source_product in selected:
        reference_text = description.short_description or description.long_description or ""
        lines.append(
            json.dumps({
                "reference_category": source_product.category,
                "reference_brand_voice": description.brand_voice,
                "reference_structure": reference_text[:700],
            }, ensure_ascii=False)
        )

    return "\n".join(lines)
