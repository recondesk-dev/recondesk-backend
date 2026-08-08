"""Alembic environment — reads DATABASE_URL from the environment."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# this is the Alembic Config object, which provides access to the values within alembic.ini
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def get_url() -> str:
    url = (
        os.environ.get("SUPABASE_DATABASE_URL", "").strip()
        or os.environ.get("SUPABASE_DB_URL", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
    )
    if not url:
        raise RuntimeError(
            "Neither SUPABASE_DATABASE_URL nor DATABASE_URL is set. Add your Supabase Postgres URI to the environment "
            "(see .env.example), then run: alembic upgrade head"
        )
    return url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_num_dim=128,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from urllib.parse import urlparse
    url = get_url()
    try:
        host = urlparse(url).hostname or "(unknown)"
    except Exception:
        host = "(invalid)"
    print(f"Alembic env.py connecting to target DB host: {host}")

    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(128) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));"
            )
        )
        connection.execute(
            sa.text(
                "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128);"
            )
        )
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_num_dim=128,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
