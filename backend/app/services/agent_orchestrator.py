"""Four-agent generation orchestration and audit trace."""
from __future__ import annotations

import json
from typing import Any

from app.ai.base import AIProvider
from app.schemas.schemas import GeneratedContent, GenerationSettings, ProductResponse, QualityBreakdown
from app.services.factual_checker import run_factual_checks
from app.services.quality_evaluator import evaluate_quality


class ResearchNormalizationAgent:
    name = "Product Research and Normalization Agent"

    def run(self, product: ProductResponse, settings: GenerationSettings) -> dict[str, Any]:
        missing: list[str] = []
        verified_attributes: dict[str, Any] = {
            "name": product.name,
            "brand": product.brand,
            "category": product.category,
            "source": product.source_name,
        }
        for field, value in (
            ("material", product.material), ("color", product.color),
            ("weight", product.weight_kg), ("dimensions", product.dimensions_cm),
            ("price", product.price), ("quantity", product.quantity),
            ("original_description", product.original_description),
        ):
            if value in (None, "", [], {}): missing.append(field)
            else: verified_attributes[field] = value
        if product.features: verified_attributes["features"] = product.features
        else: missing.append("features")
        if product.specifications: verified_attributes["specifications"] = product.specifications
        else: missing.append("specifications")
        return {"agent": self.name, "status": "completed", "missing_fields": missing,
                "verified_attributes": verified_attributes,
                "rule": "Missing attributes are omitted; they are never invented."}


class ContentGenerationAgent:
    name = "Content Generation Agent"

    async def run(self, provider: AIProvider, product: ProductResponse, settings: GenerationSettings,
                  attempt: int) -> GeneratedContent:
        return await provider.generate(product, settings)


class QualityFactualVerificationAgent:
    name = "Quality and Factual Verification Agent"

    def run(self, product: ProductResponse, content: GeneratedContent,
            settings: GenerationSettings) -> tuple[list, QualityBreakdown]:
        warnings = run_factual_checks(product, content)
        quality = evaluate_quality(product, content, settings, warnings)
        return warnings, quality


class ContentImprovementAgent:
    name = "Content Improvement Agent"

    def run(self, warnings: list, quality: QualityBreakdown, settings: GenerationSettings) -> dict[str, Any]:
        feedback = "; ".join(
            f"Fix {warning.claim}: {warning.suggested_action or warning.explanation}"
            for warning in warnings[:5]
        )
        if not feedback:
            feedback = "Improve relevance, SEO coverage, readability, and source-backed consistency."
        return {"agent": self.name, "status": "feedback_ready",
                "feedback": feedback,
                "quality_snapshot": quality.model_dump(),
                "quality_threshold": settings.quality_threshold}


class AgentOrchestrator:
    """Coordinates specialist agents and records a reproducible audit trail."""

    def __init__(self):
        self.research = ResearchNormalizationAgent()
        self.generator = ContentGenerationAgent()
        self.verifier = QualityFactualVerificationAgent()
        self.improver = ContentImprovementAgent()

    async def run_variant(self, provider: AIProvider, product: ProductResponse,
                          settings: GenerationSettings, variant_index: int) -> dict[str, Any]:
        research = self.research.run(product, settings)
        attempts: list[dict[str, Any]] = []

        content = None
        warnings = []
        quality = None
        passes_gate = False

        for attempt in range(1, settings.max_regeneration_attempts + 2):
            attempt_settings = settings.model_copy(deep=True)
            if attempt > 1:
                improvement = self.improver.run(warnings, quality, settings)
                attempt_settings.category_instructions = (
                    f"{settings.category_instructions or ''} Quality-gate feedback for regeneration: "
                    f"{improvement['feedback']}"
                ).strip()

            content = await self.generator.run(provider, product, attempt_settings, attempt)
            warnings, quality = self.verifier.run(product, content, attempt_settings)
            has_factual_errors = any(warning.severity == "error" for warning in warnings)
            passes_gate = (
                quality.overall >= settings.quality_threshold
                and quality.factual_consistency >= min(7.0, settings.quality_threshold)
                and quality.relevance >= 6.0
                and not has_factual_errors
            )

            attempt_trace: dict[str, Any] = {
                "attempt": attempt,
                "quality_gate": "passed" if passes_gate else "failed",
                "quality": quality.model_dump(),
                "warnings": [warning.model_dump() for warning in warnings],
            }
            if not passes_gate and attempt <= settings.max_regeneration_attempts + 1:
                attempt_trace["improvement_feedback"] = self.improver.run(warnings, quality, settings)
            attempts.append(attempt_trace)
            if passes_gate:
                break

        final_trace = {
            "variant": variant_index + 1,
            "agents": [research, attempts],
            "research": research,
            "attempts": attempts,
            "passes_quality_gate": passes_gate,
            "regeneration_attempts": max(0, len(attempts) - 1),
        }
        assert content is not None and quality is not None
        return {"content": content, "warnings": warnings, "quality": quality,
                "passes_gate": passes_gate, "trace": final_trace}
