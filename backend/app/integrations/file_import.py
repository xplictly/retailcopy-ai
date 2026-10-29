"""CSV and JSON import + synthetic dataset generation."""
from __future__ import annotations

import io
import json
import logging
import random
import uuid
from typing import Any

import pandas as pd

from app.schemas.schemas import ProductCreate

logger = logging.getLogger(__name__)

SOURCE_NAME_CSV = "csv_import"
SOURCE_NAME_JSON = "json_import"
SOURCE_NAME_SYNTHETIC = "synthetic"

# ── Templates ─────────────────────────────────────────────────────────────────

CSV_TEMPLATE_HEADERS = [
    "name", "brand", "category", "quantity", "original_description",
    "features", "material", "color", "weight_kg", "price", "currency",
    "target_keywords", "image_url",
]

JSON_TEMPLATE = [
    {
        "name": "Example Product Name",
        "brand": "Brand Name",
        "category": "Category",
        "quantity": 25,
        "original_description": "A brief description of the product.",
        "features": ["Feature 1", "Feature 2"],
        "material": "Material",
        "color": "Color",
        "weight_kg": 0.5,
        "price": 29.99,
        "currency": "USD",
        "target_keywords": ["keyword1", "keyword2"],
        "image_url": "https://example.com/image.jpg",
    }
]

# ── Synthetic Data ────────────────────────────────────────────────────────────

