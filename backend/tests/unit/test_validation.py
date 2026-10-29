"""Unit tests: factual checker and quality evaluator."""
from __future__ import annotations

import pytest
from datetime import datetime

from app.schemas.schemas import (
    FactualWarning,
    GeneratedContent,
    GenerationSettings,
    ProductResponse,
)
from app.services.factual_checker import run_factual_checks
from app.services.quality_evaluator import evaluate_quality


def _make_product(**kwargs) -> ProductResponse:
    defaults = dict(
        id="test-001",
        source_name="test",
        name="Titanium Pro Watch",
        brand="ChronoLux",
        category="accessories",
        price=299.99,
        currency="USD",
        features=["Titanium case", "100m water resistant", "GPS"],
        target_keywords=["watch", "titanium", "GPS"],
        is_synthetic=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    defaults.update(kwargs)
    return ProductResponse(**defaults)


def _make_content(**kwargs) -> GeneratedContent:
    defaults = dict(
        title="Titanium Pro Watch",
        short_description="Premium titanium watch with GPS.",
        long_description="The Titanium Pro Watch features a robust titanium case, GPS tracking, and 100m water resistance.",
        feature_bullets=["Titanium case", "GPS enabled", "100m water resistant"],
        seo_title="Buy Titanium Pro Watch | ChronoLux",
        seo_meta_description="Shop the Titanium Pro Watch. Premium GPS watch with titanium case.",
        keywords=["watch", "titanium", "GPS"],
    )
    defaults.update(kwargs)
    return GeneratedContent(**defaults)


class TestFactualChecker:
    def test_clean_content_no_warnings(self):
        product = _make_product()
        content = _make_content()
        warnings = run_factual_checks(product, content)
        # Should have no error-level warnings for clean content
        errors = [w for w in warnings if w.severity == "error"]
        assert len(errors) == 0

    def test_detects_certification_claim(self):
        product = _make_product()
        content = _make_content(
            long_description="ISO 9001 certified manufacturing process. CE certified product.",
        )
        warnings = run_factual_checks(product, content)
        cert_warnings = [w for w in warnings if "ISO" in w.claim or "CE" in w.claim]
        assert len(cert_warnings) > 0
        assert all(w.severity in ("warning", "error") for w in cert_warnings)

    def test_detects_warranty_claim(self):
        product = _make_product()
        content = _make_content(
            long_description="Comes with a 5-year warranty guaranteed.",
        )
        warnings = run_factual_checks(product, content)
        warranty_warnings = [w for w in warnings if "warranty" in w.claim.lower() or "year" in w.claim.lower()]
        assert len(warranty_warnings) > 0

    def test_detects_health_claim(self):
        product = _make_product(category="skincare")
        content = _make_content(
            long_description="Clinically proven to reduce wrinkles. Doctor recommended formula.",
        )
        warnings = run_factual_checks(product, content)
        health_warnings = [w for w in warnings if w.severity == "error"]
        assert len(health_warnings) > 0

    def test_detects_superlative_claim(self):
        product = _make_product()
        content = _make_content(
            long_description="The world's best watch with unbeatable performance.",
        )
        warnings = run_factual_checks(product, content)
        perf_warnings = [w for w in warnings if "best" in w.claim.lower() or "unbeatable" in w.claim.lower()]
        assert len(perf_warnings) > 0

    def test_detects_price_contradiction(self):
        product = _make_product(price=299.99)
        content = _make_content(
            long_description="This watch is priced at $99.99 making it a bargain.",
        )
        warnings = run_factual_checks(product, content)
        price_warnings = [w for w in warnings if "price" in w.claim.lower() or "99" in w.claim]
        assert len(price_warnings) > 0
        assert any(w.severity == "error" for w in price_warnings)

    def test_missing_title_is_error(self):
        product = _make_product()
        content = _make_content(title="")
        warnings = run_factual_checks(product, content)
        title_errors = [w for w in warnings if w.claim == "title"]
        assert len(title_errors) > 0
        assert title_errors[0].severity == "error"

    def test_empty_description_is_warning(self):
        product = _make_product()
        content = _make_content(long_description="Short")
        warnings = run_factual_checks(product, content)
        desc_warnings = [w for w in warnings if w.claim == "long_description"]
        assert len(desc_warnings) > 0

    def test_warnings_have_required_fields(self):
        product = _make_product()
        content = _make_content(long_description="ISO 9001 certified. 5-year warranty.")
        warnings = run_factual_checks(product, content)
        for w in warnings:
            assert w.severity in ("info", "warning", "error")
            assert len(w.claim) > 0
            assert len(w.explanation) > 0

    def test_no_duplicate_warnings(self):
        """Deduplication should prevent same claim appearing twice."""
        product = _make_product()
        content = _make_content(
            long_description="ISO 9001 certified ISO 9001 certified.",
        )
        warnings = run_factual_checks(product, content)
        iso_warnings = [w for w in warnings if "ISO" in w.claim]
        assert len(iso_warnings) == 1  # Deduplicated


class TestQualityEvaluator:
    def test_scores_in_range(self):
        product = _make_product()
        content = _make_content()
        settings = GenerationSettings()
        warnings = []
        breakdown = evaluate_quality(product, content, settings, warnings)
        for score in [breakdown.relevance, breakdown.factual_consistency,
                      breakdown.readability, breakdown.creativity,
                      breakdown.seo_coverage, breakdown.brand_adherence,
                      breakdown.overall]:
            assert 0 <= score <= 10, f"Score {score} out of range"

    def test_errors_reduce_factual_score(self):
        product = _make_product()
        content = _make_content()
        settings = GenerationSettings()

        no_warnings = []
        score_clean = evaluate_quality(product, content, settings, no_warnings)

        many_errors = [
            FactualWarning(severity="error", claim="test1", explanation="e1"),
            FactualWarning(severity="error", claim="test2", explanation="e2"),
            FactualWarning(severity="error", claim="test3", explanation="e3"),
        ]
        score_errors = evaluate_quality(product, content, settings, many_errors)

        assert score_errors.factual_consistency < score_clean.factual_consistency

    def test_keyword_coverage_improves_seo_score(self):
        product = _make_product(target_keywords=["titanium", "GPS", "watch"])
        content_with_kws = _make_content(keywords=["titanium", "GPS", "watch", "sport"])
        content_no_kws = _make_content(keywords=[])
        settings = GenerationSettings(seo_keywords=["titanium", "GPS"])
        warnings = []

        score_with = evaluate_quality(product, content_with_kws, settings, warnings)
        score_without = evaluate_quality(product, content_no_kws, settings, warnings)
        assert score_with.seo_coverage >= score_without.seo_coverage

    def test_overall_is_weighted_average(self):
        product = _make_product()
        content = _make_content()
        settings = GenerationSettings()
        warnings = []
        breakdown = evaluate_quality(product, content, settings, warnings)

        weights = {
            "relevance": 0.25, "factual_consistency": 0.25, "readability": 0.20,
            "creativity": 0.10, "seo_coverage": 0.10, "brand_adherence": 0.10,
        }
        expected_overall = (
            breakdown.relevance * weights["relevance"] +
            breakdown.factual_consistency * weights["factual_consistency"] +
            breakdown.readability * weights["readability"] +
            breakdown.creativity * weights["creativity"] +
            breakdown.seo_coverage * weights["seo_coverage"] +
            breakdown.brand_adherence * weights["brand_adherence"]
        )
        assert abs(breakdown.overall - expected_overall) < 0.01
