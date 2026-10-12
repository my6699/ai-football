"""add scheduler_tasks.start_hour

Revision ID: d4e8b1c6f205
Revises: c1f4a7b2d903
Create Date: 2026-10-08 21:20:00.000000

修补 `scheduler_tasks` 的两处建表缺陷
--------------------------------------

`f1173d35c3c1_add_scheduler_tasks.py` 建表时**漏了 `start_hour` 列**，
而链上**没有任何 `upgrade()` 补过它**（`aa8539407817` 里出现过一次，
但那是在它的 `downgrade()` 里）。

后果：从空库执行 `alembic upgrade head` 会成功建表，但紧接着
`uvicorn main:app` 启动时 `app/services/scheduler.py: _seed_defaults()` 执行

    INSERT IGNORE INTO scheduler_tasks
        (id, name, interval_seconds, start_hour, is_enabled) VALUES (...)

会抛 MySQL 1054 `Unknown column 'start_hour' in 'field list'`
→ `init_scheduler()` 抛异常 → FastAPI lifespan 失败 → **服务起不来**。
（注意 `INSERT IGNORE` 不会吞掉「列不存在」这类名称解析错误。）

另外 `interval_seconds` 建表时是 `NOT NULL`，但 `_seed_defaults()` 对
`auto_predict` 这类纯定时任务会插入 `None`，语义上应为可空。

本迁移是**幂等**的：先检查列是否存在再改，因此在已经带有该列的数据库上
（例如从作者提供的 SQL dump 导入的库）重复执行也不会报错。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'd4e8b1c6f205'
down_revision: Union[str, None] = 'c1f4a7b2d903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "scheduler_tasks"


def _columns() -> dict:
    """返回 {列名: 列信息}；表不存在或无法探测时返回 None。"""
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(TABLE):
        return None
    return {c["name"]: c for c in insp.get_columns(TABLE)}


def upgrade() -> None:
    cols = _columns()
    if cols is None:
        # 表不存在说明这条链没按预期跑过，交给上游迁移处理
        return

    # ① 补 start_hour —— scheduler.py 会显式 INSERT 这一列
    if "start_hour" not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                "start_hour",
                mysql.DOUBLE(asdecimal=True),
                nullable=True,
                comment="定时任务的每日启动小时，支持小数（5.5 = 05:30）；NULL 表示按间隔执行",
            ),
        )

    # ② interval_seconds 放宽为可空 —— 纯定时任务（如 auto_predict）不设间隔
    col = cols.get("interval_seconds")
    if col is not None and not col.get("nullable", True):
        op.alter_column(
            TABLE,
            "interval_seconds",
            existing_type=mysql.INTEGER(),
            nullable=True,
            comment="间隔任务的执行间隔（秒）；NULL 表示按 start_hour 每天执行",
        )


def downgrade() -> None:
    cols = _columns()
    if cols is None:
        return
    if "start_hour" in cols:
        op.drop_column(TABLE, "start_hour")
    # 不把 interval_seconds 改回 NOT NULL：可能已存在 NULL 行，回滚会失败。
