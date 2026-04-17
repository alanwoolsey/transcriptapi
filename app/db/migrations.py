from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import settings
from app.db.session import get_database_url, get_engine

MIGRATION_LOCK_ID = 868732145199


def run_migrations() -> None:
    database_url = get_database_url()
    if not database_url or not settings.run_db_migrations_on_startup:
        return

    engine = get_engine()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID})
        try:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID})
