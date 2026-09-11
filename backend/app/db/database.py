"""Database layer. SQLite for MVP; PostgreSQL later = change DATABASE_URL only.

Uses a per-request Session (FastAPI Depends) plus a dedicated session factory
for background engines. SQLite needs check_same_thread=False + WAL for
concurrent monitor writes.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.db import models  # noqa: F401  (register tables)

    Base.metadata.create_all(bind=engine)
    _ensure_service_columns()


# Columns added after the first release. create_all() never alters an
# existing table, so long-lived dev DBs (and the SQLite file on disk) get
# lightweight ALTERs here; fresh DBs and Alembic-managed Postgres are no-ops.
_SERVICE_COLUMNS = {
    "repo_path_or_url": "VARCHAR(500) DEFAULT ''",
    "git_token_enc": "VARCHAR(1000) DEFAULT ''",
    "target_branch": "VARCHAR(120) DEFAULT ''",
    "workspace_frontend": "VARCHAR(200) DEFAULT ''",
    "workspace_backend": "VARCHAR(200) DEFAULT ''",
    "test_command": "VARCHAR(500) DEFAULT ''",
    "remediation_policy": "VARCHAR(20) DEFAULT ''",
    "published_url": "VARCHAR(500) DEFAULT ''",
    "client_api_key": "VARCHAR(64) DEFAULT ''",
    "deploy_webhook_url": "VARCHAR(500) DEFAULT ''",
}


def _ensure_service_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    try:
        with engine.begin() as conn:
            existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(services)").fetchall()}
            for col, ddl in _SERVICE_COLUMNS.items():
                if col not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE services ADD COLUMN {col} {ddl}")
    except Exception:
        pass  # best-effort: a fresh create_all already has everything
