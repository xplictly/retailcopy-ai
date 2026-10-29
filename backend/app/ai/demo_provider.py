"""Demo/test AI provider — varied output, no API key required."""
from __future__ import annotations

import hashlib
import json
import random
import secrets

from app.ai.base import AIProvider
from app.schemas.schemas import GeneratedContent, GenerationSettings, ProductResponse

_ADJECTIVES = ["Premium", "Essential", "Superior", "Classic", "Advanced", "Refined", "Quality"]
_VERBS = ["Elevate", "Discover", "Experience", "Enjoy", "Transform"]


def _seed_from_product(product: ProductResponse) -> int:
    return int(hashlib.md5(product.id.encode()).hexdigest()[:8], 16)


class DemoProvider(AIProvider):
    """Deterministic provider for testing and demo mode. Never calls an external API."""

    @property
    def provider_name(self) -> str:
        return "demo"

    @property
    def model_id(self) -> str | None:
        return "demo-varied-v1"

    async def is_available(self) -> tuple[bool, str]:
        return True, "Demo mode is always available. No API key required."

    async def generate(
        self,
        product: ProductResponse,
        settings: GenerationSettings,
    ) -> GeneratedContent:
        rng = random.Random(_seed_from_product(product) + secrets.randbits(32))
        adj = rng.choice(_ADJECTIVES)
        verb = rng.choice(_VERBS)

        category = product.category or "Product"
        brand = product.brand or "Brand"
        name = product.name
        price_text = f"{product.currency} {product.price:.2f}" if product.price is not None else ""

        hooks = [
            f"{verb} everyday style with the {name}",
            f"Meet the {name}: an elevated choice for your {category.lower()} collection",
            f"Designed for confidence, the {name} brings practical appeal to the {category.lower()} range",
            f"A fresh take on the {category.lower()} category: discover the {name}",
        ]
        hook = rng.choice(hooks)
        title = f"{adj} {name} by {brand}"[:80]
        voice = settings.brand_voice or "professional"
        voice_openers = {
            "professional": "with clear, reliable product information",
            "friendly": "in a warm, approachable way that makes browsing easy",
            "premium": "with refined positioning and elevated product presentation",
            "technical": "with precise, specification-led product information",
            "playful": "with energetic, memorable product storytelling",
        }
        short = f"{hook}. {brand} presents this {category.lower()} {voice_openers[voice]} and a consistent brand identity."

        source_facts: list[str] = []
        if product.original_description:
            source_facts.append(product.original_description.strip())
        if product.features:
            source_facts.append("Known features: " + "; ".join(str(f) for f in product.features[:4]) + ".")
        if product.specifications:
            specs = "; ".join(f"{key}: {value}" for key, value in list(product.specifications.items())[:4])
            source_facts.append("Available specifications: " + specs + ".")
        if product.material:
            source_facts.append(f"Material: {product.material}.")
        if product.color:
            source_facts.append(f"Color: {product.color}.")
        if product.weight_kg is not None:
            source_facts.append(f"Weight: {product.weight_kg:g} kg.")
        if product.dimensions_cm:
            source_facts.append(f"Dimensions: {product.dimensions_cm}.")

        category_name = category.lower()
        category_guidance: list[str] = []
        if any(token in category_name for token in ("watch", "accessories", "jewelery", "jewelry")):
            category_guidance = [value for value in source_facts if any(k in value.lower() for k in ("material", "water", "resistan", "dimension", "strap", "movement"))]
        elif any(token in category_name for token in ("cloth", "shirt", "dress", "tops", "fashion", "wear")):
            category_guidance = [value for value in source_facts if any(k in value.lower() for k in ("material", "fabric", "fit", "size", "color", "care"))]
        elif any(token in category_name for token in ("phone", "laptop", "electronics", "computer", "device")):
            category_guidance = [value for value in source_facts if any(k in value.lower() for k in ("specif", "processor", "battery", "camera", "memory", "storage", "connect"))]
        elif any(token in category_name for token in ("food", "grocery", "beauty", "skincare")):
            category_guidance = [value for value in source_facts if any(k in value.lower() for k in ("ingredient", "nutrition", "quantity", "weight", "allergen"))]
        fact_text = " ".join(category_guidance or source_facts)
        positioning = rng.choice([
            "It is presented as an approachable option that balances appearance, usability, and product clarity.",
            "Its straightforward presentation makes it easy to compare the option with other products in the same category.",
            "The product pairs a recognizable retail profile with information that helps shoppers make a considered choice.",
            "From initial browsing to final selection, the description keeps the product identity and available attributes front and center.",
        ])
        price_text_paragraph = f"The listed price is {price_text}. " if price_text else ""
        audience = settings.target_audience or "everyday shoppers"
        long_desc = (
            f"{hook}. The {name} from {brand} is a {category.lower()} product intended for {audience}. "
            f"{positioning} "
            f"{fact_text} {price_text_paragraph}"
            f"Explore the available details before purchase, especially where a specific feature, size, or compatibility may matter to your needs.\n\n"
            f"[DEMO COPY — varied locally from the imported product facts; live AI wording can be enabled with a configured provider.]"
        ).strip()

        bullets = [
            f"{adj} {category.lower()} option from {brand}",
            f"Designed for {audience}",
            f"Explore the available {category.lower()} product details",
        ]
        if product.features:
            bullets += [f for f in product.features[:2] if f]

        kws = list(settings.seo_keywords or [])
        if product.target_keywords:
            kws += product.target_keywords[:3]
        if not kws:
            kws = [name, category, brand]

        seo_title = f"Buy {name} — {adj} {category} | {brand}"[:70]
        seo_meta = (
            f"Shop the {name} by {brand}. {short[:100]}"
        )[:160]

        return GeneratedContent(
            title=title,
            short_description=short,
            long_description=long_desc,
            feature_bullets=bullets[:6],
            seo_title=seo_title,
            seo_meta_description=seo_meta,
            keywords=list(dict.fromkeys(kws))[:10],
        )
