"""API-Football ``/injuries`` 伤停数据同步。

ai-football 原仓库**完全没有接入该端点**（只在 ``schemas/league.py`` 里有个
coverage 标志位）。本模块把它补上，作为 LLM 软信息层的数据来源。

API-Football /injuries 支持参数：``league`` / ``season`` / ``fixture`` / ``team`` /
``player`` / ``date``。这里采用「按已启用联赛的当前赛季」批量拉取，
也可用 ``fixture_ids`` 精确拉取单场。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.injury import Injury
from app.models.league import League, Season


def _upsert_injury(db: Session, payload: dict) -> int:
    """按 (fixture_id, player_id) 幂等写入一条伤停记录。"""
    fixture_raw = payload.get("fixture") or {}
    league_raw = payload.get("league") or {}
    team_raw = payload.get("team") or {}
    player_raw = payload.get("player") or {}

    fixture_id = fixture_raw.get("id")
    player_id = player_raw.get("id")
    if player_id is None:
        return 0

    fixture_date = None
    raw_date = fixture_raw.get("date")
    if raw_date:
        try:
            fixture_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).date()
        except ValueError:
            fixture_date = None

    row = None
    if fixture_id is not None:
        row = (
            db.query(Injury)
            .filter(Injury.fixture_id == fixture_id, Injury.player_id == player_id)
            .first()
        )

    fields = dict(
        fixture_id=fixture_id,
        league_id=league_raw.get("id"),
        season=league_raw.get("season"),
        team_id=team_raw.get("id"),
        team_name=team_raw.get("name"),
        player_name=player_raw.get("name"),
        player_photo=player_raw.get("photo"),
        injury_type=player_raw.get("type"),
        injury_reason=player_raw.get("reason"),
        fixture_date=fixture_date,
    )

    if row is None:
        db.add(Injury(player_id=player_id, **fields))
        return 1

    for key, value in fields.items():
        setattr(row, key, value)
    return 1


def sync_injuries(
    db: Session,
    fixture_ids: Optional[list[int]] = None,
    date_str: Optional[str] = None,
) -> dict:
    """同步伤停数据。

    :param fixture_ids: 指定比赛 ID 列表（优先，精确拉取）
    :param date_str: 指定日期 ``YYYY-MM-DD``；与 fixture_ids 都为空时按联赛+赛季拉取
    :return: ``{"fetched": n, "written": n}``
    """
    if not settings.api_football_key:
        logger.warning("API_FOOTBALL_KEY 未配置，跳过伤停同步")
        return {"fetched": 0, "written": 0}

    base = settings.api_football_base_url
    headers = {"x-apisports-key": settings.api_football_key}

    jobs: list[dict] = []
    if fixture_ids:
        jobs = [{"fixture": str(fid)} for fid in fixture_ids]
    elif date_str:
        jobs = [{"date": date_str}]
    else:
        seasons = (
            db.query(Season)
            .join(League)
            .filter(Season.is_current == True, League.enabled == True)  # noqa: E712
            .all()
        )
        if not seasons:
            logger.warning("没有找到当前赛季，跳过伤停同步")
            return {"fetched": 0, "written": 0}
        jobs = [{"league": str(s.league_id), "season": str(s.year)} for s in seasons]

    fetched = 0
    written = 0

    for params in jobs:
        try:
            resp = httpx.get(f"{base}/injuries", headers=headers, params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"拉取伤停失败 params={params}: {exc}")
            continue

        items = data.get("response", []) or []
        fetched += len(items)
        for payload in items:
            written += _upsert_injury(db, payload)

        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning(f"写入伤停失败 params={params}: {exc}")

    logger.info(f"伤停同步完成: 拉取 {fetched} 条, 写入 {written} 条")
    return {"fetched": fetched, "written": written}
