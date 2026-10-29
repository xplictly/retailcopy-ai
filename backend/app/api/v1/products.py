"""Products API router."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.models import GeneratedDescription, Product
from app.schemas.schemas import (
    GenerationRequest,
    GenerationResult,
    ProductListResponse,
    ProductResponse,
    ReviewDecision,
    BulkReviewDecision,
)
from app.services import product_service
from app.services.generation_service import generate_description

router = APIRouter(prefix="/products", tags=["products"])
logger = logging.getLogger(__name__)

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/review/queue")
async def get_review_queue(db: DB, limit: int = Query(default=50, ge=1, le=100)):
    """Return review cards in one query without the product-by-product N+1 cost."""
    result = await db.execute(
        select(GeneratedDescription, Product)
        .join(Product, GeneratedDescription.product_id == Product.id)
        .order_by(GeneratedDescription.created_at.desc())
        .limit(limit)
    )
    items = []
    for description, product in result.all():
        items.append({
            "product": {
                "id": product.id,
                "name": product.name,
                "brand": product.brand,
                "category": product.category,
                "source_name": product.source_name,
                "price": product.price,
                "quantity": product.quantity,
                "currency": product.currency,
                "is_synthetic": product.is_synthetic,
                "latest_description_id": description.id,
                "review_status": description.review_status,
            },
            "description": {
                "id": description.id,
                "version": description.version,
                "provider": description.provider,
                "title": description.title,
                "short_description": description.short_description,
                "long_description": description.long_description,
                "feature_bullets": description.feature_bullets,
                "seo_title": description.seo_title,
                "seo_meta_description": description.seo_meta_description,
                "quality_score": description.quality_score,
                "factual_warnings": description.factual_warnings,
                "agent_trace": description.agent_trace,
                "review_status": description.review_status,
                "reviewer_notes": description.reviewer_notes,
            },
        })
    return items


def _desc_review_status(product: Product) -> str | None:
    if product.descriptions:
        latest = max(product.descriptions, key=lambda d: d.version)
        return latest.review_status
    return None


@router.get("", response_model=ProductListResponse)
async def list_products(
    db: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source_name: str | None = Query(default=None),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
):
    products, total = await product_service.get_products(
        db, page=page, page_size=page_size,
        source_name=source_name, category=category, search=search,
    )
    items = [
        ProductResponse(
            id=p.id,
            source_name=p.source_name,
            external_id=p.external_id,
            name=p.name,
            brand=p.brand,
            category=p.category,
            original_description=p.original_description,
            features=p.features,
            specifications=p.specifications,
            material=p.material,
            color=p.color,
            weight_kg=p.weight_kg,
            dimensions_cm=p.dimensions_cm,
            price=p.price,
            quantity=p.quantity,
            currency=p.currency,
            target_keywords=p.target_keywords,
            image_url=p.image_url,
            is_synthetic=p.is_synthetic,
            created_at=p.created_at,
            updated_at=p.updated_at,
            latest_description_id=p.descriptions[-1].id if p.descriptions else None,
            review_status=p.descriptions[-1].review_status if p.descriptions else None,
        )
        for p in products
    ]
    return ProductListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str, db: DB):
    product = await product_service.get_product_by_id(product_id, db)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    return ProductResponse(
        id=product.id,
        source_name=product.source_name,
        external_id=product.external_id,
        name=product.name,
        brand=product.brand,
        category=product.category,
        original_description=product.original_description,
        features=product.features,
        specifications=product.specifications,
        material=product.material,
        color=product.color,
        weight_kg=product.weight_kg,
        dimensions_cm=product.dimensions_cm,
        price=product.price,
        quantity=product.quantity,
        currency=product.currency,
        target_keywords=product.target_keywords,
        image_url=product.image_url,
        is_synthetic=product.is_synthetic,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


@router.post("/{product_id}/generate", response_model=GenerationResult)
async def generate_product_description(
    product_id: str,
    request: GenerationRequest,
    db: DB,
):
    try:
        result = await generate_description(product_id, request.settings, db)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{product_id}/descriptions")
async def get_product_descriptions(product_id: str, db: DB):
    descs = await product_service.get_product_descriptions(product_id, db)
    return [
        {
            "id": d.id,
            "version": d.version,
            "provider": d.provider,
            "model_id": d.model_id,
            "is_demo": d.is_demo,
            "title": d.title,
            "short_description": d.short_description,
            "long_description": d.long_description,
            "feature_bullets": d.feature_bullets,
            "seo_title": d.seo_title,
            "seo_meta_description": d.seo_meta_description,
            "keywords": d.keywords,
            "quality_score": d.quality_score,
            "quality_breakdown": d.quality_breakdown,
            "factual_warnings": d.factual_warnings,
            "factual_warning_count": d.factual_warning_count,
            "agent_trace": d.agent_trace,
            "review_status": d.review_status,
            "reviewer_notes": d.reviewer_notes,
            "reviewed_at": d.reviewed_at,
            "reviewed_by": d.reviewed_by,
            "edited_content": d.edited_content,
            "brand_voice": d.brand_voice,
            "created_at": d.created_at,
        }
        for d in descs
    ]


@router.post("/descriptions/{description_id}/review", status_code=status.HTTP_200_OK)
async def review_description(
    description_id: str,
    decision: ReviewDecision,
    db: DB,
):
    desc = await product_service.update_review_decision(
        description_id=description_id,
        status=decision.status,
        notes=decision.reviewer_notes,
        edited_content=decision.edited_content,
        reviewed_by=decision.reviewed_by,
        db=db,
    )
    if not desc:
        raise HTTPException(status_code=404, detail="Description not found.")
    return {"id": desc.id, "review_status": desc.review_status, "reviewed_at": desc.reviewed_at}


@router.post("/descriptions/bulk-review", status_code=status.HTTP_200_OK)
async def bulk_review_descriptions(decision: BulkReviewDecision, db: DB):
    """Apply one review decision to several generated descriptions atomically."""
    result = await db.execute(
        select(GeneratedDescription).where(GeneratedDescription.id.in_(decision.description_ids))
    )
    descriptions = result.scalars().all()
    found_ids = {item.id for item in descriptions}
    missing_ids = [item_id for item_id in decision.description_ids if item_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Descriptions not found: {missing_ids[:10]}")

    reviewed_at = datetime.now(timezone.utc)
    for description in descriptions:
        description.review_status = decision.status
        description.reviewer_notes = decision.reviewer_notes
        description.reviewed_by = decision.reviewed_by
        description.reviewed_at = reviewed_at
    await db.commit()
    return {"updated_count": len(descriptions), "review_status": decision.status, "reviewed_at": reviewed_at}
