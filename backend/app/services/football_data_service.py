"""football-data.co.uk 免费 CSV 数据源接入。

用途
----
为 ai-football 免费回填历史比赛与比赛统计，**大幅减少 API-Football 的调用配额消耗**
（API-Football 免费层仅 100 次/天，而本数据源无 key、无次数限制）。

数据源
------
    https://www.football-data.co.uk/mmz4281/{season_code}/{league_code}.csv

实测列（以 2425/E0.csv 为准）::

    Date, HomeTeam, AwayTeam, FTHG, FTAG, FTR, HTHG, HTAG, HTR,
    HS, AS, HST, AST, HF, AF, HC, AC, HY, AY, HR, AR,
    B365H..PSH, PSD, PSA..（多家赔率）

写入目标
--------
- ``fixtures``             比分 / 半场比分（A 组状态特征的原料）
- ``fixture_statistics``   射门 / 射正 / 角球 / 犯规（B 组统计特征的原料）

**本数据源不提供**：控球率、传球成功率、真实 xG、积分榜。
这四项仍需 API-Football（``/fixtures/statistics``、``/standings``），或 Understat（xG）。

设计要点
--------
1. 队名解析：football-data.co.uk 用队名，ai-football 用 API-Football 的 team_id。
   解析顺序 = 精确归一化匹配 ``teams`` 表 → 别名表 → 模糊匹配（阈值 0.86）。
   未解析的队名会被收集并在日志中告警，补进 ``app/data/team_aliases.json`` 即可。
2. 幂等：fixture 以 ``(league_id, season, home_id, away_id)`` 匹配已存在记录；
   不存在时用**确定性负数 ID** 新建，绝不占用 API-Football 的正整数 ID 空间。
   统计值按 ``(fixture_id, team_id, stat_type)`` upsert。
3. 失败降级：单个联赛/赛季拉取失败只记日志，不影响其余。
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.league import League, Season
from app.services.fixture_matching import (
    TeamResolver,
    build_external_fixture,
    match_existing_fixture,
    upsert_stat,
)

# ──────────── 常量 ────────────

# API-Football league_id -> football-data.co.uk 联赛码
LEAGUE_CODE_MAP: dict[int, str] = {
    39: "E0",    # 英超
    140: "SP1",  # 西甲
    78: "D1",    # 德甲
    135: "I1",   # 意甲
    61: "F1",    # 法甲
    179: "SC0",  # 苏超
}

# football-data.co.uk 列 -> fixture_statistics.stat_type
# 命名刻意与 API-Football 对齐，以命中 features.py 的 stat_type 白名单：
#   expected_goals / Total Shots / Shots on Goal / Ball Possession /
#   Corner Kicks / Passes % / Fouls
STAT_COLUMN_MAP: tuple[tuple[str, str, str], ...] = (
    # (主队列, 客队列, stat_type)
    ("HS", "AS", "Total Shots"),
    ("HST", "AST", "Shots on Goal"),
    ("HC", "AC", "Corner Kicks"),
    ("HF", "AF", "Fouls"),
)

_DEFAULT_BASE_URL = "https://www.football-data.co.uk/mmz4281"


# ──────────── 队名归一化与解析 ────────────
# 队名归一化、TeamResolver、合成 ID、统计 upsert 均已抽到 app/services/fixture_matching.py，
# 供 football-data.co.uk 与 Understat 两个数据源共用（保证同一场比赛只建一条 fixture）。
# 这里仅重新导出 TeamResolver，方便外部沿用旧导入路径。

__all__ = ["LEAGUE_CODE_MAP", "STAT_COLUMN_MAP", "season_code", "fetch_league_csv",
           "sync_football_data", "TeamResolver"]


# ──────────── CSV 拉取与解析 ────────────


def season_code(season_year: int) -> str:
    """ai-football 的 season(整数年份) -> football-data.co.uk 赛季码。

    2024 -> "2425"（2024/25 赛季）
    """
    y = int(season_year)
    return f"{str(y)[2:]}{str(y + 1)[2:]}"


def _base_url() -> str:
    return (getattr(settings, "football_data_base_url", "") or _DEFAULT_BASE_URL).rstrip("/")


def fetch_league_csv(league_code: str, season_code_str: str, timeout: float = 60.0) -> list[dict]:
    """下载并解析某个联赛某赛季的 CSV，返回 dict 行列表。"""
    url = f"{_base_url()}/{season_code_str}/{league_code}.csv"
    resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    # CSV 带 BOM，用 utf-8-sig 解码
    text = resp.content.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _to_int(value) -> Optional[int]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _parse_date(raw: str) -> Optional[date]:
    s = (raw or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ──────────── 主流程 ────────────


def sync_football_data(
    db: Session,
    seasons: Optional[list[int]] = None,
    dry_run: bool = False,
) -> dict:
    """从 football-data.co.uk 回填历史比赛与比赛统计。

    :param seasons: 指定赛季年份列表；缺省时用 DB 里已启用联赛的全部赛季。
    :param dry_run: 只解析与统计，不写库。
    :return: 统计字典（下载行数、写入 fixture/stat 数、未解析队名等）。
    """
    leagues = db.query(League).filter(League.enabled == True).all()  # noqa: E712
    targets: list[tuple[int, int]] = []  # (league_id, season_year)
    league_names: dict[int, str] = {}

    for league in leagues:
        league_names[league.id] = league.name_zh or league.name or ""
        code = LEAGUE_CODE_MAP.get(league.id)
        if not code:
            continue
        if seasons:
            for y in seasons:
                targets.append((league.id, int(y)))
        else:
            for s in db.query(Season).filter(Season.league_id == league.id).all():
                targets.append((league.id, int(s.year)))

    if not targets:
        logger.warning("没有可用的「已启用联赛 × 赛季」组合，跳过 football-data.co.uk 同步")
        return {"leagues": 0, "rows": 0, "fixtures_new": 0, "fixtures_matched": 0,
                "stats_written": 0, "unresolved": []}

    resolver = TeamResolver(db)

    rows_total = 0
    fixtures_new = 0
    fixtures_matched = 0
    stats_written = 0
    skipped_no_team = 0

    for league_id, season_year in targets:
        code = LEAGUE_CODE_MAP[league_id]
        sc = season_code(season_year)
        try:
            rows = fetch_league_csv(code, sc)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"拉取 {code}/{sc} ({league_id}) 失败: {exc}")
            continue

        if not rows:
            continue

        logger.info(f"football-data.co.uk {code}/{sc}: {len(rows)} 场")
        rows_total += len(rows)

        for row in rows:
            home_name = (row.get("HomeTeam") or "").strip()
            away_name = (row.get("AwayTeam") or "").strip()
            match_date = _parse_date(row.get("Date", ""))
            fthg = _to_int(row.get("FTHG"))
            ftag = _to_int(row.get("FTAG"))
            if not home_name or not away_name or match_date is None:
                continue
            if fthg is None or ftag is None:
                continue

            home_id = resolver.resolve(home_name)
            away_id = resolver.resolve(away_name)
            if home_id is None or away_id is None:
                skipped_no_team += 1
                continue
            if home_id == away_id:
                # 队名解析错误导致主客同队，写入会污染数据，直接跳过
                logger.warning(f"主客解析为同一球队，跳过: {home_name} vs {away_name}")
                skipped_no_team += 1
                continue

            fixture = match_existing_fixture(db, league_id, season_year, home_id, away_id)
            if fixture is None:
                # 负数确定性 ID + sub_data_synced=True（见 build_external_fixture 的说明）
                fixture = build_external_fixture(
                    league_id, season_year, home_id, home_name, away_id, away_name,
                    league_name=league_names.get(league_id),
                )
                if not dry_run:
                    db.add(fixture)
                fixtures_new += 1
            else:
                fixtures_matched += 1
            if not fixture.league_name:
                fixture.league_name = league_names.get(league_id)

            # 只在缺失时补日期：已有 fixture 的 date 是 API-Football 的精确开球时间戳，
            # 不能被 football-data.co.uk 的「仅到天」粒度覆盖成 00:00。
            if fixture.date is None:
                fixture.date = datetime.combine(match_date, datetime.min.time())
            fixture.goals_home = fthg
            fixture.goals_away = ftag
            fixture.halftime_home = _to_int(row.get("HTHG"))
            fixture.halftime_away = _to_int(row.get("HTAG"))
            if not fixture.home_name:
                fixture.home_name = home_name
            if not fixture.away_name:
                fixture.away_name = away_name

            if dry_run:
                continue

            # fixture 需要先有 id 才能挂 statistics（新建对象尚未 flush 时 id 已赋值）
            for home_col, away_col, stat_type in STAT_COLUMN_MAP:
                stats_written += upsert_stat(
                    db, fixture.id, home_id, home_name, stat_type, _to_int(row.get(home_col))
                )
                stats_written += upsert_stat(
                    db, fixture.id, away_id, away_name, stat_type, _to_int(row.get(away_col))
                )

        if not dry_run:
            db.commit()

    unresolved = sorted(resolver.unresolved)
    if unresolved:
        preview = ", ".join(unresolved[:40]) + (" ..." if len(unresolved) > 40 else "")
        logger.warning(
            f"有 {len(unresolved)} 个队名未能解析为 team_id"
            f"（请补进 app/data/team_aliases.json）: {preview}"
        )

    result = {
        "leagues": len({t[0] for t in targets}),
        "seasons": len(targets),
        "rows": rows_total,
        "fixtures_new": fixtures_new,
        "fixtures_matched": fixtures_matched,
        "stats_written": stats_written,
        "skipped_no_team": skipped_no_team,
        "unresolved": unresolved,
    }
    logger.info(
        f"football-data.co.uk 同步完成: 解析 {rows_total} 行, 匹配已有 {fixtures_matched} 场, "
        f"新建 {fixtures_new} 场, 写入统计 {stats_written} 条, 跳过 {skipped_no_team} 行"
    )
    return result
