from __future__ import annotations
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from db.models import Base

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Лёгкие миграции: {таблица: [(колонка, DDL-тип)]}.
# create_all не добавляет колонки в уже существующие таблицы,
# поэтому добавляем недостающие через ALTER TABLE вручную.
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "users": [
        ("closeness", "INTEGER DEFAULT 0"),
        ("pet_name", "VARCHAR(64)"),
    ],
}

def _run_migrations(conn) -> None:
    insp = inspect(conn)
    try:
        tables = set(insp.get_table_names())
    except Exception:
        tables = set()
    for table, columns in _MIGRATIONS.items():
        if table not in tables:
            continue  # create_all уже создал её с нужными колонками
        try:
            existing = {c["name"] for c in insp.get_columns(table)}
        except Exception:
            existing = set()
        for name, ddl in columns:
            if name in existing:
                continue
            try:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
            except Exception:
                pass  # колонка могла появиться параллельно - игнорируем

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_run_migrations)
