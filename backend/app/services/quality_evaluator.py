"""Quality evaluation metrics for generated descriptions.

Scoring formula (all dimensions 0-10):
  relevance         = keyword overlap + product attribute coverage
  factual_consistency = 10 - (2 * errors) - (1 * warnings) clamped to [0,10]
  readability       = sentence length score + vocabulary score
  creativity        = unique word ratio (normalized)
  seo_coverage      = target keyword presence ratio * 10
  brand_adherence   = voice marker match score
  overall           = weighted average of the six dimensions

Weights:
  relevance: 0.25, factual_consistency: 0.25, readability: 0.20,
  creativity: 0.10, seo_coverage: 0.10, brand_adherence: 0.10
"""
from __future__ import annotations

import math
import re
from typing import List

from app.schemas.schemas import (
    FactualWarning,
    GeneratedContent,
    GenerationSettings,
    ProductResponse,
    QualityBreakdown,
)

_WEIGHTS = {
    "relevance": 0.25,
    "factual_consistency": 0.25,
    "readability": 0.20,
    "creativity": 0.10,
    "seo_coverage": 0.10,
    "brand_adherence": 0.10,
}

_VOICE_MARKERS = {
    "professional": ["quality", "performance", "reliable", "designed", "precision"],
    "friendly": ["you", "your", "love", "enjoy", "perfect for"],
    "premium": ["luxury", "exclusive", "superior", "exceptional", "elevated"],
    "technical": ["specification", "frequency", "resistance", "capacity", "processor"],
    "playful": ["amazing", "awesome", "fun", "exciting", "fantastic"],
}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-z]+\b", text.lower())


def _score_relevance(product: ProductResponse, content: GeneratedContent) -> float:
    """Score how well the content covers product attributes."""
    full_text = " ".join([
        content.title, content.short_description,
        content.long_description, " ".join(content.feature_bullets),
    ]).lower()
    tokens = set(_tokenize(full_text))

    # Build source token set
    source_tokens: set[str] = set()
    for attr in [product.name, product.brand, product.category,
                 product.color, product.material]:
        if attr:
            source_tokens.update(_tokenize(attr))

    if product.features:
        for f in product.features:
            source_tokens.update(_tokenize(f))

    if product.target_keywords:
        for k in product.target_keywords:
            source_tokens.update(_tokenize(k))

    if not source_tokens:
        return 7.0  # No source tokens to compare against

    overlap = len(tokens & source_tokens) / len(source_tokens)
    return min(10.0, overlap * 12.0)  # Scale to 10


def _score_factual_consistency(warnings: list[FactualWarning]) -> float:
    errors = sum(1 for w in warnings if w.severity == "error")
    warns = sum(1 for w in warnings if w.severity == "warning")
    score = 10.0 - (errors * 2.0) - (warns * 0.5)
    return max(0.0, min(10.0, score))


def _score_readability(content: GeneratedContent) -> float:
    """Approximate Flesch-Kincaid readability: prefer 15-25 words/sentence."""
    text = content.long_description or content.short_description or ""
    if not text:
        return 5.0
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return 5.0
    words_per_sentence = [len(s.split()) for s in sentences]
    avg_wps = sum(words_per_sentence) / len(words_per_sentence)
    # Penalize very short or very long sentences
    ideal = 20.0
    deviation = abs(avg_wps - ideal)
    score = max(0.0, 10.0 - deviation * 0.3)
    return round(min(10.0, score), 2)


def _score_creativity(content: GeneratedContent) -> float:
    """Unique word ratio as proxy for vocabulary richness."""
    all_text = " ".join([
        content.title, content.short_description,
        content.long_description,
    ])
    tokens = _tokenize(all_text)
    if len(tokens) < 10:
        return 5.0
    ratio = len(set(tokens)) / len(tokens)
    return round(min(10.0, ratio * 12.0), 2)


def _score_seo_coverage(
    content: GeneratedContent,
    settings: GenerationSettings,
    product: ProductResponse,
) -> float:
    """Fraction of target keywords found in the generated content."""
    target_kws = list(settings.seo_keywords or []) + list(product.target_keywords or [])
    if not target_kws:
        # Fall back to checking generated keywords coverage in description
        if content.keywords:
            return 7.0
        return 5.0
    full_text = " ".join([
        content.title, content.long_description, " ".join(content.keywords),
    ]).lower()
    hits = sum(1 for kw in target_kws if kw.lower() in full_text)
    return round(min(10.0, (hits / len(target_kws)) * 10.0), 2)


def _score_brand_adherence(
    content: GeneratedContent,
    settings: GenerationSettings,
) -> float:
    voice = settings.brand_voice or "professional"
    markers = _VOICE_MARKERS.get(voice, _VOICE_MARKERS["professional"])
    all_text = " ".join([
        content.title, content.short_description, content.long_description,
    ]).lower()
    hits = sum(1 for m in markers if m in all_text)
    return round(min(10.0, (hits / len(markers)) * 10.0 + 4.0), 2)  # Base of 4


def evaluate_quality(
    product: ProductResponse,
    content: GeneratedContent,
    settings: GenerationSettings,
    warnings: list[FactualWarning],
) -> QualityBreakdown:
    r = _score_relevance(product, content)
    f = _score_factual_consistency(warnings)
    rd = _score_readability(content)
    c = _score_creativity(content)
    s = _score_seo_coverage(content, settings, product)
    b = _score_brand_adherence(content, settings)

    overall = (
        r * _WEIGHTS["relevance"]
        + f * _WEIGHTS["factual_consistency"]
        + rd * _WEIGHTS["readability"]
        + c * _WEIGHTS["creativity"]
        + s * _WEIGHTS["seo_coverage"]
        + b * _WEIGHTS["brand_adherence"]
    )

    return QualityBreakdown(
        relevance=round(r, 2),
        factual_consistency=round(f, 2),
        readability=round(rd, 2),
        creativity=round(c, 2),
        seo_coverage=round(s, 2),
        brand_adherence=round(b, 2),
        overall=round(overall, 2),
    )
