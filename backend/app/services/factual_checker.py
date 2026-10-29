"""Deterministic factual consistency checks."""
from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.schemas import FactualWarning, GeneratedContent, ProductResponse

# ── Patterns for unsupported claims ──────────────────────────────────────────

_CERT_PATTERN = re.compile(
    r"\b(ISO\s*\d+|CE\s*certified|FDA\s*approved|UL\s*listed|RoHS|FCC|Energy\s*Star)\b",
    re.IGNORECASE,
)
_WARRANTY_PATTERN = re.compile(
    r"\b(\d+[-\s]?(year|month|day|yr)(\s+warranty)?|lifetime\s+warranty|guaranteed\s+for)\b",
    re.IGNORECASE,
)
_HEALTH_PATTERN = re.compile(
    r"\b(cures?|treats?|prevents?|heals?|clinically\s+(proven|tested)|doctor\s+recommended|"
    r"medically\s+(approved|certified)|boosts?\s+(immunity|metabolism|health)|"
    r"anti[-\s]?(aging|ageing)|reduces?\s+risk\s+of)\b",
    re.IGNORECASE,
)
_PERF_CLAIMS = re.compile(
    r"\b(fastest|world['\u2019s]?\s+best|industry['\u2019s]?\s+leading|#1\s+rated|"
    r"best[-\s]in[-\s]class|unbeatable|guaranteed\s+(performance|results))\b",
    re.IGNORECASE,
)

_NUMBER_PATTERN = re.compile(r"\b(\d[\d,]*\.?\d*)\s*(kg|g|lb|oz|mm|cm|m|inch|in|W|kW|V|A|mAh|GB|TB|GHz|MHz)\b")


def _extract_numbers(text: str) -> list[tuple[float, str]]:
    """Extract (value, unit) pairs from text."""
    results = []
    for m in _NUMBER_PATTERN.finditer(text):
        try:
            val = float(m.group(1).replace(",", ""))
            results.append((val, m.group(2)))
        except ValueError:
            pass
    return results


def _check_contradictions(
    product: ProductResponse,
    content: GeneratedContent,
) -> list[FactualWarning]:
    """Flag numeric claims that contradict source data."""
    warnings: list[FactualWarning] = []
    all_generated_text = " ".join([
        content.title, content.short_description,
        content.long_description, " ".join(content.feature_bullets),
    ])

    # Weight check
    if product.weight_kg is not None:
        for val, unit in _extract_numbers(all_generated_text):
            if unit in ("kg",) and abs(val - product.weight_kg) / max(product.weight_kg, 0.001) > 0.20:
                warnings.append(FactualWarning(
                    severity="error",
                    claim=f"Weight stated as {val} kg in generated content",
                    explanation=f"Source data specifies weight as {product.weight_kg} kg. Values differ by >20%.",
                    source_attribute="weight_kg",
                    suggested_action="Verify and correct the weight figure.",
                ))

    # Price check
    if product.price is not None:
        price_pattern = re.compile(r"\$\s*(\d[\d,]*\.?\d*)")
        for m in price_pattern.finditer(all_generated_text):
            try:
                stated_price = float(m.group(1).replace(",", ""))
                if abs(stated_price - product.price) / max(product.price, 0.01) > 0.05:
                    warnings.append(FactualWarning(
                        severity="error",
                        claim=f"Price stated as ${stated_price:.2f}",
                        explanation=f"Source price is {product.currency} {product.price:.2f}.",
                        source_attribute="price",
                        suggested_action="Remove or correct the price reference.",
                    ))
            except ValueError:
                pass

    return warnings


