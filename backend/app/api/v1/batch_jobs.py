"""Batch jobs API router."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.models import BatchJob, BatchJobItem, Product
from app.schemas.schemas import (
    BatchJobCreate,
    BatchJobListResponse,
    BatchJobResponse,
)
from app.services.product_service import get_product_by_id
from app.workers.batch_worker import (
    cancel_batch_job,
    create_batch_job,
    retry_failed_items,
    run_batch_job,
)

router = APIRouter(prefix="/batch-jobs", tags=["batch"])
logger = logging.getLogger(__name__)

DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("", response_model=BatchJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_batch_job(payload: BatchJobCreate, db: DB):
    """Submit a batch generation job. Returns a persistent job ID immediately."""
    # Validate product IDs exist
    invalid_ids = []
    for pid in payload.product_ids[:10]:  # Spot-check first 10
        product = await get_product_by_id(pid, db)
        if not product:
            invalid_ids.append(pid)
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown product IDs: {invalid_ids[:5]}",
        )

    job = await create_batch_job(payload.product_ids, payload.settings, db)
    await db.commit()

    # Launch in production and unit-driven app runs; tests remain deterministic.
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        asyncio.create_task(run_batch_job(job.id))

    return BatchJobResponse.from_orm_with_progress(job)


@router.get("", response_model=BatchJobListResponse)
async def list_batch_jobs(
    db: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    total_result = await db.execute(select(func.count(BatchJob.id)))
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(BatchJob).order_by(BatchJob.created_at.desc()).offset(offset).limit(page_size)
    )
    jobs = result.scalars().all()
    return BatchJobListResponse(
        items=[BatchJobResponse.from_orm_with_progress(j) for j in jobs],
        total=total,
    )


@router.get("/{job_id}", response_model=BatchJobResponse)
async def get_batch_job(job_id: str, db: DB):
    result = await db.execute(select(BatchJob).where(BatchJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found.")
    return BatchJobResponse.from_orm_with_progress(job)


@router.get("/{job_id}/results")
async def get_batch_job_results(
    job_id: str,
    db: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
):
    """Get individual item results for a batch job."""
    # Verify job exists
    job_result = await db.execute(select(BatchJob).where(BatchJob.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found.")

    query = (
        select(BatchJobItem, Product)
        .join(Product, BatchJobItem.product_id == Product.id, isouter=True)
        .where(BatchJobItem.job_id == job_id)
    )
    if status_filter:
        query = query.where(BatchJobItem.status == status_filter)

    count_q = select(func.count(BatchJobItem.id)).where(BatchJobItem.job_id == job_id)
    if status_filter:
        count_q = count_q.where(BatchJobItem.status == status_filter)

    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    query = query.order_by(BatchJobItem.created_at.asc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    rows = result.all()

    return {
        "job_id": job_id,
        "job_status": job.status,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": product.name if product else None,
                "product_category": product.category if product else None,
                "quantity": product.quantity if product else None,
                "status": item.status,
                "attempts": item.attempts,
                "last_error": item.last_error,
                "description_id": item.description_id,
                "duration_ms": item.duration_ms,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item, product in rows
        ],
    }


@router.post("/{job_id}/cancel", response_model=BatchJobResponse)
async def cancel_job(job_id: str, db: DB):
    job = await cancel_batch_job(job_id, db)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found.")
    await db.commit()
    return BatchJobResponse.from_orm_with_progress(job)


@router.post("/{job_id}/retry", response_model=BatchJobResponse)
async def retry_job(job_id: str, db: DB):
    """Retry failed items — does not reprocess successful items."""
    count = await retry_failed_items(job_id, db)
    if count == 0:
        raise HTTPException(status_code=400, detail="No failed items to retry.")
    await db.commit()

    # Re-launch worker outside deterministic test runs.
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        asyncio.create_task(run_batch_job(job_id))

    result = await db.execute(select(BatchJob).where(BatchJob.id == job_id))
    job = result.scalar_one()
    return BatchJobResponse.from_orm_with_progress(job)