_SYNTHETIC_PRODUCTS = [
    # Electronics
    {"name": "ProVision X1 Laptop", "brand": "TechCore", "category": "laptops", "price": 899.99, "color": "Space Gray", "weight_kg": 1.4, "features": ["Intel Core i5", "8GB RAM", "512GB SSD", "14-inch FHD display"], "target_keywords": ["laptop", "ultrabook", "portable"]},
    {"name": "NovaBud Pro Earbuds", "brand": "SoundWave", "category": "smartphones", "price": 149.99, "color": "White", "weight_kg": 0.05, "features": ["Active Noise Cancellation", "30hr battery", "IPX4 water resistant"], "target_keywords": ["earbuds", "wireless", "noise cancelling"]},
    {"name": "SwiftCharge 65W Adapter", "brand": "PowerUp", "category": "automotive", "price": 39.99, "color": "Black", "features": ["65W GaN technology", "Universal compatibility", "Foldable prongs"], "target_keywords": ["charger", "USB-C", "fast charge"]},
    {"name": "ClearView 27\" Monitor", "brand": "VisualPro", "category": "laptops", "price": 329.00, "color": "Black", "weight_kg": 4.2, "features": ["4K UHD", "IPS panel", "HDR400", "Height adjustable"], "target_keywords": ["monitor", "4K", "display"]},
    {"name": "MechType Pro Keyboard", "brand": "KeyMaster", "category": "laptops", "price": 119.00, "color": "White", "weight_kg": 0.9, "features": ["Mechanical switches", "RGB backlit", "USB-C connection"], "target_keywords": ["keyboard", "mechanical", "gaming"]},
    # Fashion
    {"name": "UrbanEdge Slim Jeans", "brand": "DenimCo", "category": "tops", "price": 59.99, "color": "Indigo Blue", "material": "98% Cotton, 2% Elastane", "features": ["Slim fit", "Mid-rise", "Five-pocket design"], "target_keywords": ["jeans", "slim", "denim"]},
    {"name": "LuxeSoft Cashmere Sweater", "brand": "WoolHaven", "category": "tops", "price": 189.00, "color": "Cream", "material": "100% Cashmere", "features": ["Crew neck", "Ribbed cuffs", "Fine-knit", "Dry clean only"], "target_keywords": ["sweater", "cashmere", "luxury"]},
    {"name": "AquaFlex Running Shoes", "brand": "SpeedStep", "category": "tops", "price": 99.99, "color": "Neon Green", "features": ["Breathable mesh upper", "Cushioned sole", "Anti-slip grip"], "target_keywords": ["running shoes", "athletic", "sport"]},
    {"name": "SunGuard UV Sunglasses", "brand": "ClearVision", "category": "sunglasses", "price": 74.99, "color": "Tortoise", "material": "Acetate frame, Polycarbonate lens", "features": ["UV400 protection", "Polarized", "Lightweight"], "target_keywords": ["sunglasses", "UV protection", "polarized"]},
    {"name": "VelvetTouch Evening Dress", "brand": "EleganceWear", "category": "womens-dresses", "price": 149.00, "color": "Midnight Black", "material": "95% Polyester, 5% Spandex", "features": ["A-line silhouette", "V-neck", "Floor length", "Hidden zipper"], "target_keywords": ["evening dress", "formal", "gown"]},
    # Home & Living
    {"name": "ZenBreeze Aromatherapy Diffuser", "brand": "NaturalHome", "category": "home-decoration", "price": 44.99, "color": "White", "features": ["500ml capacity", "7 LED colors", "Auto shut-off", "Ultrasonic"], "target_keywords": ["diffuser", "aromatherapy", "essential oil"]},
    {"name": "CozyNest Memory Foam Pillow", "brand": "SleepWell", "category": "furniture", "price": 54.99, "color": "White", "weight_kg": 0.8, "features": ["Ergonomic design", "Cooling gel layer", "Hypoallergenic cover"], "target_keywords": ["pillow", "memory foam", "sleep"]},
    {"name": "BrightLight LED Desk Lamp", "brand": "LuminaDesk", "category": "lighting", "price": 39.99, "color": "Silver", "features": ["5 brightness levels", "Color temperature control", "USB charging port", "Touch control"], "target_keywords": ["desk lamp", "LED", "study light"]},
    {"name": "GreenThumb Plant Pot Set", "brand": "TerraStyle", "category": "home-decoration", "price": 29.99, "color": "Terracotta", "material": "Ceramic", "features": ["Set of 3", "Drainage holes", "Saucers included"], "target_keywords": ["plant pot", "ceramic", "indoor garden"]},
    {"name": "ModernGrid Wall Shelf", "brand": "SpaceDesign", "category": "furniture", "price": 49.99, "color": "Black", "material": "Metal & MDF", "features": ["4 shelves", "Easy installation", "Weight capacity 15kg"], "target_keywords": ["wall shelf", "storage", "modern"]},
    # Beauty & Personal Care
    {"name": "RadiantGlow Vitamin C Serum", "brand": "GlowLab", "category": "skincare", "price": 34.99, "features": ["10% Vitamin C", "Hyaluronic Acid", "30ml", "Dermatologically tested"], "target_keywords": ["vitamin C serum", "brightening", "skincare"]},
    {"name": "PureSilk Facial Cleanser", "brand": "CleanBeauty", "category": "skincare", "price": 19.99, "features": ["Sulfate-free", "Suitable for sensitive skin", "150ml", "pH balanced"], "target_keywords": ["cleanser", "face wash", "gentle"]},
    {"name": "VelvetSmooth Body Lotion", "brand": "SkinLux", "category": "skincare", "price": 16.99, "color": "Cream", "features": ["Shea butter", "Vitamin E", "24hr hydration", "200ml"], "target_keywords": ["body lotion", "moisturizer", "hydrating"]},
    {"name": "FreshMint Charcoal Toothpaste", "brand": "OralCare", "category": "skincare", "price": 8.99, "features": ["Activated charcoal", "Fluoride-free", "Whitening", "100g"], "target_keywords": ["toothpaste", "charcoal", "whitening"]},
    {"name": "LushLocks Hair Mask", "brand": "HairPro", "category": "skincare", "price": 22.99, "features": ["Argan oil", "Deep conditioning", "For damaged hair", "250ml"], "target_keywords": ["hair mask", "conditioning", "argan oil"]},
    # Food & Groceries
    {"name": "OrganicBlend Ground Coffee", "brand": "BrewMaster", "category": "groceries", "price": 14.99, "weight_kg": 0.25, "features": ["100% Arabica beans", "Medium roast", "Fair Trade certified", "Vacuum sealed"], "target_keywords": ["coffee", "organic", "arabica"]},
    {"name": "WildHarvest Honey 500g", "brand": "NaturePure", "category": "groceries", "price": 12.99, "weight_kg": 0.5, "features": ["Raw unfiltered", "Wildflower blend", "No additives"], "target_keywords": ["honey", "raw honey", "natural sweetener"]},
    {"name": "ProGain Whey Protein Powder", "brand": "FitFuel", "category": "groceries", "price": 49.99, "weight_kg": 1.0, "color": "Chocolate", "features": ["25g protein per serving", "Low sugar", "BCAA enriched", "30 servings"], "target_keywords": ["protein powder", "whey", "fitness"]},
    {"name": "AncientGrain Quinoa 1kg", "brand": "HarvestFields", "category": "groceries", "price": 8.99, "weight_kg": 1.0, "features": ["Complete protein", "Gluten-free", "Organic", "Pre-washed"], "target_keywords": ["quinoa", "superfood", "gluten-free"]},
    {"name": "CrunchPerfect Almond Butter", "brand": "NutButter", "category": "groceries", "price": 9.99, "weight_kg": 0.35, "features": ["100% almonds", "No added sugar", "High protein", "Crunchy texture"], "target_keywords": ["almond butter", "nut butter", "protein"]},
    # Fragrances
    {"name": "Midnight Oud Eau de Parfum", "brand": "MaisonFragrance", "category": "fragrances", "price": 89.99, "features": ["Top: Bergamot, Saffron", "Middle: Oud, Rose", "Base: Amber, Musk", "50ml", "Long-lasting"], "target_keywords": ["perfume", "oud", "oriental fragrance"]},
    {"name": "CitrusBurst Cologne", "brand": "FreshScent", "category": "fragrances", "price": 49.99, "features": ["Top: Lemon, Orange", "Middle: Jasmine", "Base: Cedar, Sandalwood", "75ml"], "target_keywords": ["cologne", "citrus", "fresh"]},
    {"name": "FloralBloom Perfume", "brand": "GardenEau", "category": "fragrances", "price": 69.99, "features": ["Rose", "Peony", "White Musk", "100ml spray"], "target_keywords": ["floral perfume", "rose", "feminine"]},
    # Automotive
    {"name": "ProGrip Dash Mount Holder", "brand": "AutoMate", "category": "automotive", "price": 24.99, "color": "Black", "material": "ABS Plastic", "features": ["360° rotation", "One-touch mechanism", "Universal fit", "Dashboard/windshield mount"], "target_keywords": ["phone mount", "car holder", "dashboard"]},
    {"name": "CrystalView Car Air Freshener", "brand": "FreshDrive", "category": "automotive", "price": 12.99, "features": ["30-day fragrance", "Non-toxic formula", "Clip-on vent mount", "Ocean breeze scent"], "target_keywords": ["car freshener", "air freshener", "auto"]},
    # Sports
    {"name": "FlexCore Yoga Mat", "brand": "ZenFit", "category": "tops", "price": 39.99, "color": "Purple", "material": "Natural Rubber", "weight_kg": 1.5, "dimensions_cm": "183L x 61W x 0.6D cm", "features": ["Non-slip surface", "6mm thickness", "Eco-friendly", "Carry strap included"], "target_keywords": ["yoga mat", "exercise mat", "non-slip"]},
    {"name": "AdjustPro Dumbbell Set", "brand": "IronForce", "category": "furniture", "price": 199.99, "color": "Black", "features": ["Adjustable 5-25kg", "Space-saving design", "Rubber coated plates", "Quick-select dial"], "target_keywords": ["dumbbell", "adjustable weights", "home gym"]},
    # Tech Accessories
    {"name": "SlimShell iPhone Case", "brand": "ProtectX", "category": "smartphones", "price": 19.99, "color": "Clear", "material": "TPU", "features": ["Military-grade drop protection", "Wireless charging compatible", "Slim profile 1.5mm"], "target_keywords": ["phone case", "iPhone case", "protection"]},
    {"name": "SmartTrack Fitness Band", "brand": "HealthPulse", "category": "smartphones", "price": 79.99, "color": "Black", "features": ["Heart rate monitor", "Sleep tracking", "5-day battery", "Water resistant IP67", "OLED display"], "target_keywords": ["fitness tracker", "smartband", "health monitor"]},
    {"name": "PortaHub USB-C 7-in-1", "brand": "ConnectAll", "category": "automotive", "price": 49.99, "color": "Silver", "features": ["4K HDMI", "USB-A 3.0 x2", "SD/MicroSD reader", "100W PD charging"], "target_keywords": ["USB hub", "USB-C hub", "multiport"]},
    # Kitchen
    {"name": "SpiceMaster Mortar & Pestle", "brand": "CuisineCraft", "category": "home-decoration", "price": 34.99, "color": "Granite", "material": "Natural Granite", "weight_kg": 1.8, "features": ["Unpolished interior", "Non-porous", "Dishwasher safe base"], "target_keywords": ["mortar pestle", "spice grinder", "kitchen"]},
    {"name": "EcoBrew Reusable Coffee Filter", "brand": "GreenBrew", "category": "groceries", "price": 11.99, "color": "Gold", "material": "Stainless Steel", "features": ["Fits all drip machines", "Permanent filter", "BPA-free"], "target_keywords": ["coffee filter", "reusable", "eco-friendly"]},
    # Toys & Games
    {"name": "BuildWorld Mega Blocks 500pc", "brand": "BrickFun", "category": "home-decoration", "price": 34.99, "color": "Multicolor", "features": ["500 pieces", "Compatible with major brands", "Ages 6+", "Storage box included"], "target_keywords": ["building blocks", "LEGO compatible", "toys"]},
    {"name": "PixelArt Drawing Tablet", "brand": "CreativePad", "category": "laptops", "price": 89.99, "color": "Black", "features": ["8192 pressure levels", "Wireless", "Compatible Windows/Mac/Android", "8x5 inch active area"], "target_keywords": ["drawing tablet", "graphic tablet", "digital art"]},
    # Stationery
    {"name": "InkFlow Fountain Pen Set", "brand": "ScriptMaster", "category": "tops", "price": 44.99, "color": "Midnight Blue", "material": "Brass barrel, Steel nib", "features": ["Medium nib", "Converter included", "Gift box"], "target_keywords": ["fountain pen", "writing", "premium pen"]},
    {"name": "NoteSync Smart Notebook", "brand": "DigiWrite", "category": "tops", "price": 29.99, "color": "Black", "features": ["200 reusable pages", "Scan with app", "Waterproof pages", "A5 size"], "target_keywords": ["smart notebook", "reusable notebook", "digital"]},
    # Additional to reach 50+
    {"name": "ProSound Bluetooth Speaker", "brand": "AudioMax", "category": "smartphones", "price": 79.99, "color": "Blue", "features": ["360° sound", "12hr battery", "IPX7 waterproof", "Wireless pairing"], "target_keywords": ["bluetooth speaker", "portable speaker", "waterproof"]},
    {"name": "GlassShield Screen Protector", "brand": "ClearGuard", "category": "smartphones", "price": 12.99, "color": "Clear", "material": "Tempered Glass", "features": ["9H hardness", "Anti-fingerprint", "Easy application kit"], "target_keywords": ["screen protector", "tempered glass", "phone"]},
    {"name": "WireFree Charging Pad", "brand": "ChargeEase", "category": "smartphones", "price": 24.99, "color": "White", "features": ["15W fast wireless", "Multi-device compatible", "LED indicator", "Slim 7mm"], "target_keywords": ["wireless charger", "charging pad", "Qi"]},
    {"name": "ThermaBreeze Insulated Bottle", "brand": "HydroLife", "category": "groceries", "price": 29.99, "color": "Matte Black", "material": "18/8 Stainless Steel", "weight_kg": 0.4, "features": ["500ml capacity", "24hr cold / 12hr hot", "Leak-proof lid", "BPA-free"], "target_keywords": ["water bottle", "insulated bottle", "travel"]},
    {"name": "CloudComfort Slippers", "brand": "CozyStep", "category": "tops", "price": 34.99, "color": "Grey", "material": "Memory foam + Plush", "features": ["Non-slip sole", "Machine washable", "Indoor/outdoor use", "Open toe"], "target_keywords": ["slippers", "memory foam", "comfort"]},
    {"name": "BioActive Probiotic Capsules", "brand": "WellnessPlus", "category": "groceries", "price": 27.99, "features": ["10 billion CFU", "6 strains", "60 capsules", "Shelf-stable"], "target_keywords": ["probiotic", "gut health", "supplement"]},
    {"name": "LensFlare Camera Tripod", "brand": "ShootPro", "category": "automotive", "price": 54.99, "color": "Black", "material": "Aluminum Alloy", "weight_kg": 1.2, "features": ["67\" max height", "360° pan head", "Quick release plate", "Compact fold"], "target_keywords": ["camera tripod", "photography", "video"]},
    {"name": "AeroFit Jump Rope", "brand": "CardioKing", "category": "tops", "price": 14.99, "color": "Red", "features": ["Adjustable length 3m", "Ball bearing handles", "Foam grips", "Carry bag"], "target_keywords": ["jump rope", "skipping rope", "cardio"]},
    {"name": "PocketLens 10x Macro Clip", "brand": "PhotoSnap", "category": "smartphones", "price": 19.99, "color": "Silver", "material": "Aluminum", "features": ["Universal clip", "10x magnification", "HD optical glass", "LED ring light"], "target_keywords": ["macro lens", "phone lens", "photography"]},
    {"name": "SilkSoft Bamboo Bed Sheets", "brand": "DreamLinen", "category": "furniture", "price": 69.99, "color": "White", "material": "100% Bamboo", "features": ["400 thread count", "King size", "Temperature regulating", "Machine washable"], "target_keywords": ["bed sheets", "bamboo", "bedding"]},
    {"name": "NaturalBoost Collagen Powder", "brand": "PureVitals", "category": "groceries", "price": 39.99, "weight_kg": 0.3, "features": ["Hydrolyzed collagen", "Unflavored", "30 servings", "Mixes easily"], "target_keywords": ["collagen", "protein", "supplement"]},
    {"name": "FlexiDesk Laptop Stand", "brand": "ErgoWork", "category": "laptops", "price": 34.99, "color": "Silver", "material": "Aluminum", "features": ["6 height settings", "Foldable", "Cable management", "Fits 10-17\" laptops"], "target_keywords": ["laptop stand", "ergonomic", "desk accessory"]},
]


