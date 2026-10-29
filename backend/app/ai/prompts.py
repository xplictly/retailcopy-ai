"""Prompt construction for category-aware product description generation."""
from __future__ import annotations

from app.schemas.schemas import GenerationSettings, ProductResponse

LENGTH_WORDS = {
    "short": "80-120",
    "medium": "150-250",
    "long": "300-450",
}

VOICE_GUIDANCE = {
    "professional": "Use clear, authoritative, and business-focused language. Be precise and factual.",
    "friendly": "Use warm, conversational, and approachable language. Speak directly to the customer.",
    "premium": "Use sophisticated, aspirational language that conveys luxury and exclusivity.",
    "technical": "Use precise technical terminology. Focus on specifications and performance details.",
    "playful": "Use energetic, fun, and creative language. Make it memorable and engaging.",
}

CATEGORY_HINTS = {
    "smartphones": "Emphasize performance, camera quality, battery life, and connectivity.",
    "laptops": "Highlight processor, RAM, storage, display quality, and battery life.",
    "fragrances": "Focus on scent notes, longevity, occasions, and the sensory experience.",
    "skincare": "Emphasize ingredients, skin benefits, skin type suitability, and texture.",
    "groceries": "Highlight freshness, taste, nutritional value, and usage suggestions.",
    "home-decoration": "Focus on aesthetic appeal, materials, dimensions, and versatility.",
    "furniture": "Emphasize quality, comfort, dimensions, materials, and style.",
    "tops": "Focus on fit, fabric, style versatility, and care instructions.",
    "womens-dresses": "Highlight silhouette, fabric, occasion, and styling options.",
    "sunglasses": "Focus on UV protection, frame material, style, and lens technology.",
    "automotive": "Highlight performance specs, compatibility, and durability.",
    "motorcycle": "Emphasize performance, safety features, and build quality.",
    "lighting": "Focus on brightness (lumens), color temperature, energy efficiency, and design.",
    "watches": "Highlight verified movement, case material, water resistance, dimensions, strap, and watch features; do not imply waterproofing without source evidence.",
    "mens-watches": "Highlight verified movement, case material, water resistance, dimensions, strap, and watch features.",
    "womens-watches": "Highlight verified movement, case material, water resistance, dimensions, strap, and watch features.",
    "clothing": "Highlight fabric, fit, silhouette, style, size information, and care instructions when available.",
    "tops": "Focus on fit, fabric, style versatility, size information, and care instructions.",
    "mens-shirts": "Highlight fabric, fit, collar/style, occasion, and care instructions when available.",
    "womens-dresses": "Highlight silhouette, fabric, occasion, and styling options.",
    "electronics": "Highlight verified specifications, compatibility, connectivity, supported features, and technical limitations.",
    "smartphones": "Emphasize performance, camera quality, battery life, connectivity, display, and only source-verified specifications.",
    "laptops": "Highlight processor, RAM, storage, display quality, graphics, connectivity, and battery life when stated.",
    "food": "Highlight ingredients, quantity, nutritional information, storage, allergens, and usage only when supplied by the source.",
    "groceries": "Highlight freshness, taste, nutritional value, quantity, allergens, and usage suggestions only when verified.",
    "beauty": "Highlight ingredients, skin or hair suitability, texture, use, quantity, and benefits supported by source data.",
    "skincare": "Emphasize ingredients, skin benefits, skin type suitability, and texture without unverified medical claims.",
    "default": "Highlight key product benefits, quality, and value proposition.",
}

SYSTEM_PROMPT = """You are an expert retail copywriter specializing in creating accurate, engaging, SEO-friendly product descriptions.

CRITICAL RULES:
1. Only describe features and attributes explicitly present in the product data provided.
2. Never invent specifications, certifications, warranties, health claims, or technical capabilities.
3. If an attribute is not provided, omit it rather than guessing.
4. Keep claims factual and verifiable.
5. Return ONLY valid JSON matching the exact schema below.

OUTPUT SCHEMA (return exactly this JSON structure):
{
  "title": "string (compelling product title, max 80 chars)",
  "short_description": "string (1-2 sentence hook)",
  "long_description": "string (detailed description)",
  "feature_bullets": ["string", "string", "string"],
  "seo_title": "string (SEO-optimized title, max 70 chars)",
  "seo_meta_description": "string (150-160 chars meta description)",
  "keywords": ["string", "string"]
}"""


def build_prompt(product: ProductResponse, settings: GenerationSettings) -> str:
    voice = settings.brand_voice or "professional"
    voice_guidance = VOICE_GUIDANCE.get(voice, VOICE_GUIDANCE["professional"])
    length_range = LENGTH_WORDS.get(settings.description_length or "medium", "150-250")

    # Category-aware hints
    category_key = (product.category or "default").lower().replace(" ", "-")
    category_hint = CATEGORY_HINTS.get(category_key, CATEGORY_HINTS["default"])

    # Build product data section
    product_lines = [f"Name: {product.name}"]
    if product.brand:
        product_lines.append(f"Brand: {product.brand}")
    if product.category:
        product_lines.append(f"Category: {product.category}")
    if product.price is not None:
        product_lines.append(f"Price: {product.currency} {product.price:.2f}")
    if product.original_description:
        product_lines.append(f"Original Description: {product.original_description}")
    if product.features:
        product_lines.append(f"Features: {', '.join(product.features)}")
    if product.specifications:
        specs = "; ".join(f"{k}: {v}" for k, v in product.specifications.items())
        product_lines.append(f"Specifications: {specs}")
    if product.material:
        product_lines.append(f"Material: {product.material}")
    if product.color:
        product_lines.append(f"Color: {product.color}")
    if product.weight_kg is not None:
        product_lines.append(f"Weight: {product.weight_kg} kg")
    if product.dimensions_cm:
        product_lines.append(f"Dimensions: {product.dimensions_cm}")
    if product.quantity is not None:
        product_lines.append(f"Quantity: {product.quantity}")
    if settings.seo_keywords:
        product_lines.append(f"Target SEO Keywords: {', '.join(settings.seo_keywords)}")
    if product.target_keywords:
        product_lines.append(f"Product Keywords: {', '.join(product.target_keywords)}")

    product_section = "\n".join(product_lines)

    audience_section = ""
    if settings.target_audience:
        audience_section = f"\nTarget Audience: {settings.target_audience}"

    category_section = ""
    if settings.category_instructions:
        category_section = f"\nSpecial Category Instructions: {settings.category_instructions}"
    else:
        category_section = f"\nCategory Guidance: {category_hint}"

    rag_section = ""
    if settings.rag_context:
        rag_section = f"\n\nRETRIEVED APPROVED REFERENCES:\n{settings.rag_context}\n\nRAG RULE: Use these references only for tone, structure, and category conventions. Do not transfer any claim, specification, or product fact from a reference unless it is present in PRODUCT DATA above."

    return f"""{SYSTEM_PROMPT}

PRODUCT DATA:
{product_section}{rag_section}

WRITING GUIDELINES:
- Brand Voice: {voice} — {voice_guidance}
- Long description word count: {length_range} words
- Language: {settings.language}{audience_section}{category_section}

Generate the JSON output now:"""
