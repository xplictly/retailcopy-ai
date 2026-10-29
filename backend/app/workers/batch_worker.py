"""Persistent background batch worker.

Architecture:
- BatchJob and BatchJobItem records are the authoritative state.
- Worker reads from DB, not an in-memory queue.
- asyncio.Semaphore enforces concurrency limits.
- Exponential backoff for retries.
- Cancellation via status flag checked before each item.
- Recovery: on startup, re-queues items that were 'running' (interrupted restart).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal
from app.models.models import BatchJob, BatchJobItem, GeneratedDescription, Product
from app.schemas.schemas import GenerationSettings
from app.services.generation_service import generate_description, get_product_or_raise, _product_to_response
from app.services.factual_checker import run_factual_checks
from app.services.quality_evaluator import evaluate_quality
from app.ai.provider_factory import get_provider

logger = logging.getLogger(__name__)
_settings = get_settings()

# ── Job Creation ──────────────────────────────────────────────────────────────

async def create_batch_job(
    product_ids: list[str],
    settings: GenerationSettings,
    db: AsyncSession,
) -> BatchJob:
    """Create a batch job and its items. Returns the job record immediately."""
    provider = get_provider()
    job = BatchJob(
        id=str(uuid.uuid4()),
        status="pending",
        total_items=len(product_ids),
        processed_items=0,
        successful_items=0,
        failed_items=0,
        generation_settings=settings.model_dump(),
        provider=provider.provider_name,
        model_id=provider.model_id,
        items=[],
    )
    db.add(job)
    await db.flush()

    for product_id in product_ids:
        idem_key = f"{job.id}:{product_id}"
        item = BatchJobItem(
            id=str(uuid.uuid4()),
            job_id=job.id,
            product_id=product_id,
            idempotency_key=idem_key,
            status="pending",
        )
        db.add(item)
        job.items.append(item)

    await db.flush()
    return job


# ── Worker ────────────────────────────────────────────────────────────────────

_active_jobs: set[str] = set()  # job IDs currently being processed


async def _process_single_item(
    item_id: str,
    settings: GenerationSettings,
    retry_limit: int,
    backoff_base: float,
) -> None:
    """Process a single batch item with retries. Uses its own DB session."""
    for attempt in range(1, retry_limit + 2):
        async with AsyncSessionLocal() as db:
            # Reload item
            result = await db.execute(select(BatchJobItem).where(BatchJobItem.id == item_id))
            item = result.scalar_one_or_none()
            if not item:
                logger.error("Batch item %s not found in DB.", item_id)
                return

            # Check cancellation
            job_result = await db.execute(select(BatchJob).where(BatchJob.id == item.job_id))
            job = job_result.scalar_one_or_none()
            if job and job.status in ("cancelling", "cancelled"):
                item.status = "cancelled"
                item.updated_at = datetime.utcnow()
                await db.commit()
                return

            # Skip already succeeded items (idempotency)
            if item.status == "success":
                return

            item.status = "running"
            item.attempts = attempt
            item.started_at = datetime.utcnow()
            await db.commit()

        # Do the actual generation (outside the session to avoid long-held connections)
        start_ms = int(datetime.utcnow().timestamp() * 1000)
        try:
            async with AsyncSessionLocal() as db:
                result = await generate_description(item.product_id, settings, db)
                await db.commit()
                desc_id = result.id

            end_ms = int(datetime.utcnow().timestamp() * 1000)
            duration = end_ms - start_ms

            async with AsyncSessionLocal() as db:
                res = await db.execute(select(BatchJobItem).where(BatchJobItem.id == item_id))
                item = res.scalar_one()
                item.status = "success"
                item.description_id = desc_id
                item.completed_at = datetime.utcnow()
                item.duration_ms = duration
                item.last_error = None
                await db.commit()
            return  # Success — stop retrying

        except Exception as exc:
            logger.warning(
                "Batch item %s attempt %d/%d failed: %s",
                item_id, attempt, retry_limit + 1, exc,
            )
            if attempt <= retry_limit:
                wait = backoff_base ** attempt
                await asyncio.sleep(wait)
            else:
                # Final failure
                async with AsyncSessionLocal() as db:
                    res = await db.execute(select(BatchJobItem).where(BatchJobItem.id == item_id))
                    item = res.scalar_one()
                    item.status = "failed"
                    item.last_error = str(exc)[:2000]
                    item.completed_at = datetime.utcnow()
                    await db.commit()
                return


async def _update_job_progress(job_id: str) -> None:
    """Recount item states from DB and update job counters."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BatchJobItem).where(BatchJobItem.job_id == job_id)
        )
        items = result.scalars().all()

        total = len(items)
        success = sum(1 for i in items if i.status == "success")
        failed = sum(1 for i in items if i.status == "failed")
        cancelled = sum(1 for i in items if i.status == "cancelled")
        processed = success + failed + cancelled

        job_result = await db.execute(select(BatchJob).where(BatchJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if not job:
            return

        job.processed_items = processed
        job.successful_items = success
        job.failed_items = failed
        job.updated_at = datetime.utcnow()
        await db.commit()


async def run_batch_job(job_id: str) -> None:
    """Run a batch job to completion. Called as a background asyncio task."""
    if job_id in _active_jobs:
        logger.warning("Job %s is already running.", job_id)
        return

    _active_jobs.add(job_id)
    semaphore = asyncio.Semaphore(_settings.batch_concurrency)

    try:
        # Mark job as running
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(BatchJob).where(BatchJob.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                logger.error("Job %s not found.", job_id)
                return
            job.status = "running"
            job.started_at = datetime.utcnow()
            settings_dict = job.generation_settings or {}
            await db.commit()

        settings = GenerationSettings(**settings_dict)
        retry_limit = _settings.batch_retry_limit
        backoff_base = _settings.batch_retry_backoff_base

        # Fetch pending items
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BatchJobItem)
                .where(BatchJobItem.job_id == job_id)
                .where(BatchJobItem.status.in_(["pending", "running"]))  # 'running' = interrupted
            )
            items = result.scalars().all()
            item_ids = [i.id for i in items]

        # Reset any 'running' items from a previous run to 'pending'
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(BatchJobItem)
                .where(BatchJobItem.job_id == job_id)
                .where(BatchJobItem.status == "running")
                .values(status="pending")
            )
            await db.commit()

        async def _process_with_semaphore(item_id: str) -> None:
            async with semaphore:
                # Check cancellation
                async with AsyncSessionLocal() as db:
                    res = await db.execute(select(BatchJob).where(BatchJob.id == job_id))
                    job_check = res.scalar_one_or_none()
                    if job_check and job_check.status in ("cancelling", "cancelled"):
                        return
                await _process_single_item(item_id, settings, retry_limit, backoff_base)
                await _update_job_progress(job_id)

        # Run all items concurrently (controlled by semaphore)
        await asyncio.gather(*[_process_with_semaphore(iid) for iid in item_ids])

        # Final job status
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(BatchJob).where(BatchJob.id == job_id))
            job = result.scalar_one()

            if job.status in ("cancelling",):
                job.status = "cancelled"
            elif job.failed_items > 0 and job.successful_items > 0:
                job.status = "completed_with_errors"
            elif job.failed_items > 0 and job.successful_items == 0:
                job.status = "failed"
            elif job.successful_items == job.total_items:
                job.status = "completed"
            else:
                job.status = "completed_with_errors"

            job.completed_at = datetime.utcnow()
            await db.commit()

        logger.info(
            "Batch job %s completed: status=%s, success=%d, failed=%d",
            job_id, job.status, job.successful_items, job.failed_items,
        )

    except Exception as exc:
        logger.error("Batch job %s crashed: %s", job_id, exc)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(BatchJob).where(BatchJob.id == job_id))
            job = result.scalar_one_or_none()
            if job:
                job.status = "failed"
                job.error_message = str(exc)[:2000]
                job.completed_at = datetime.utcnow()
                await db.commit()
    finally:
        _active_jobs.discard(job_id)


