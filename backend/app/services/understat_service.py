"""Understat 真实 xG 数据源接入。

用途
----
为 ai-football 补齐**真实 xG（expected goals）**。

为什么需要它
------------
ai-football 的 B 组特征里有 ``xg``（见 ``prediction/features.py`` 的
``'expected_goals' -> 'xg'``），但它的两个上游数据源都拿不到真实 xG：

- **football-data.co.uk**：免费 CSV 只有比分/射门/角球/犯规，**没有 xG**；
- **API-Football**：``/fixtures/statistics`` 偶尔返回 ``expected_goals``，
  但免费层覆盖不稳定，且缺失率高。

Understat 是公开的真实 xG 权威源，覆盖五大联赛，可以免费、无限次抓取。

数据源
------
    GET https://understat.com/getLeagueData/{league}/{season}

返回 **gzip 压缩的 JSON**（httpx 会自动解压），顶层三个键：

- ``teams``   dict: understat_team_id -> {id, title, history[]}
- ``players`` list: 球员赛季数据
- ``dates``   list: **比赛列表**（本模块真正使用的部分）

``dates`` 每一项的结构（实测 2024/25 EPL）::

    {
      "id": "26602",
      "isResult": true,
      "h": {"id": "89", "title": "Manchester United", "short_title": "MUN"},
      "a": {"id": "228", "title": "Fulham",            "short_title": "FLH"},
      "goals": {"h": "1", "a": "0"},
      "xG":    {"h": "2.04268", "a": "0.418711"},
      "datetime": "2024-08-16 19:00:00",   # UTC
      "forecast": {"w": "0.8069", "d": "0.1489", "l": "0.0442"}
    }

实测各联赛每赛季场次：EPL 380 / La_liga 380 / Bundesliga 306 /
Serie_A 380 / Ligue_1 306 —— 与 football-data.co.uk 完全一致。

写入目标
--------
- ``fixture_statistics``  ``expected_goals``（主客各一条）→ B 组 ``xg`` 特征
- ``fixtures``            仅在**本场 fixture 尚不存在**时新建；
                          比分只在为空时补；日期在为空时补，
                          且当已有值只是「日期粒度」(00:00:00) 时会**升级**为
                          Understat 的真实开球时间（见 ``_should_upgrade_date``）
- ``fixtures``（未开赛）  ``isResult == false`` 的比赛建成 ``status_short='NS'``，
                          带真实开球时间、不写比分与 xG。**这是免费数据源里唯一
                          能提供「未来赛程」的地方**——``auto_predict`` 只认
                          ``status_short='NS'`` 的比赛，没有它每日自动预测无目标可跑。

设计要点
--------
1. **与 football-data.co.uk 共用一套匹配逻辑**（``app/services/fixture_matching.py``）：
   同一个 ``synthetic_fixture_id`` 公式（键不含数据源前缀），所以 Understat 的 xG
   会**挂到 football-data.co.uk 已建好的那场比赛上**，而不是另建一条。
   两个数据源的执行顺序无关紧要，先跑谁都能对上。
2. **xG 权威性**：``expected_goals`` 以 Understat 为准（``overwrite=True``）。
   若同时启用 API-Football 的统计同步，请把本任务排在它之后执行
   （默认调度：football_data_backfill 05:30 → understat_sync 06:00）。
3. **未开赛比赛建 fixture 但不写 xG**（见上「写入目标」）。
4. 失败降级：单个联赛/赛季拉取失败只记日志，不影响其余。
"""
from __future__ import annotations

import time
from datetime import datetime
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

# API-Football league_id -> Understat 联赛 slug
# 注意：Understat 不覆盖苏超（179），该联赛的 xG 只能靠 API-Football。
UNDERSTAT_LEAGUE_MAP: dict[int, str] = {
    39: "EPL",         # 英超
    140: "La_liga",    # 西甲
    78: "Bundesliga",  # 德甲
    135: "Serie_A",    # 意甲
    61: "Ligue_1",     # 法甲
}

# 写入 fixture_statistics 的统计类型，必须命中 features.py 的白名单
XG_STAT_TYPE = "expected_goals"

_DEFAULT_BASE_URL = "https://understat.com/getLeagueData"

# Understat 是 AJAX 接口，必须带 X-Requested-With，否则可能返回 HTML 页面
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://understat.com/",
}

__all__ = [
    "UNDERSTAT_LEAGUE_MAP",
    "XG_STAT_TYPE",
    "fetch_league_data",
    "sync_understat",
]


def _base_url() -> str:
    return (getattr(settings, "understat_base_url", "") or _DEFAULT_BASE_URL).rstrip("/")


# ──────────── 拉取 ────────────