def _check_unsupported_claims(text: str) -> list[FactualWarning]:
    warnings: list[FactualWarning] = []

    for m in _CERT_PATTERN.finditer(text):
        warnings.append(FactualWarning(
            severity="warning",
            claim=m.group(0),
            explanation="Certification claim detected. Not found in source product data.",
            source_attribute=None,
            suggested_action="Remove certification claim or add it to verified product attributes.",
        ))

    for m in _WARRANTY_PATTERN.finditer(text):
        warnings.append(FactualWarning(
            severity="warning",
            claim=m.group(0),
            explanation="Warranty claim detected. Not found in source product data.",
            source_attribute=None,
            suggested_action="Remove warranty claim unless verified in source data.",
        ))

    for m in _HEALTH_PATTERN.finditer(text):
        warnings.append(FactualWarning(
            severity="error",
            claim=m.group(0),
            explanation="Health or medical claim detected. Such claims require regulatory verification.",
            source_attribute=None,
            suggested_action="Remove health/medical claims entirely.",
        ))

    for m in _PERF_CLAIMS.finditer(text):
        warnings.append(FactualWarning(
            severity="warning",
            claim=m.group(0),
            explanation="Superlative performance claim detected without source evidence.",
            source_attribute=None,
            suggested_action="Replace with specific, verifiable performance attributes.",
        ))

    return warnings


def _check_missing_fields(content: GeneratedContent) -> list[FactualWarning]:
    warnings: list[FactualWarning] = []
    if not content.title or len(content.title.strip()) < 3:
        warnings.append(FactualWarning(
            severity="error", claim="title", explanation="Title is empty or too short.",
            suggested_action="Regenerate with valid product data.",
        ))
    if not content.long_description or len(content.long_description.strip()) < 50:
        warnings.append(FactualWarning(
            severity="warning", claim="long_description",
            explanation="Description is very short (< 50 chars).",
            suggested_action="Check generation settings or product data completeness.",
        ))
    if not content.feature_bullets:
        warnings.append(FactualWarning(
            severity="info", claim="feature_bullets",
            explanation="No feature bullets generated.",
            suggested_action="Add product features to source data.",
        ))
    if not content.keywords:
        warnings.append(FactualWarning(
            severity="info", claim="keywords",
            explanation="No SEO keywords generated.",
            suggested_action="Provide target keywords in generation settings.",
        ))
    return warnings


_ATTRIBUTE_CLAIMS = {
    "waterproof": "waterproof",
    "water resistance": "water resistant|water resistance",
    "compatibility": "compatible with|compatibility",
    "material": "leather|stainless steel|titanium|cotton|nylon|silk",
    "certification": "certified|certification",
    "warranty": "warranty|guaranteed for",
}


def _check_unverified_attributes(product: ProductResponse, content: GeneratedContent) -> list[FactualWarning]:
    source_text = " ".join([
        product.name or "", product.original_description or "", product.category or "",
        " ".join(product.features or []), json.dumps(product.specifications or {}),
        product.material or "", product.color or "",
    ]).lower()
    all_text = " ".join([
        content.title, content.short_description, content.long_description,
        " ".join(content.feature_bullets),
    ]).lower()
    warnings: list[FactualWarning] = []
    for attribute, pattern in _ATTRIBUTE_CLAIMS.items():
        matches = re.search(pattern, all_text, re.IGNORECASE)
        if matches and not re.search(pattern, source_text, re.IGNORECASE):
            claim = matches.group(0)
            warnings.append(FactualWarning(
                severity="warning" if attribute != "warranty" else "error",
                claim=claim,
                explanation=f"Generated text mentions {attribute}, but the source product attributes do not verify it.",
                source_attribute=attribute,
                suggested_action=f"Remove the {attribute} claim or add verified source data before approval.",
            ))
    return warnings


def run_factual_checks(
    product: ProductResponse,
    content: GeneratedContent,
) -> list[FactualWarning]:
    """Run all deterministic factual consistency checks."""
    all_text = " ".join([
        content.title, content.short_description,
        content.long_description, " ".join(content.feature_bullets),
        content.seo_title, content.seo_meta_description,
        " ".join(content.keywords),
    ])

    warnings: list[FactualWarning] = []
    warnings.extend(_check_missing_fields(content))
    warnings.extend(_check_contradictions(product, content))
    warnings.extend(_check_unsupported_claims(all_text))
    warnings.extend(_check_unverified_attributes(product, content))

    # Deduplicate by claim text
    seen: set[str] = set()
    unique: list[FactualWarning] = []
    for w in warnings:
        key = w.claim.lower()[:80]
        if key not in seen:
            seen.add(key)
            unique.append(w)

    return unique
