"""add missing zh columns

模型里存在但历史迁移从未创建的中文翻译列。
注意：predictions / scheduler_tasks / scheduler_logs 由裸 SQL 管理、不在 ORM metadata 中，
autogenerate 会误判为「多余表」并生成 drop_table，此处已手动移除。

Revision ID: fe965d7de7c6
Revises: d4e8b1c6f205
Create Date: 2026-10-08 22:04:36.009865

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fe965d7de7c6'
down_revision: Union[str, None] = 'd4e8b1c6f205'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('fixture_events', sa.Column('type_zh', sa.String(length=20), nullable=True, comment='事件类型中文'))
    op.add_column('fixture_events', sa.Column('detail_zh', sa.String(length=100), nullable=True, comment='事件详情中文'))
    op.add_column('fixture_statistics', sa.Column('stat_type_zh', sa.String(length=100), nullable=True, comment='统计类型中文'))
    op.add_column('leagues', sa.Column('name_zh', sa.String(length=255), nullable=True, comment='中文名'))
    op.add_column('leagues', sa.Column('country_name_zh', sa.String(length=100), nullable=True, comment='国家中文名'))
    op.add_column('players', sa.Column('name_zh', sa.String(length=255), nullable=True, comment='中文名'))
    op.add_column('teams', sa.Column('name_zh', sa.String(length=255), nullable=True, comment='中文名'))
    op.add_column('teams', sa.Column('country_zh', sa.String(length=100), nullable=True, comment='国家中文名'))
    op.add_column('venues', sa.Column('name_zh', sa.String(length=255), nullable=True, comment='中文名'))
    op.add_column('venues', sa.Column('city_zh', sa.String(length=100), nullable=True, comment='城市中文名'))


def downgrade() -> None:
    op.drop_column('venues', 'city_zh')
    op.drop_column('venues', 'name_zh')
    op.drop_column('teams', 'country_zh')
    op.drop_column('teams', 'name_zh')
    op.drop_column('players', 'name_zh')
    op.drop_column('leagues', 'country_name_zh')
    op.drop_column('leagues', 'name_zh')
    op.drop_column('fixture_statistics', 'stat_type_zh')
    op.drop_column('fixture_events', 'detail_zh')
    op.drop_column('fixture_events', 'type_zh')