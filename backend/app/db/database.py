"""Database engine, session factory, and Base declarative class."""
from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

_settings = get_settings()

# Convert sync sqlite:/// URL to async aiosqlite URL
_db_url: str = _settings.database_url
if _db_url.startswith("sqlite:///"):
    _db_url = _db_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)

engine = create_async_engine(
    _db_url,
    echo=_settings.app_env == "development",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables and add columns needed by newer application versions."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        def add_application_columns(sync_conn):
            product_columns = {row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info(products)").fetchall()}
            if "quantity" not in product_columns:
                sync_conn.exec_driver_sql("ALTER TABLE products ADD COLUMN quantity INTEGER")

            description_columns = {row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info(generated_descriptions)").fetchall()}
            if "agent_trace" not in description_columns:
                sync_conn.exec_driver_sql("ALTER TABLE generated_descriptions ADD COLUMN agent_trace JSON")
        await conn.run_sync(add_application_columns)