def generate_synthetic_products(count: int = 60) -> list[ProductCreate]:
    """Generate labeled synthetic product records."""
    products = []
    rng = random.Random(42)  # Deterministic

    for i, tmpl in enumerate(_SYNTHETIC_PRODUCTS[:count]):
        product = ProductCreate(
            source_name=SOURCE_NAME_SYNTHETIC,
            external_id=f"synth-{i+1:04d}",
            name=tmpl["name"],
            brand=tmpl.get("brand"),
            category=tmpl.get("category"),
            price=tmpl.get("price"),
            currency="USD",
            color=tmpl.get("color"),
            material=tmpl.get("material"),
            weight_kg=tmpl.get("weight_kg"),
            quantity=rng.randint(5, 250),
            dimensions_cm=tmpl.get("dimensions_cm"),
            features=tmpl.get("features"),
            target_keywords=tmpl.get("target_keywords"),
            original_description=f"[SYNTHETIC] {tmpl['name']} by {tmpl.get('brand', 'Unknown')}. "
                                  f"Category: {tmpl.get('category', 'General')}.",
            is_synthetic=True,
        )
        products.append(product)

    return products


# ── CSV/JSON Import ───────────────────────────────────────────────────────────

class ImportError(Exception):
    pass


def _parse_list_field(val: Any) -> list[str] | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        return [v.strip() for v in val.split("|")]
    return None


