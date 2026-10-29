"""SQLAlchemy ORM models for RetailCopy AI."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# ── Product ──────────────────────────────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("source_name", "external_id", name="uq_product_source_external"),
        Index("ix_product_category", "category"),
        Index("ix_product_source", "source_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(256))
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(256))
    category: Mapped[str | None] = mapped_column(String(256))
    original_description: Mapped[str | None] = mapped_column(Text)
    features: Mapped[list | None] = mapped_column(JSON)
    specifications: Mapped[dict | None] = mapped_column(JSON)
    material: Mapped[str | None] = mapped_column(String(256))
    color: Mapped[str | None] = mapped_column(String(128))
    weight_kg: Mapped[float | None] = mapped_column(Float)
    dimensions_cm: Mapped[str | None] = mapped_column(String(128))
    price: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    target_keywords: Mapped[list | None] = mapped_column(JSON)
    image_url: Mapped[str | None] = mapped_column(String(1024))
    raw_source_data: Mapped[dict | None] = mapped_column(JSON)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    # Relationships
    descriptions: Mapped[list[GeneratedDescription]] = relationship(
        "GeneratedDescription", back_populates="product", cascade="all, delete-orphan"
    )
    batch_items: Mapped[list[BatchJobItem]] = relationship(
        "BatchJobItem", back_populates="product"
    )


# ── Generated Description ─────────────────────────────────────────────────────

class GeneratedDescription(Base):
    __tablename__ = "generated_descriptions"
    __table_args__ = (
        Index("ix_gen_desc_product", "product_id"),
        Index("ix_gen_desc_status", "review_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[str | None] = mapped_column(String(256))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    # Generation settings snapshot
    brand_voice: Mapped[str | None] = mapped_column(String(64))
    target_audience: Mapped[str | None] = mapped_column(String(256))
    language: Mapped[str] = mapped_column(String(8), default="en")
    description_length: Mapped[str | None] = mapped_column(String(32))
    seo_keywords: Mapped[list | None] = mapped_column(JSON)

    # Generated content
    title: Mapped[str | None] = mapped_column(String(512))
    short_description: Mapped[str | None] = mapped_column(Text)
    long_description: Mapped[str | None] = mapped_column(Text)
    feature_bullets: Mapped[list | None] = mapped_column(JSON)
    seo_title: Mapped[str | None] = mapped_column(String(256))
    seo_meta_description: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list | None] = mapped_column(JSON)

    # Raw LLM output for audit
    raw_llm_output: Mapped[str | None] = mapped_column(Text)
    prompt_used: Mapped[str | None] = mapped_column(Text)

    # Quality
    quality_score: Mapped[float | None] = mapped_column(Float)
    quality_breakdown: Mapped[dict | None] = mapped_column(JSON)
    factual_warnings: Mapped[list | None] = mapped_column(JSON)
    factual_warning_count: Mapped[int] = mapped_column(Integer, default=0)
    agent_trace: Mapped[dict | None] = mapped_column(JSON)

    # Review
    review_status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|approved|rejected|needs_editing
    reviewer_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by: Mapped[str | None] = mapped_column(String(256))

    # Edited content (human override)
    edited_content: Mapped[dict | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="descriptions")
    batch_item: Mapped[BatchJobItem | None] = relationship(
        "BatchJobItem", back_populates="description", uselist=False
    )


# ── Batch Job ─────────────────────────────────────────────────────────────────

class BatchJob(Base):
    __tablename__ = "batch_jobs"
    __table_args__ = (
        Index("ix_batch_job_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending|running|completed|completed_with_errors|cancelling|cancelled|failed

    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    successful_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)

    # Settings
    generation_settings: Mapped[dict | None] = mapped_column(JSON)
    provider: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[str | None] = mapped_column(String(256))

    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    items: Mapped[list[BatchJobItem]] = relationship(
        "BatchJobItem", back_populates="job", cascade="all, delete-orphan"
    )


class BatchJobItem(Base):
    __tablename__ = "batch_job_items"
    __table_args__ = (
        UniqueConstraint("job_id", "product_id", name="uq_batch_item_job_product"),
        Index("ix_batch_item_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("batch_jobs.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)

    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending|running|success|failed|skipped|cancelled

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    description_id: Mapped[str | None] = mapped_column(ForeignKey("generated_descriptions.id"))

    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    job: Mapped[BatchJob] = relationship("BatchJob", back_populates="items")
    product: Mapped[Product] = relationship("Product", back_populates="batch_items")
    description: Mapped[GeneratedDescription | None] = relationship(
        "GeneratedDescription", back_populates="batch_item"
    )
