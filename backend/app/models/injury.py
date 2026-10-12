from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from datetime import datetime

from app.db.base import Base


class Injury(Base):
    """球员伤停记录（来自 API-Football ``/injuries``）。

    ai-football 原仓库未接入该端点，此表用于承接伤停软信息，
    可供给 ``predict.py`` 的 LLM 分析层或后续特征使用。
    """

    __tablename__ = "injuries"
    __table_args__ = (
        UniqueConstraint("fixture_id", "player_id", name="uq_injury_fixture_player"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增 ID")

    fixture_id = Column(
        Integer,
        ForeignKey("fixtures.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="比赛 ID（API-Football 赛程可用时）",
    )
    league_id = Column(Integer, nullable=True, index=True, comment="联赛 ID")
    season = Column(Integer, nullable=True, comment="赛季年份")
    team_id = Column(Integer, nullable=True, index=True, comment="球队 ID")
    team_name = Column(String(255), nullable=True, comment="球队名称")

    player_id = Column(Integer, nullable=True, index=True, comment="球员 ID")
    player_name = Column(String(255), nullable=True, comment="球员姓名")
    player_photo = Column(String(500), nullable=True, comment="球员头像")

    injury_type = Column(String(50), nullable=True, comment="类型: Missing / Questionable 等")
    injury_reason = Column(String(255), nullable=True, comment="伤情描述")

    fixture_date = Column(Date, nullable=True, index=True, comment="比赛日期")

    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