def _parse_int(val: Any) -> int | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return max(0, int(float(val)))
    except (ValueError, TypeError):
        return None


def _parse_float(val: Any) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def validate_and_parse_csv(
    content: bytes,
    source_name: str = SOURCE_NAME_CSV,
) -> tuple[list[ProductCreate], list[str]]:
    """Parse and validate CSV file. Returns (products, errors)."""
    errors: list[str] = []
    products: list[ProductCreate] = []

    try:
        df = pd.read_csv(io.BytesIO(content), dtype=str, na_values=["", "NA", "N/A"])
    except Exception as exc:
        raise ImportError(f"CSV parse error: {exc}")

    required_cols = {"name"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ImportError(f"CSV missing required columns: {missing}")

    for idx, row in df.iterrows():
        row_num = int(idx) + 2  # +2 for header and 0-indexing
        name = str(row.get("name", "")).strip()
        if not name or name.lower() in ("nan", "none"):
            errors.append(f"Row {row_num}: Missing required field 'name'. Skipped.")
            continue
        try:
            product = ProductCreate(
                source_name=source_name,
                external_id=f"csv-{row_num}",
                name=name,
                brand=str(row.get("brand", "")).strip() or None,
                category=str(row.get("category", "")).strip() or None,
                original_description=str(row.get("original_description", "")).strip() or None,
                features=_parse_list_field(row.get("features")),
                material=str(row.get("material", "")).strip() or None,
                color=str(row.get("color", "")).strip() or None,
                weight_kg=_parse_float(row.get("weight_kg")),
                quantity=_parse_int(row.get("quantity")),
                price=_parse_float(row.get("price")),
                currency=str(row.get("currency", "USD")).strip() or "USD",
                target_keywords=_parse_list_field(row.get("target_keywords")),
                image_url=str(row.get("image_url", "")).strip() or None,
                is_synthetic=False,
            )
            products.append(product)
        except Exception as exc:
            errors.append(f"Row {row_num}: Validation error — {exc}. Skipped.")

    return products, errors


def validate_and_parse_json(
    content: bytes,
    source_name: str = SOURCE_NAME_JSON,
) -> tuple[list[ProductCreate], list[str]]:
    """Parse and validate JSON file. Returns (products, errors)."""
    errors: list[str] = []
    products: list[ProductCreate] = []

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ImportError(f"JSON parse error: {exc}")

    if isinstance(data, dict):
        data = data.get("products", [data])

    if not isinstance(data, list):
        raise ImportError("JSON must be an array of product objects or {\"products\": [...]}.")

    for idx, item in enumerate(data):
        item_num = idx + 1
        if not isinstance(item, dict):
            errors.append(f"Item {item_num}: Not an object. Skipped.")
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            errors.append(f"Item {item_num}: Missing 'name'. Skipped.")
            continue
        try:
            product = ProductCreate(
                source_name=source_name,
                external_id=str(item.get("id", f"json-{item_num}")),
                name=name,
                brand=item.get("brand"),
                category=item.get("category"),
                original_description=item.get("original_description") or item.get("description"),
                features=item.get("features"),
                specifications=item.get("specifications"),
                material=item.get("material"),
                color=item.get("color"),
                weight_kg=_parse_float(item.get("weight_kg")),
                quantity=_parse_int(item.get("quantity")),
                dimensions_cm=item.get("dimensions_cm"),
                price=_parse_float(item.get("price")),
                currency=item.get("currency", "USD"),
                target_keywords=item.get("target_keywords"),
                image_url=item.get("image_url"),
                raw_source_data=item,
                is_synthetic=False,
            )
            products.append(product)
        except Exception as exc:
            errors.append(f"Item {item_num} ('{name}'): Validation error — {exc}. Skipped.")

    return products, errors


def generate_csv_template() -> bytes:
    """Generate a downloadable CSV template."""
    rows = [
        {
            "name": "Example Wireless Mouse",
            "brand": "TechBrand",
            "category": "electronics",
            "original_description": "Ergonomic wireless mouse with precision tracking.",
            "features": "Wireless|2.4GHz|1600 DPI|USB receiver",
            "material": "ABS Plastic",
            "color": "Black",
            "weight_kg": "0.1",
            "price": "29.99",
            "currency": "USD",
            "target_keywords": "wireless mouse|ergonomic|office",
            "image_url": "https://example.com/mouse.jpg",
        },
    ]
    df = pd.DataFrame(rows, columns=CSV_TEMPLATE_HEADERS)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def generate_json_template() -> bytes:
    """Generate a downloadable JSON template."""
    return json.dumps({"products": JSON_TEMPLATE}, indent=2).encode()
