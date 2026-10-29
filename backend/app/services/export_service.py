"""Export service — CSV and JSON exports with all content fields."""
from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import GeneratedDescription, Product

logger = logging.getLogger(__name__)


async def export_products(
    db: AsyncSession,
    approved_only: bool = False,
    product_ids: list[str] | None = None,
    search: str | None = None,
    category: str | None = None,
    format: str = "csv",
) -> bytes:
    """Export generated descriptions with product data."""

    # Build query
    query = (
        select(GeneratedDescription, Product)
        .join(Product, GeneratedDescription.product_id == Product.id)
        .order_by(GeneratedDescription.created_at.desc())
    )

    if approved_only:
        query = query.where(GeneratedDescription.review_status == "approved")

    if product_ids:
        query = query.where(Product.id.in_(product_ids))

    if search and search.strip():
        groups: list[Any] = []
        for term in search.strip().lower().split():
            aliases = {term.replace("_", " ").replace("-", " ")}
            if term.endswith("s"):
                aliases.add(term[:-1])
            term_conditions = []
            for alias in sorted(aliases):
                like = f"%{alias}%"
                term_conditions.extend([
                    Product.name.ilike(like),
                    Product.brand.ilike(like),
                    Product.category.ilike(like),
                ])
            groups.append(or_(*term_conditions))
        if groups:
            query = query.where(and_(*groups))

    if category and category.strip():
        query = query.where(Product.category == category.strip())

    result = await db.execute(query)
    rows = result.all()

    if not rows:
        if format == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["No data to export"])
            return buf.getvalue().encode()
        return json.dumps({"products": [], "count": 0}).encode()

    records = []
    seen_product_desc: set[str] = set()  # Keep latest version per product

    for desc, product in rows:
        key = f"{product.id}:{desc.version}"
        if key in seen_product_desc:
            continue
        # Only keep the latest version per product
        p_key = product.id
        if p_key in seen_product_desc:
            continue
        seen_product_desc.add(p_key)

        content = desc.edited_content or {}
        record = {
            "product_id": product.id,
            "product_name": product.name,
            "brand": product.brand or "",
            "category": product.category or "",
            "source_name": product.source_name,
            "external_id": product.external_id or "",
            "price": product.price or "",
            "quantity": product.quantity if product.quantity is not None else "",
            "currency": product.currency,
            "original_description": product.original_description or "",
            "is_synthetic": product.is_synthetic,
            # Generated content
            "description_id": desc.id,
            "version": desc.version,
            "provider": desc.provider,
            "model_id": desc.model_id or "",
            "is_demo": desc.is_demo,
            "generated_title": content.get("title", desc.title) or "",
            "generated_short_description": content.get("short_description", desc.short_description) or "",
            "generated_long_description": content.get("long_description", desc.long_description) or "",
            "generated_feature_bullets": " | ".join(content.get("feature_bullets", desc.feature_bullets or [])),
            "seo_title": content.get("seo_title", desc.seo_title) or "",
            "seo_meta_description": content.get("seo_meta_description", desc.seo_meta_description) or "",
            "keywords": " | ".join(content.get("keywords", desc.keywords or [])),
            # Quality
            "quality_score": desc.quality_score or "",
            "factual_warning_count": desc.factual_warning_count,
            # Review
            "review_status": desc.review_status,
            "reviewer_notes": desc.reviewer_notes or "",
            "reviewed_by": desc.reviewed_by or "",
            "reviewed_at": str(desc.reviewed_at) if desc.reviewed_at else "",
            "generated_at": str(desc.created_at),
        }
        records.append(record)

    if format == "csv":
        if not records:
            return b""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(records[0].keys()), quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for record in records:
            writer.writerow(record)
        return buf.getvalue().encode("utf-8-sig")  # UTF-8 BOM for Excel compatibility

    else:  # JSON
        return json.dumps({
            "export_meta": {
                "approved_only": approved_only,
                "count": len(records),
            },
            "products": records,
        }, indent=2, default=str).encode()