async def cancel_batch_job(job_id: str, db: AsyncSession) -> BatchJob | None:
    """Request cancellation of a running job."""
    result = await db.execute(select(BatchJob).where(BatchJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return None
    if job.status in ("completed", "cancelled", "failed"):
        return job
    job.status = "cancelling"
    await db.flush()
    return job


async def retry_failed_items(job_id: str, db: AsyncSession) -> int:
    """Reset failed items to pending and re-queue the job. Returns count of reset items."""
    result = await db.execute(
        select(BatchJobItem)
        .where(BatchJobItem.job_id == job_id)
        .where(BatchJobItem.status == "failed")
    )
    failed_items = result.scalars().all()
    count = 0
    for item in failed_items:
        item.status = "pending"
        item.last_error = None
        count += 1

    if count > 0:
        job_result = await db.execute(select(BatchJob).where(BatchJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if job:
            job.status = "pending"
            job.failed_items = 0

    await db.flush()
    return count


async def recover_interrupted_jobs() -> None:
    """On startup: recover jobs that were 'running' when the app was last killed."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BatchJob).where(BatchJob.status == "running")
        )
        interrupted = result.scalars().all()
        for job in interrupted:
            logger.warning("Recovering interrupted job %s", job.id)
            job.status = "pending"
        await db.commit()

    # Restart recovered jobs
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BatchJob).where(BatchJob.status == "pending")
        )
        pending = result.scalars().all()
        for job in pending:
            logger.info("Re-queuing recovered job %s", job.id)
            asyncio.create_task(run_batch_job(job.id))
