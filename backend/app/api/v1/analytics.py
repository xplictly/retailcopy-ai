"""Analytics, export, and provider status API router."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider_factory import get_provider
from app.core.config import get_settings
from app.db.database import get_db
from app.models.models import BatchJob, BatchJobItem, GeneratedDescription, Product
from app.schemas.schemas import AnalyticsSummary, ExportRequest, ProviderStatus
from app.services.export_service import export_products

router = APIRouter(tags=["analytics"])
logger = logging.getLogger(__name__)
_settings = get_settings()

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/analytics", response_model=AnalyticsSummary)
async def get_analytics(db: DB):
    total_products = (await db.execute(select(func.count(Product.id)))).scalar_one()
    total_generated = (await db.execute(select(func.count(GeneratedDescription.id)))).scalar_one()

    status_counts = {}
    for status_val in ["approved", "rejected", "needs_editing", "pending"]:
        count = (
            await db.execute(
                select(func.count(GeneratedDescription.id)).where(
                    GeneratedDescription.review_status == status_val
                )
            )
        ).scalar_one()
        status_counts[status_val] = count

    avg_q = (
        await db.execute(select(func.avg(GeneratedDescription.quality_score)))
    ).scalar_one()

    total_warnings = (
        await db.execute(select(func.sum(GeneratedDescription.factual_warning_count)))
    ).scalar_one() or 0

    total_jobs = (await db.execute(select(func.count(BatchJob.id)))).scalar_one()

    provider = get_provider()

    return AnalyticsSummary(
        total_products=total_products,
        total_generated=total_generated,
        total_approved=status_counts.get("approved", 0),
        total_rejected=status_counts.get("rejected", 0),
        total_needs_editing=status_counts.get("needs_editing", 0),
        total_pending_review=status_counts.get("pending", 0),
        avg_quality_score=round(float(avg_q), 2) if avg_q else None,
        total_factual_warnings=int(total_warnings),
        total_batch_jobs=total_jobs,
        active_provider=provider.provider_name,
        is_demo_mode=provider.provider_name == "demo",
    )


@router.get("/provider/status", response_model=ProviderStatus)
async def get_provider_status():
    provider = get_provider()
    is_available, message = await provider.is_available()

    ollama_models = None
    if provider.provider_name == "ollama":
        from app.ai.ollama_provider import OllamaProvider
        if isinstance(provider, OllamaProvider):
            ollama_models = await provider.list_models()

    return ProviderStatus(
        provider=provider.provider_name,
        is_demo_mode=provider.provider_name == "demo",
        is_operational=is_available,
        model_id=provider.model_id,
        message=message,
        ollama_models=ollama_models,
    )


@router.post("/export")
async def export_data(
    request: ExportRequest,
    db: DB,
):
    """Export generated descriptions as CSV or JSON."""
    content = await export_products(
        db,
        approved_only=request.approved_only,
        product_ids=request.product_ids,
        search=request.search,
        category=request.category,
        format=request.format,
    )

    if request.format == "csv":
        filename = "retailcopy_export_approved.csv" if request.approved_only else "retailcopy_export.csv"
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    else:
        filename = "retailcopy_export_approved.json" if request.approved_only else "retailcopy_export.json"
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )


@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset_database(db: DB, confirm: bool = Query(default=False)):
    """Delete all catalog, generated-content, review, and batch data."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to reset the database.")

    await db.execute(delete(BatchJobItem))
    await db.execute(delete(GeneratedDescription))
    await db.execute(delete(BatchJob))
    await db.execute(delete(Product))
    await db.flush()

    return {
        "status": "reset_complete",
        "products_deleted": True,
        "generated_descriptions_deleted": True,
        "review_history_deleted": True,
        "batch_history_deleted": True,
    }


@router.get("/categories")
async def get_categories(db: DB):
    """Get all distinct categories from the product catalog."""
    result = await db.execute(
        select(Product.category, func.count(Product.id).label("count"))
        .where(Product.category.isnot(None))
        .group_by(Product.category)
        .order_by(func.count(Product.id).desc())
    )
    rows = result.all()
    return [{"category": r.category, "count": r.count} for r in rows]