def fetch_league_data(
    league_slug: str,
    season_year: int,
    timeout: float = 60.0,
    retries: int = 3,
) -> dict:
    """拉取某联赛某赛季的 Understat 数据（已解析为 dict）。

    Understat 偶发 5xx / 超时，这里做 3 次指数退避重试。
    """
    url = f"{_base_url()}/{league_slug}/{int(season_year)}"
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            # httpx 通常已自动解压；个别情况下 content-encoding 未被处理，兜底手动解压
            raw = resp.content
            if raw[:2] == b"\x1f\x8b":
                import gzip

                raw = gzip.decompress(raw)
            import json

            data = json.loads(raw.decode("utf-8", errors="replace"))
            if not isinstance(data, dict) or "dates" not in data:
                raise ValueError("返回结构异常（缺少 dates 键）")
            return data
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                sleep_s = 2 ** attempt
                logger.warning(
                    f"Understat {league_slug}/{season_year} 第 {attempt} 次失败: {exc}，"
                    f"{sleep_s}s 后重试"
                )
                time.sleep(sleep_s)
    raise RuntimeError(f"Understat {league_slug}/{season_year} 拉取失败: {last_exc}")


# ──────────── 解析辅助 ────────────


def _parse_dt(raw) -> Optional[datetime]:
    """Understat 的 ``"2024-08-16 19:00:00"`` 是 UTC。"""
    s = (raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _to_float(raw) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _to_int(raw) -> Optional[int]:
    v = _to_float(raw)
    return None if v is None else int(v)


def _fmt_xg(value: Optional[float]) -> Optional[str]:
    """xG 存成定长 4 位小数的字符串，避免 6 位有效数字带来的无意义抖动。"""
    if value is None:
        return None
    return f"{value:.4f}"


def _should_upgrade_date(current: Optional[datetime], incoming: Optional[datetime]) -> bool:
    """是否用 Understat 的 datetime 覆盖已有 ``fixtures.date``。

    规则（保证「先跑谁结果都一样」，且绝不降级）:

    - 已有值为空 → 写入；
    - 已有值**只有日期粒度**（恰好 00:00:00，来自 football-data.co.uk 的 ``Date`` 列）
      且 Understat 带真实开球时间 → **升级**为精确时间；
    - 已有值是精确时间（来自 API-Football，或本函数此前写入） → **不覆盖**；
    - 仅当**日期部分相同**时才升级，绝不因时区差异把比赛挪到另一天。
    """
    if incoming is None:
        return False
    if current is None:
        return True
    cur_time = (current.hour, current.minute, current.second, current.microsecond)
    inc_time = (incoming.hour, incoming.minute, incoming.second, incoming.microsecond)
    if cur_time != (0, 0, 0, 0) or inc_time == (0, 0, 0, 0):
        return False
    return current.date() == incoming.date()


# ──────────── 主流程 ────────────


def sync_understat(
    db: Session,
    seasons: Optional[list[int]] = None,
    league_ids: Optional[list[int]] = None,
    dry_run: bool = False,
) -> dict:
    """从 Understat 回填真实 xG 到 ``fixture_statistics``。

    :param seasons: 指定赛季年份列表（如 ``[2024, 2023]``）；
                    缺省时用 DB 里已启用联赛的全部赛季。
    :param league_ids: 只处理这些 league_id；缺省时处理所有已启用联赛。
    :param dry_run: 只解析与统计，不写库。
    :return: 统计字典。
    """
    query = db.query(League).filter(League.enabled == True)  # noqa: E712
    if league_ids:
        query = query.filter(League.id.in_(league_ids))
    leagues = query.all()

    targets: list[tuple[int, int]] = []  # (league_id, season_year)
    league_names: dict[int, str] = {}
    for league in leagues:
        league_names[league.id] = league.name_zh or league.name or ""
        if league.id not in UNDERSTAT_LEAGUE_MAP:
            continue
        if seasons:
            for y in seasons:
                targets.append((league.id, int(y)))
        else:
            for s in db.query(Season).filter(Season.league_id == league.id).all():
                targets.append((league.id, int(s.year)))

    if not targets:
        logger.warning("没有可用的「已启用联赛 × 赛季」组合，跳过 Understat 同步")
        return {"leagues": 0, "seasons": 0, "matches": 0, "fixtures_new": 0,
                "fixtures_matched": 0, "upcoming_new": 0, "xg_written": 0,
                "skipped_not_played": 0, "skipped_no_team": 0, "skipped_no_xg": 0,
                "unresolved": []}

    resolver = TeamResolver(db)

    matches_total = 0
    fixtures_new = 0
    fixtures_matched = 0
    xg_written = 0
    skipped_not_played = 0
    skipped_no_team = 0
    skipped_no_xg = 0
    upcoming_new = 0

    for league_id, season_year in targets:
        slug = UNDERSTAT_LEAGUE_MAP[league_id]
        try:
            data = fetch_league_data(slug, season_year)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"拉取 Understat {slug}/{season_year} ({league_id}) 失败: {exc}")
            continue

        dates = data.get("dates") or []
        if not dates:
            continue

        logger.info(f"Understat {slug}/{season_year}: {len(dates)} 场")
        matches_total += len(dates)

        for entry in dates:
            is_result = bool(entry.get("isResult"))

            home = entry.get("h") or {}
            away = entry.get("a") or {}
            home_name = (home.get("title") or "").strip()
            away_name = (away.get("title") or "").strip()
            if not home_name or not away_name:
                continue

            # 未开赛的比赛没有 xG（只有 forecast），但**仍要建 fixture**：
            # auto_predict 只认 status_short='NS' 的比赛，这是免费数据源里
            # 唯一能提供「未来赛程」的地方。
            xg_home = _to_float((entry.get("xG") or {}).get("h")) if is_result else None
            xg_away = _to_float((entry.get("xG") or {}).get("a")) if is_result else None
            if is_result and xg_home is None and xg_away is None:
                # 已开赛却没有 xG：这场 Understat 没有数据，跳过
                skipped_no_xg += 1
                continue

            home_id = resolver.resolve(home_name)
            away_id = resolver.resolve(away_name)
            if home_id is None or away_id is None:
                skipped_no_team += 1
                continue
            if home_id == away_id:
                logger.warning(f"主客解析为同一球队，跳过: {home_name} vs {away_name}")
                skipped_no_team += 1
                continue

            fixture = match_existing_fixture(db, league_id, season_year, home_id, away_id)
            if fixture is None:
                # 负数确定性 ID + sub_data_synced=True（见 build_external_fixture 的说明）
                # 未开赛建 NS（供 auto_predict 选中），已完赛建 FT
                fixture = build_external_fixture(
                    league_id, season_year, home_id, home_name, away_id, away_name,
                    status_short="FT" if is_result else "NS",
                    league_name=league_names.get(league_id),
                )
                if not dry_run:
                    db.add(fixture)
                fixtures_new += 1
                if not is_result:
                    upcoming_new += 1
            else:
                fixtures_matched += 1
            if not fixture.league_name:
                fixture.league_name = league_names.get(league_id)

            # 日期：空值直接补；若已有值只是 football-data.co.uk 的「日期粒度」(00:00:00)
            # 而 Understat 有真实开球时间，则升级为精确时间（保证与执行顺序无关）。
            # API-Football 写入的精确时间永远不会被覆盖。
            dt = _parse_dt(entry.get("datetime"))
            if _should_upgrade_date(fixture.date, dt):
                fixture.date = dt

            if not is_result:
                # 未开赛：fixture 已建好（含开球时间），没有 xG 可写，到此为止
                skipped_not_played += 1
                continue

            # 比分：只在缺失时补（Understat 不是比分权威源，不覆盖已有比分）
            goals_home = _to_int((entry.get("goals") or {}).get("h"))
            goals_away = _to_int((entry.get("goals") or {}).get("a"))
            if fixture.goals_home is None and goals_home is not None:
                fixture.goals_home = goals_home
            if fixture.goals_away is None and goals_away is not None:
                fixture.goals_away = goals_away

            if dry_run:
                continue

            xg_written += upsert_stat(
                db, fixture.id, home_id, home_name, XG_STAT_TYPE, _fmt_xg(xg_home)
            )
            xg_written += upsert_stat(
                db, fixture.id, away_id, away_name, XG_STAT_TYPE, _fmt_xg(xg_away)
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
        "matches": matches_total,
        "fixtures_new": fixtures_new,
        "fixtures_matched": fixtures_matched,
        "upcoming_new": upcoming_new,
        "xg_written": xg_written,
        "skipped_not_played": skipped_not_played,
        "skipped_no_team": skipped_no_team,
        "skipped_no_xg": skipped_no_xg,
        "unresolved": unresolved,
    }
    logger.info(
        f"Understat 同步完成: 解析 {matches_total} 场, 匹配已有 {fixtures_matched} 场, "
        f"新建 {fixtures_new} 场（其中未开赛 {upcoming_new} 场）, 写入 xG {xg_written} 条, "
        f"未开赛无 xG {skipped_not_played} 场, 已开赛无 xG {skipped_no_xg} 场, "
        f"跳过队名未解析 {skipped_no_team} 场"
    )
    return result
