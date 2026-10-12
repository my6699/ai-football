"""add_injuries

新增 ``injuries`` 表，承接 API-Football ``/injuries`` 的伤停数据。

Revision ID: c1f4a7b2d903
Revises: b6d2a8c9f001
Create Date: 2026-10-07 20:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1f4a7b2d903"
down_revision: Union[str, None] = "b6d2a8c9f001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "injuries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增 ID"),
        sa.Column("fixture_id", sa.Integer(), nullable=True, comment="比赛 ID（API-Football 赛程可用时）"),
        sa.Column("league_id", sa.Integer(), nullable=True, comment="联赛 ID"),
        sa.Column("season", sa.Integer(), nullable=True, comment="赛季年份"),
        sa.Column("team_id", sa.Integer(), nullable=True, comment="球队 ID"),
        sa.Column("team_name", sa.String(length=255), nullable=True, comment="球队名称"),
        sa.Column("player_id", sa.Integer(), nullable=True, comment="球员 ID"),
        sa.Column("player_name", sa.String(length=255), nullable=True, comment="球员姓名"),
        sa.Column("player_photo", sa.String(length=500), nullable=True, comment="球员头像"),
        sa.Column("injury_type", sa.String(length=50), nullable=True, comment="类型: Missing / Questionable 等"),
        sa.Column("injury_reason", sa.String(length=255), nullable=True, comment="伤情描述"),
        sa.Column("fixture_date", sa.Date(), nullable=True, comment="比赛日期"),
        sa.Column("created_at", sa.DateTime(), nullable=True, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=True, comment="更新时间"),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fixture_id", "player_id", name="uq_injury_fixture_player"),
    )
    op.create_index("ix_injuries_fixture_id", "injuries", ["fixture_id"])
    op.create_index("ix_injuries_league_id", "injuries", ["league_id"])
    op.create_index("ix_injuries_team_id", "injuries", ["team_id"])
    op.create_index("ix_injuries_player_id", "injuries", ["player_id"])
    op.create_index("ix_injuries_fixture_date", "injuries", ["fixture_date"])


def downgrade() -> None:
    op.drop_index("ix_injuries_fixture_date", table_name="injuries")
    op.drop_index("ix_injuries_player_id", table_name="injuries")
    op.drop_index("ix_injuries_team_id", table_name="injuries")
    op.drop_index("ix_injuries_league_id", table_name="injuries")
    op.drop_index("ix_injuries_fixture_id", table_name="injuries")
    op.drop_table("injuries")
