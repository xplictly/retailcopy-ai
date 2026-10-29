"""Pydantic schemas for products and generation."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ── Product Schemas ───────────────────────────────────────────────────────────

class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    brand: str | None = None
    category: str | None = None
    original_description: str | None = None
    features: list[str] | None = None
    specifications: dict[str, Any] | None = None
    material: str | None = None
    color: str | None = None
    weight_kg: float | None = None
    dimensions_cm: str | None = None
    price: float | None = None
    quantity: int | None = Field(default=None, ge=0)
    currency: str = "USD"
    target_keywords: list[str] | None = None
    image_url: str | None = None


class ProductCreate(ProductBase):
    source_name: str
    external_id: str | None = None
    raw_source_data: dict[str, Any] | None = None
    is_synthetic: bool = False


class ProductResponse(ProductBase):
    id: str
    source_name: str
    external_id: str | None = None
    is_synthetic: bool
    created_at: datetime
    updated_at: datetime
    latest_description_id: str | None = None
    review_status: str | None = None

    model_config = {"from_attributes": True}


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    page: int
    page_size: int


# ── Generation Schemas ────────────────────────────────────────────────────────

class GenerationSettings(BaseModel):
    brand_voice: str = Field(default="professional", pattern="^(professional|friendly|premium|technical|playful)$")
    target_audience: str | None = None
    language: str = "en"
    description_length: str = Field(default="medium", pattern="^(short|medium|long)$")
    seo_keywords: list[str] | None = None
    category_instructions: str | None = None
    rag_context: str | None = None
    provider_override: str | None = None
    variant_count: int = Field(default=1, ge=1, le=3)
    quality_threshold: float = Field(default=7.0, ge=0, le=10)
    max_regeneration_attempts: int = Field(default=2, ge=0, le=3)


class GeneratedContent(BaseModel):
    title: str
    short_description: str
    long_description: str
    feature_bullets: list[str]
    seo_title: str
    seo_meta_description: str
    keywords: list[str]


class FactualWarning(BaseModel):
    severity: str  # info|warning|error
    claim: str
    explanation: str
    source_attribute: str | None = None
    suggested_action: str | None = None


class QualityBreakdown(BaseModel):
    relevance: float = Field(ge=0, le=10)
    factual_consistency: float = Field(ge=0, le=10)
    readability: float = Field(ge=0, le=10)
    creativity: float = Field(ge=0, le=10)
    seo_coverage: float = Field(ge=0, le=10)
    brand_adherence: float = Field(ge=0, le=10)
    overall: float = Field(ge=0, le=10)


class GenerationResult(BaseModel):
    id: str
    product_id: str
    version: int
    provider: str
    model_id: str | None = None
    is_demo: bool
    content: GeneratedContent
    quality_score: float
    quality_breakdown: QualityBreakdown
    factual_warnings: list[FactualWarning]
    factual_warning_count: int
    agent_trace: dict[str, Any] | None = None
    review_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class GenerationRequest(BaseModel):
    product_id: str
    settings: GenerationSettings = Field(default_factory=GenerationSettings)


# ── Review Schemas ────────────────────────────────────────────────────────────

class ReviewDecision(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected|needs_editing)$")
    reviewer_notes: str | None = None
    reviewed_by: str | None = "human_reviewer"
    edited_content: dict[str, Any] | None = None


class BulkReviewDecision(BaseModel):
    description_ids: list[str] = Field(..., min_length=1)
    status: str = Field(..., pattern="^(approved|rejected|needs_editing)$")
    reviewer_notes: str | None = None
    reviewed_by: str | None = "human_reviewer"


# ── Batch Job Schemas ─────────────────────────────────────────────────────────

class BatchJobCreate(BaseModel):
    product_ids: list[str] = Field(..., min_length=1)
    settings: GenerationSettings = Field(default_factory=GenerationSettings)


class BatchJobItemResponse(BaseModel):
    id: str
    product_id: str
    status: str
    attempts: int
    last_error: str | None = None
    description_id: str | None = None
    duration_ms: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchJobResponse(BaseModel):
    id: str
    status: str
    total_items: int
    processed_items: int
    successful_items: int
    failed_items: int
    provider: str | None = None
    model_id: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    progress_pct: float = 0.0

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_progress(cls, job) -> "BatchJobResponse":
        obj = cls.model_validate(job)
        if job.total_items > 0:
            obj.progress_pct = round(job.processed_items / job.total_items * 100, 1)
        return obj


class BatchJobListResponse(BaseModel):
    items: list[BatchJobResponse]
    total: int


# ── Import Schemas ────────────────────────────────────────────────────────────

class ImportResult(BaseModel):
    source: str
    total_fetched: int
    imported: int
    skipped_duplicates: int
    failed: int
    errors: list[str] = []
    product_ids: list[str] = []


# ── Provider Status ───────────────────────────────────────────────────────────

class ProviderStatus(BaseModel):
    provider: str
    is_demo_mode: bool
    is_operational: bool
    model_id: str | None = None
    message: str
    ollama_models: list[str] | None = None


# ── Export ────────────────────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    format: str = Field(default="csv", pattern="^(csv|json)$")
    approved_only: bool = False
    product_ids: list[str] | None = None
    search: str | None = None
    category: str | None = None


# ── Analytics ─────────────────────────────────────────────────────────────────

class AnalyticsSummary(BaseModel):
    total_products: int
    total_generated: int
    total_approved: int
    total_rejected: int
    total_needs_editing: int
    total_pending_review: int
    avg_quality_score: float | None
    total_factual_warnings: int
    total_batch_jobs: int
    active_provider: str
    is_demo_mode: bool
