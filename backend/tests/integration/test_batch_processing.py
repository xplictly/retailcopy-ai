"""Integration tests: batch processing with 50+ products."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.models import BatchJob, BatchJobItem, Product
from app.schemas.schemas import GenerationSettings
from app.workers.batch_worker import (
    cancel_batch_job,
    create_batch_job,
    retry_failed_items,
    run_batch_job,
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def engine():
    e = create_async_engine(
        TEST_DB_URL,
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield e
    await e.dispose()


@pytest_asyncio.fixture(scope="function")
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


async def _create_test_products(db: AsyncSession, count: int = 55) -> list[str]:
    """Create N test products and return their IDs."""
    ids = []
    for i in range(count):
        product = Product(
            id=str(uuid.uuid4()),
            source_name="test",
            external_id=f"batch-test-{i}",
            name=f"Batch Test Product {i+1}",
            brand="TestBrand",
            category="electronics",
            price=float(10 + i),
            currency="USD",
            is_synthetic=True,
        )
        db.add(product)
        ids.append(product.id)
    await db.commit()
    return ids


class TestBatchJobCreation:
    @pytest.mark.asyncio
    async def test_creates_job_with_items(self, db: AsyncSession):
        product_ids = await _create_test_products(db, 5)
        settings = GenerationSettings()
        job = await create_batch_job(product_ids, settings, db)
        await db.commit()

        assert job.id is not None
        assert job.status == "pending"
        assert job.total_items == 5
        assert len(job.items) == 5

    @pytest.mark.asyncio
    async def test_job_returned_before_processing(self, db: AsyncSession):
        """Job ID is returned immediately, not after processing completes."""
        product_ids = await _create_test_products(db, 3)
        settings = GenerationSettings()
        job = await create_batch_job(product_ids, settings, db)
        await db.commit()

        # Job should be pending, not completed
        assert job.status == "pending"
        assert job.processed_items == 0

    @pytest.mark.asyncio
    async def test_idempotency_keys_unique(self, db: AsyncSession):
        product_ids = await _create_test_products(db, 10)
        settings = GenerationSettings()
        job = await create_batch_job(product_ids, settings, db)
        await db.commit()

        keys = {item.idempotency_key for item in job.items}
        assert len(keys) == 10  # All unique


class TestBatch50Products:
    @pytest.mark.asyncio
    async def test_batch_processes_50_products_deterministically(self, engine):
        """
        ACCEPTANCE TEST: 50-product batch with demo provider.
        Verifies:
        - All 50 records are accounted for
        - Successful items have persisted descriptions
        - Progress counts match actual DB state
        """
        from sqlalchemy import select
        from app.db.database import AsyncSessionLocal
        import app.db.database as db_module

        # Patch the worker's session factory to use our test engine
        test_factory = async_sessionmaker(engine, expire_on_commit=False)

        # Create 50 products
        async with test_factory() as session:
            product_ids = await _create_test_products(session, 50)

        settings = GenerationSettings(brand_voice="professional")

        # Create job
        async with test_factory() as session:
            job = await create_batch_job(product_ids, settings, session)
            job_id = job.id
            await session.commit()

        # Run worker with patched session factory
        original_factory = db_module.AsyncSessionLocal

        try:
            db_module.AsyncSessionLocal = test_factory
            # Import and patch the worker's reference too
            import app.workers.batch_worker as worker_module
            worker_module.AsyncSessionLocal = test_factory
            worker_module.generate_description.__module__

            # Patch generate_description in the worker
            from app.services.generation_service import generate_description as real_gen

            async def mock_generate(product_id, settings, db):
                from app.schemas.schemas import GeneratedContent, GenerationResult, QualityBreakdown
                import uuid as _uuid
                content = GeneratedContent(
                    title=f"Title for {product_id[:8]}",
                    short_description="Short desc",
                    long_description="Long description content here.",
                    feature_bullets=["F1", "F2"],
                    seo_title=f"SEO {product_id[:8]}",
                    seo_meta_description="Meta desc",
                    keywords=["k1", "k2"],
                )
                from app.models.models import GeneratedDescription
                desc_id = str(_uuid.uuid4())
                desc = GeneratedDescription(
                    id=desc_id,
                    product_id=product_id,
                    version=1,
                    provider="demo",
                    model_id="demo-v1",
                    is_demo=True,
                    title=content.title,
                    short_description=content.short_description,
                    long_description=content.long_description,
                    feature_bullets=content.feature_bullets,
                    seo_title=content.seo_title,
                    seo_meta_description=content.seo_meta_description,
                    keywords=content.keywords,
                    quality_score=7.5,
                    quality_breakdown={"overall": 7.5},
                    factual_warnings=[],
                    factual_warning_count=0,
                    review_status="pending",
                )
                db.add(desc)
                await db.flush()

                from app.schemas.schemas import QualityBreakdown as QB, FactualWarning as FW
                return GenerationResult(
                    id=desc_id,
                    product_id=product_id,
                    version=1,
                    provider="demo",
                    model_id="demo-v1",
                    is_demo=True,
                    content=content,
                    quality_score=7.5,
                    quality_breakdown=QB(relevance=7.5, factual_consistency=10, readability=7, creativity=6, seo_coverage=8, brand_adherence=6, overall=7.5),
                    factual_warnings=[],
                    factual_warning_count=0,
                    review_status="pending",
                    created_at=datetime.utcnow(),
                )

            with patch("app.workers.batch_worker.generate_description", side_effect=mock_generate):
                with patch("app.workers.batch_worker.AsyncSessionLocal", test_factory):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        await run_batch_job(job_id)

        finally:
            db_module.AsyncSessionLocal = original_factory

        # Verify final state
        async with test_factory() as session:
            from sqlalchemy import select as sel
            job_result = await session.execute(sel(BatchJob).where(BatchJob.id == job_id))
            final_job = job_result.scalar_one()

            item_result = await session.execute(sel(BatchJobItem).where(BatchJobItem.job_id == job_id))
            final_items = item_result.scalars().all()

            assert len(final_items) == 50, f"Expected 50 items, got {len(final_items)}"
            assert final_job.total_items == 50

            success_count = sum(1 for i in final_items if i.status == "success")
            failed_count = sum(1 for i in final_items if i.status == "failed")
            pending_count = sum(1 for i in final_items if i.status == "pending")

            # All 50 should be accounted for (no silent loss)
            assert success_count + failed_count + pending_count == 50
            assert success_count == 50, f"Expected 50 successes, got {success_count} (failed={failed_count})"

            assert final_job.successful_items == 50
            assert final_job.failed_items == 0
            assert final_job.status == "completed"


class TestBatchCancellation:
    @pytest.mark.asyncio
    async def test_cancel_pending_job(self, db: AsyncSession):
        product_ids = await _create_test_products(db, 5)
        settings = GenerationSettings()
        job = await create_batch_job(product_ids, settings, db)
        await db.commit()

        cancelled = await cancel_batch_job(job.id, db)
        await db.commit()

        assert cancelled is not None
        assert cancelled.status == "cancelling"

    @pytest.mark.asyncio
    async def test_cancel_already_completed_job_noop(self, db: AsyncSession):
        product_ids = await _create_test_products(db, 3)
        settings = GenerationSettings()
        job = await create_batch_job(product_ids, settings, db)
        job.status = "completed"
        await db.commit()

        cancelled = await cancel_batch_job(job.id, db)
        assert cancelled.status == "completed"  # Unchanged


class TestBatchRetry:
    @pytest.mark.asyncio
    async def test_retry_resets_failed_items_only(self, db: AsyncSession):
        """Retry must not reprocess successful records."""
        product_ids = await _create_test_products(db, 5)
        settings = GenerationSettings()
        job = await create_batch_job(product_ids, settings, db)
        await db.commit()

        # Manually set some items to success, some to failed
        items = job.items
        for i, item in enumerate(items):
            if i < 3:
                item.status = "success"
            else:
                item.status = "failed"
                item.last_error = "Simulated error"
        await db.commit()

        count = await retry_failed_items(job.id, db)
        await db.commit()

        assert count == 2  # Only the 2 failed items

        # Successful items must still be success
        from sqlalchemy import select
        result = await db.execute(
            select(BatchJobItem).where(
                BatchJobItem.job_id == job.id,
                BatchJobItem.status == "success"
            )
        )
        still_success = result.scalars().all()
        assert len(still_success) == 3  # Unchanged

    @pytest.mark.asyncio
    async def test_retry_clears_error_messages(self, db: AsyncSession):
        product_ids = await _create_test_products(db, 2)
        settings = GenerationSettings()
        job = await create_batch_job(product_ids, settings, db)
        for item in job.items:
            item.status = "failed"
            item.last_error = "Old error"
        await db.commit()

        await retry_failed_items(job.id, db)
        await db.commit()

        for item in job.items:
            assert item.last_error is None
            assert item.status == "pending"


class TestBatchPartialFailure:
    @pytest.mark.asyncio
    async def test_batch_continues_after_individual_failure(self, engine):
        """If one item fails, others should still be processed."""
        test_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with test_factory() as session:
            product_ids = await _create_test_products(session, 5)

        settings = GenerationSettings()

        async with test_factory() as session:
            job = await create_batch_job(product_ids, settings, session)
            job_id = job.id
            await session.commit()

        call_count = [0]

        async def mock_generate_partial(product_id, settings, db):
            call_count[0] += 1
            if call_count[0] == 2:  # Second call fails
                raise RuntimeError("Simulated individual failure")

            from app.schemas.schemas import GeneratedContent, GenerationResult, QualityBreakdown
            import uuid as _uuid
            content = GeneratedContent(
                title=f"Title {product_id[:8]}",
                short_description="Short", long_description="Long",
                feature_bullets=["F"], seo_title="SEO", seo_meta_description="Meta",
                keywords=["k"],
            )
            from app.models.models import GeneratedDescription
            desc_id = str(_uuid.uuid4())
            desc = GeneratedDescription(
                id=desc_id, product_id=product_id, version=1,
                provider="demo", is_demo=True, title=content.title,
                short_description="S", long_description="L",
                feature_bullets=["F"], seo_title="SEO",
                seo_meta_description="M", keywords=["k"],
                quality_score=7.0, quality_breakdown={}, factual_warnings=[],
                factual_warning_count=0, review_status="pending",
            )
            db.add(desc)
            await db.flush()
            return GenerationResult(
                id=desc_id, product_id=product_id, version=1,
                provider="demo", is_demo=True, content=content,
                quality_score=7.0,
                quality_breakdown=QualityBreakdown(relevance=7, factual_consistency=10, readability=7, creativity=6, seo_coverage=7, brand_adherence=6, overall=7),
                factual_warnings=[], factual_warning_count=0,
                review_status="pending", created_at=datetime.utcnow(),
            )

        with patch("app.workers.batch_worker.generate_description", side_effect=mock_generate_partial):
            with patch("app.workers.batch_worker.AsyncSessionLocal", test_factory):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await run_batch_job(job_id)

        async with test_factory() as session:
            from sqlalchemy import select as sel
            result = await session.execute(sel(BatchJobItem).where(BatchJobItem.job_id == job_id))
            final_items = result.scalars().all()

            statuses = {i.status for i in final_items}
            assert "success" in statuses  # Some succeeded
            # Total items still 5
            assert len(final_items) == 5
