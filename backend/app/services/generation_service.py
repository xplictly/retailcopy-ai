"""Core description generation service."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider_factory import get_provider
from app.models.models import GeneratedDescription, Product
from app.schemas.schemas import (
    GeneratedContent,
    GenerationResult,
    GenerationSettings,
    ProductResponse,
    QualityBreakdown,
)
from app.services.factual_checker import run_factual_checks
from app.services.quality_evaluator import evaluate_quality
from app.services.rag_service import retrieve_rag_context
from app.services.agent_orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)


async def get_product_or_raise(product_id: str, db: AsyncSession) -> Product:
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise ValueError(f"Product {product_id} not found.")
    return product


def _product_to_response(product: Product) -> ProductResponse:
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
        quantity=product.quantity,
        dimensions_cm=product.dimensions_cm,
        price=product.price,
        currency=product.currency,
        target_keywords=product.target_keywords,
        image_url=product.image_url,
        is_synthetic=product.is_synthetic,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


async def generate_description(
    product_id: str,
    settings: GenerationSettings,
    db: AsyncSession,
) -> GenerationResult:
    """Generate, validate, score, and persist a product description."""

    product_orm = await get_product_or_raise(product_id, db)
    product = _product_to_response(product_orm)

    # Retrieval-augmented style context: approved descriptions from the same
    # category guide structure and tone, while PRODUCT DATA remains the only
    # factual source for the target product.
    settings.rag_context = await retrieve_rag_context(product, db)

    # Determine version
    result = await db.execute(
        select(GeneratedDescription)
        .where(GeneratedDescription.product_id == product_id)
        .order_by(GeneratedDescription.version.desc())
    )
    existing = result.scalars().all()
    next_version = max((d.version for d in existing), default=0) + 1

    provider = get_provider()
    is_demo = provider.provider_name == "demo"

    variants: list[tuple[GeneratedContent, list, QualityBreakdown, int, bool, dict]] = []
    orchestrator = AgentOrchestrator()
    for variant_index in range(settings.variant_count):
        result_trace = await orchestrator.run_variant(provider, product, settings, variant_index)
        content = result_trace["content"]
        warnings = result_trace["warnings"]
        quality = result_trace["quality"]
        passes_gate = result_trace["passes_gate"]
        regeneration_attempts = result_trace["trace"]["regeneration_attempts"]
        if not passes_gate:
            logger.info(
                "Multi-agent quality gate failed variant=%d after %d regeneration(s)",
                variant_index + 1, regeneration_attempts,
            )
        variants.append((content, warnings, quality, regeneration_attempts, passes_gate, result_trace["trace"]))

    # Highest-scored draft is recommended for review; publication still requires human approval.
    content, warnings, quality, regeneration_attempts, passes_gate, best_trace = max(
        variants, key=lambda item: item[2].overall
    )

    best_desc: GeneratedDescription | None = None
    for variant_offset, (variant_content, variant_warnings, variant_quality, variant_regenerations, variant_passes, variant_trace) in enumerate(variants):
        variant_version = next_version + variant_offset
        desc = GeneratedDescription(
            id=str(uuid.uuid4()),
            product_id=product_id,
            version=variant_version,
            provider=provider.provider_name,
            model_id=provider.model_id,
            is_demo=is_demo,
            brand_voice=settings.brand_voice,
            target_audience=settings.target_audience,
            language=settings.language,
            description_length=settings.description_length,
            seo_keywords=settings.seo_keywords,
            title=variant_content.title,
            short_description=variant_content.short_description,
            long_description=variant_content.long_description,
            feature_bullets=variant_content.feature_bullets,
            seo_title=variant_content.seo_title,
            seo_meta_description=variant_content.seo_meta_description,
            keywords=variant_content.keywords,
            quality_score=variant_quality.overall,
            quality_breakdown=variant_quality.model_dump(),
            factual_warnings=[w.model_dump() for w in variant_warnings],
            factual_warning_count=len(variant_warnings),
            agent_trace=variant_trace,
            review_status="pending",
        )
        db.add(desc)
        await db.flush()
        if best_desc is None or variant_quality.overall > (best_desc.quality_score or 0):
            best_desc = desc

    desc = best_desc
    assert desc is not None

    logger.info(
        "Generated description id=%s product=%s provider=%s version=%d quality=%.2f gate=%s variants=%d regenerations=%d",
        desc.id, product_id, provider.provider_name, next_version, quality.overall,
        passes_gate, settings.variant_count, regeneration_attempts,
    )

    return GenerationResult(
        id=desc.id,
        product_id=product_id,
        version=desc.version,
        provider=provider.provider_name,
        model_id=provider.model_id,
        is_demo=is_demo,
        content=content,
        quality_score=quality.overall,
        quality_breakdown=quality,
        factual_warnings=warnings,
        factual_warning_count=len(warnings),
        agent_trace=best_trace,
        review_status="pending",
        created_at=desc.created_at,
    )
