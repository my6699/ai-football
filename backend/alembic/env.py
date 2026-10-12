import sys
from pathlib import Path

# 将 backend 目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import engine_from_config, pool
from alembic import context

from app.core.config import settings
from app.db.base import Base

# 导入所有模型，确保 autogenerate 能检测到
# 注意：原版只导入了 League/Season/Team/Venue，导致 Player/Standing/Fixture/Injury
# 等表在 autogenerate 时被漏掉。这里改为导入 app.models 包（其 __init__ 汇总了全部模型）。
import app.models  # noqa: F401
from app.models.league import League, Season  # noqa: F401
from app.models.team import Team, Venue  # noqa: F401
from app.models.player import Player, PlayerStats  # noqa: F401
from app.models.standing import Standing  # noqa: F401
from app.models.fixture import (  # noqa: F401
    Fixture,
    FixtureEvent,
    FixtureLineup,
    FixturePlayerStat,
    FixtureStatistic,
)
from app.models.injury import Injury  # noqa: F401

config = context.config

# 动态设置数据库 URL
config.set_main_option("sqlalchemy.url", settings.db_url)

# 使用 loguru 替代 Python logging，跳过 fileConfig 避免 GBK 编码问题
# if config.config_file_name is not None:
#     fileConfig(config.config_file_name)

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


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
