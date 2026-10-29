"""Import API router."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.database import get_db
from app.integrations import dummyjson, open_food_facts, file_import
from app.schemas.schemas import ImportResult
from app.services.product_service import bulk_import_products

router = APIRouter(prefix="/import", tags=["import"])
logger = logging.getLogger(__name__)
_settings = get_settings()

DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/dummyjson", response_model=ImportResult)
async def import_from_dummyjson(
    db: DB,
    max_records: int = Query(default=100, ge=1, le=500),
    page_size: int = Query(default=30, ge=1, le=100),
):
    """Fetch and import products from DummyJSON with real pagination."""
    try:
        products = await dummyjson.fetch_all_products(
            max_records=max_records, page_size=page_size
        )
    except Exception as exc:
        logger.error("DummyJSON fetch error: %s", exc)
        raise HTTPException(status_code=502, detail=f"DummyJSON fetch error: {exc}")

    imported_ids, skipped, errors = await bulk_import_products(products, db)
    return ImportResult(
        source="dummyjson",
        total_fetched=len(products),
        imported=len(imported_ids),
        skipped_duplicates=skipped,
        failed=len(errors),
        errors=errors[:20],
        product_ids=imported_ids,
    )


@router.post("/open-food-facts", response_model=ImportResult)
async def import_from_off(
    db: DB,
    query: str = Query(default="coffee", description="Search query"),
    max_records: int = Query(default=30, ge=1, le=100),
):
    """Search and import products from Open Food Facts."""
    try:
        products = await open_food_facts.search_products(
            query=query, page_size=min(max_records, 50)
        )
    except Exception as exc:
        logger.error("OFF search error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Open Food Facts error: {exc}")

    imported_ids, skipped, errors = await bulk_import_products(products[:max_records], db)
    return ImportResult(
        source="open_food_facts",
        total_fetched=len(products),
        imported=len(imported_ids),
        skipped_duplicates=skipped,
        failed=len(errors),
        errors=errors[:20],
        product_ids=imported_ids,
    )


@router.post("/synthetic", response_model=ImportResult)
async def import_synthetic(
    db: DB,
    count: int = Query(default=55, ge=1, le=100),
):
    """Import synthetic labeled dataset (clearly marked as non-live data)."""
    products = file_import.generate_synthetic_products(count=count)
    imported_ids, skipped, errors = await bulk_import_products(products, db)
    return ImportResult(
        source="synthetic",
        total_fetched=len(products),
        imported=len(imported_ids),
        skipped_duplicates=skipped,
        failed=len(errors),
        errors=errors[:10],
        product_ids=imported_ids,
    )


@router.post("/csv", response_model=ImportResult)
async def import_csv(
    db: DB,
    file: UploadFile = File(...),
):
    """Import products from a CSV file."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv file.")

    content = await file.read()
    max_bytes = _settings.import_file_max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {_settings.import_file_max_mb}MB limit.")

    try:
        products, parse_errors = file_import.validate_and_parse_csv(content)
    except file_import.ImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    imported_ids, skipped, import_errors = await bulk_import_products(products, db)
    all_errors = parse_errors + import_errors
    return ImportResult(
        source=f"csv:{file.filename}",
        total_fetched=len(products) + len(parse_errors),
        imported=len(imported_ids),
        skipped_duplicates=skipped,
        failed=len(parse_errors) + len(import_errors),
        errors=all_errors[:20],
        product_ids=imported_ids,
    )


@router.post("/json", response_model=ImportResult)
async def import_json(
    db: DB,
    file: UploadFile = File(...),
):
    """Import products from a JSON file."""
    content = await file.read()
    max_bytes = _settings.import_file_max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {_settings.import_file_max_mb}MB limit.")

    try:
        products, parse_errors = file_import.validate_and_parse_json(content)
    except file_import.ImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    imported_ids, skipped, import_errors = await bulk_import_products(products, db)
    all_errors = parse_errors + import_errors
    return ImportResult(
        source=f"json:{file.filename or 'upload'}",
        total_fetched=len(products) + len(parse_errors),
        imported=len(imported_ids),
        skipped_duplicates=skipped,
        failed=len(parse_errors) + len(import_errors),
        errors=all_errors[:20],
        product_ids=imported_ids,
    )


@router.get("/templates/csv")
async def download_csv_template():
    content = file_import.generate_csv_template()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=retailcopy_template.csv"},
    )


@router.get("/templates/json")
async def download_json_template():
    content = file_import.generate_json_template()
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=retailcopy_template.json"},
    )
