"""Product CRUD service."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import GeneratedDescription, Product
from app.schemas.schemas import ProductCreate, ProductResponse

logger = logging.getLogger(__name__)


async def create_or_skip_product(
    product_create: ProductCreate,
    db: AsyncSession,
) -> tuple[Product, bool]:
    """Insert product; return (product, created). created=False means duplicate skipped."""
    result = await db.execute(
        select(Product).where(
            Product.source_name == product_create.source_name,
            Product.external_id == product_create.external_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False

    product = Product(**product_create.model_dump())
    db.add(product)
    await db.flush()
    return product, True


async def bulk_import_products(
    products: list[ProductCreate],
    db: AsyncSession,
) -> tuple[list[str], int, list[str]]:
    """
    Import products, skipping duplicates.
    Returns (imported_ids, skipped_count, error_messages)
    """
    imported_ids: list[str] = []
    skipped = 0
    errors: list[str] = []

    for pc in products:
        try:
            product, created = await create_or_skip_product(pc, db)
            if created:
                imported_ids.append(product.id)
            else:
                skipped += 1
        except Exception as exc:
            errors.append(f"Error importing '{pc.name}': {exc}")
            logger.error("Bulk import error for '%s': %s", pc.name, exc)

    return imported_ids, skipped, errors


async def get_products(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    source_name: str | None = None,
    category: str | None = None,
    search: str | None = None,
) -> tuple[list[Product], int]:
    """Paginated product listing with optional filters."""
    query = select(Product).options(selectinload(Product.descriptions))
    count_query = select(func.count(Product.id))

    if source_name:
        query = query.where(Product.source_name == source_name)
        count_query = count_query.where(Product.source_name == source_name)
    if category:
        query = query.where(Product.category == category)
        count_query = count_query.where(Product.category == category)
    if search:
        like = f"%{search}%"
        query = query.where(
            Product.name.ilike(like) | Product.brand.ilike(like) | Product.category.ilike(like)
        )
        count_query = count_query.where(
            Product.name.ilike(like) | Product.brand.ilike(like) | Product.category.ilike(like)
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    query = query.order_by(Product.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    products = list(result.scalars().all())

    return products, total


async def get_product_by_id(product_id: str, db: AsyncSession) -> Product | None:
    result = await db.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.descriptions))
    )
    return result.scalar_one_or_none()


async def get_product_descriptions(product_id: str, db: AsyncSession) -> list[GeneratedDescription]:
    result = await db.execute(
        select(GeneratedDescription)
        .where(GeneratedDescription.product_id == product_id)
        .order_by(GeneratedDescription.version.desc())
    )
    return list(result.scalars().all())


async def update_review_decision(
    description_id: str,
    status: str,
    notes: str | None,
    edited_content: dict | None,
    reviewed_by: str | None,
    db: AsyncSession,
) -> GeneratedDescription | None:
    from datetime import datetime
    result = await db.execute(
        select(GeneratedDescription).where(GeneratedDescription.id == description_id)
    )
    desc = result.scalar_one_or_none()
    if not desc:
        return None
    desc.review_status = status
    desc.reviewer_notes = notes
    desc.reviewed_at = datetime.utcnow()
    desc.reviewed_by = reviewed_by
    if edited_content:
        desc.edited_content = edited_content
    await db.flush()
    return desc
