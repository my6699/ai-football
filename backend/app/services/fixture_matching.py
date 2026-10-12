"""跨数据源共享的比赛匹配与统计写入工具。

**为什么需要这个模块**

football-data.co.uk 和 Understat 都只提供「队名」，都没有 API-Football 的 fixture id。
如果两个数据源各自生成 fixture ID，同一场比赛会被写成两条记录（一条来自 CSV、
一条来自 Understat），污染训练集。

因此两个数据源必须共用：
1. 同一套队名解析规则（``TeamResolver``）
2. 同一个合成 ID 公式（``synthetic_fixture_id``）—— 键与数据源无关
3. 同一套统计 upsert 逻辑（``upsert_stat``）

这样 Understat 的 xG 会**挂到 football-data.co.uk 已经建好的那场比赛上**，
而不是新建一场。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.models.fixture import Fixture, FixtureStatistic
from app.models.team import Team

# 合成 fixture ID 的取模上界（远离 API-Football 的正整数 ID 空间）
SYNTHETIC_ID_MOD = 2_000_000_000

# 模糊匹配阈值
FUZZY_THRESHOLD = 0.86

# 常见俱乐部后缀，归一化时剔除，避免 "AC Milan" / "Milan" 之类的差异
_SUFFIX_RE = re.compile(
    r"\b(fc|afc|cf|sc|ac|as|ss|ssc|cd|ud|rc|ogc|aj|sv|vfb|vfl|tsg|bsc|sco|calcio)\b"
)


def normalize_team_name(name: str) -> str:
    """队名归一化：去重音、转小写、去标点、剔除常见俱乐部后缀。"""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _SUFFIX_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def alias_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "team_aliases.json")


class TeamResolver:
    """把外部数据源的队名解析为 ai-football 的 team_id。

    解析链：teams 表精确匹配 → 别名表 → 模糊匹配。
    未解析的原始队名会累积到 ``self.unresolved``，供调用方告警。
    """

    def __init__(self, db: Session):
        self._exact: dict[str, int] = {}
        self._alias: dict[str, str] = {}
        # 反向别名：normalize(别名值) -> [别名键...]，用于「teams 表里存的是短名」的情形
        self._reverse_alias: dict[str, list[str]] = {}
        self._cache: dict[str, Optional[int]] = {}
        self.unresolved: set[str] = set()
        self._load(db)

    def _load(self, db: Session) -> None:
        try:
            rows = db.query(Team.id, Team.name, Team.name_zh).all()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"读取 teams 表失败，队名解析将全部依赖别名表: {exc}")
            rows = []
        for tid, name, name_zh in rows:
            if name:
                self._exact.setdefault(normalize_team_name(name), tid)
            if name_zh:
                self._exact.setdefault(normalize_team_name(name_zh), tid)

        try:
            with open(alias_path(), encoding="utf-8") as fh:
                raw = json.load(fh)
            self._alias = {
                normalize_team_name(k): v
                for k, v in raw.items()
                if not str(k).startswith("_")
            }
        except FileNotFoundError:
            logger.debug("未找到 team_aliases.json，仅使用 teams 表匹配")
            self._alias = {}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"解析 team_aliases.json 失败: {exc}")
            self._alias = {}

        for k_norm, v_raw in self._alias.items():
            v_norm = normalize_team_name(v_raw)
            if v_norm and v_norm != k_norm:
                self._reverse_alias.setdefault(v_norm, []).append(k_norm)

    @property
    def known_teams(self) -> int:
        return len(self._exact)

    def _fuzzy(self, key: str) -> Optional[int]:
        """在 teams 表索引里做模糊匹配，返回达到阈值的 team_id（无则 None）。"""
        best_tid, best_score = None, 0.0
        for cand_key, cand_tid in self._exact.items():
            score = SequenceMatcher(None, key, cand_key).ratio()
            if score > best_score:
                best_tid, best_score = cand_tid, score
        return best_tid if best_score >= FUZZY_THRESHOLD else None

    def resolve(self, raw_name: str) -> Optional[int]:
        key = normalize_team_name(raw_name)
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]

        tid = self._exact.get(key)

        # ① 别名表正向：外部名 -> 规范名
        if tid is None and key in self._alias:
            target = normalize_team_name(self._alias[key])
            tid = self._exact.get(target)
            if tid is None and target:
                tid = self._fuzzy(target)

        # ② 别名表反向：teams 表里存的是别名键（短名）时，用别名值反查
        if tid is None and key in self._reverse_alias:
            for k_norm in self._reverse_alias[key]:
                tid = self._exact.get(k_norm)
                if tid is not None:
                    break

        # ③ 原始名直接模糊匹配
        if tid is None:
            tid = self._fuzzy(key)

        if tid is None:
            self.unresolved.add(raw_name)

        self._cache[key] = tid
        return tid


def synthetic_fixture_id(league_id: int, season: int, home_id: int, away_id: int) -> int:
    """为外部数据源独有的比赛生成确定性负数 ID。

    键**刻意与数据源无关**（不含 fdco / understat 之类前缀），
    这样 football-data.co.uk 和 Understat 对同一场比赛算出同一个 ID，
    不会各建一条。
    """
    key = f"{league_id}:{season}:{home_id}:{away_id}"
    digest = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:15], 16)
    return -(digest % SYNTHETIC_ID_MOD) - 1


def build_external_fixture(
    league_id: int,
    season: int,
    home_id: int,
    home_name: str,
    away_id: int,
    away_name: str,
    status_short: str = "FT",
    league_name: Optional[str] = None,
) -> Fixture:
    """构造一场「外部数据源独有」的比赛（football-data.co.uk / Understat 共用）。

    ``status_short`` 默认 ``"FT"``（已完赛，历史回填用）；Understat 对未开赛的
    比赛会传 ``"NS"``，让这些比赛能被 ``auto_predict`` 选中作为预测目标。

    ``league_name`` 反范式存联赛名，供 LLM 提示词直接取用（``predict.py`` 读
    ``fixtures.league_name``）；外部数据源同步时应由调用方从 ``leagues`` 表带过来，
    否则会存成 NULL，让提示词出现「联赛:None」。

    与直接 ``Fixture(...)`` 的区别在于两个字段，都关系到与 API-Football 的隔离：

    - ``id``：确定性**负数**，不占用 API-Football 的正整数 ID 空间；
    - ``sub_data_synced=True``：这些比赛的 events / lineups / players 在 API-Football
      里**根本不存在**（负数 ID 不是真实 fixture id）。若置为 False，
      ``fixture_service.sync_completed_sub_data`` 会为每一场反复发起 4 次无效请求，
      永远失败、也永远不会被标记完成，从而**持续烧掉 API-Football 的每日配额**
      （免费层仅 100 次/天）；``tools/sync_fixtures.py`` 更会因此**死循环**
      （它 `while True` 直到待处理数归零）。外部数据源已经把本表需要的统计写全，
      故直接标记为已同步。
    """
    return Fixture(
        id=synthetic_fixture_id(league_id, season, home_id, away_id),
        league_id=league_id,
        season=season,
        home_id=home_id,
        home_name=home_name,
        away_id=away_id,
        away_name=away_name,
        status_short=status_short,
        league_name=league_name,
        sub_data_synced=True,
    )


def match_existing_fixture(
    db: Session, league_id: int, season: int, home_id: int, away_id: int
) -> Optional[Fixture]:
    """按 (league_id, season, home_id, away_id) 匹配已有比赛。

    主客必须一致，不会把主客场颠倒的比赛错配到一起。
    """
    return (
        db.query(Fixture)
        .filter(
            Fixture.league_id == league_id,
            Fixture.season == season,
            Fixture.home_id == home_id,
            Fixture.away_id == away_id,
        )
        .first()
    )


def upsert_stat(
    db: Session,
    fixture_id: int,
    team_id: int,
    team_name: str,
    stat_type: str,
    value,
    overwrite: bool = True,
) -> int:
    """按 (fixture_id, team_id, stat_type) 幂等写入一条比赛统计。

    :param overwrite: True=值变化时覆盖（默认）；False=已有值则保留（只补空缺）。
    :return: 1=有变化, 0=无变化。
    """
    if value is None:
        return 0
    stat_value = str(value)
    row = (
        db.query(FixtureStatistic)
        .filter(
            FixtureStatistic.fixture_id == fixture_id,
            FixtureStatistic.team_id == team_id,
            FixtureStatistic.stat_type == stat_type,
        )
        .first()
    )
    if row is None:
        db.add(
            FixtureStatistic(
                fixture_id=fixture_id,
                team_id=team_id,
                team_name=team_name,
                stat_type=stat_type,
                stat_value=stat_value,
            )
        )
        return 1
    if not overwrite:
        return 0
    if row.stat_value != stat_value:
        row.stat_value = stat_value
        return 1
    return 0
