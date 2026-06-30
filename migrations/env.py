import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.core.db.session import Base
from app.core.models import host as _host  # noqa: F401
from app.core.models import ingestion_token as _ingestion_token  # noqa: F401
from app.core.models import maintenance as _maintenance  # noqa: F401
from app.core.models import metric_trend as _metric_trend  # noqa: F401
from app.core.models import metric_value as _metric_value  # noqa: F401
from app.core.models import monitor as _monitor  # noqa: F401
from app.core.models import monitor_result as _monitor_result  # noqa: F401
from app.core.models import notification_channel as _channel  # noqa: F401
from app.core.models import template as _template  # noqa: F401
from app.core.models import trigger as _trigger  # noqa: F401
from app.core.models import user as _user  # noqa: F401  (register mappers)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
