"""在没有 API-Football 的情况下，从 football-data.co.uk 引导初始化数据。

**为什么需要这个工具**

``sync_football_data`` 依赖两件事才能工作：
1. ``leagues`` 表里有 ``enabled=True`` 的联赛（否则没有抓取目标）；
2. ``teams`` 表里有队名（否则 ``TeamResolver`` 全部解析失败，一行都写不进库）。

这两张表原本由 API-Football 的 ``league_sync`` / ``team_sync`` 填充。
API-Football 不可用时，本工具用免费 CSV 把它们补上：

1. 按 ``LEAGUE_CODE_MAP`` 写入 6 个联赛（``enabled=True``）；
2. 抓取指定赛季的 CSV，收集全部队名，经 ``team_aliases.json`` 规范后写入 ``teams``；
3. 调用 ``sync_football_data`` 回填 ``fixtures`` + ``fixture_statistics``。

球队 ID 采用**负数确定性哈希**，与 ``synthetic_fixture_id`` 同一约定，
不占用 API-Football 的正整数 ID 空间。

用法（在 backend/ 目录下）::

    python tools/bootstrap_free_data.py                      # 默认最近 5 个赛季
    python tools/bootstrap_free_data.py --seasons 2024 2025
    python tools/bootstrap_free_data.py --leagues-only       # 只建联赛和球队
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from app.core.log_config import setup_logger  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.league import League, Season  # noqa: E402
from app.models.team import Team  # noqa: E402
from app.services.fixture_matching import (  # noqa: E402
    SYNTHETIC_ID_MOD,
    alias_path,
    normalize_team_name,
)
from app.services.football_data_service import (  # noqa: E402
    LEAGUE_CODE_MAP,
    fetch_league_csv,
    season_code,
    sync_football_data,
)

setup_logger()

# API-Football league_id -> (联赛名, 国家, 国家代码, 是否启用)
#
# 苏超(179) 刻意**不启用**：它是 12 队联赛，每对球队一个赛季要交手 3~4 次，
# 而 ``synthetic_fixture_id`` 的键是 (league_id, season, home_id, away_id)，
# 同一对主客在同一赛季内会重复出现，确定性 ID 必然撞车（IntegrityError）。
# 其余 5 个联赛每对每赛季只交手一次（一主一客），键唯一。
LEAGUE_META: dict[int, tuple[str, str, str, bool]] = {
    39: ("Premier League", "England", "GB", True),
    140: ("La Liga", "Spain", "ES", True),
    78: ("Bundesliga", "Germany", "DE", True),
    135: ("Serie A", "Italy", "IT", True),
    61: ("Ligue 1", "France", "FR", True),
    179: ("Scottish Premiership", "Scotland", "GB", False),
}

DEFAULT_SEASONS = [2022, 2023, 2024, 2025, 2026]


def synthetic_team_id(name: str) -> int:
    """由队名生成确定性负数 ID（与 synthetic_fixture_id 同一约定）。"""
    key = normalize_team_name(name)
    digest = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:15], 16)
    return -(digest % SYNTHETIC_ID_MOD) - 1


def load_aliases() -> dict[str, str]:
    """读取 team_aliases.json，返回 {归一化外部名: 规范名}。"""
    try:
        with open(alias_path(), encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return {}
    return {
        normalize_team_name(k): v
        for k, v in raw.items()
        if not str(k).startswith("_")
    }


def seed_leagues(db) -> int:
    """写入联赛；已存在的行只校正 ``enabled`` 标志。返回新增数。"""
    added = 0
    for league_id, (name, country, code, enabled) in LEAGUE_META.items():
        row = db.query(League).filter(League.id == league_id).first()
        if row is not None:
            row.enabled = enabled
            continue
        db.add(League(
            id=league_id,
            name=name,
            country_name=country,
            country_code=code,
            type="League",
            enabled=enabled,
        ))
        added += 1
    db.commit()
    return added


def seed_seasons(db, seasons: list[int], current: int | None = None) -> int:
    """写入赛季表（仅启用的联赛），并把最新赛季标为当前赛季。返回新增数。

    调度器里的 team/player/standing/fixture/injury 同步都按
    ``Season.is_current == True`` 找目标；football-data / Understat 回填按
    「启用联赛的全部赛季」找目标。缺了这张表，这些任务会全部空转。
    """
    current = max(seasons) if current is None else current
    added = 0
    for league_id, (_name, _country, _code, enabled) in LEAGUE_META.items():
        if not enabled:
            continue
        for year in seasons:
            row = (
                db.query(Season)
                .filter(Season.league_id == league_id, Season.year == year)
                .first()
            )
            if row is None:
                row = Season(league_id=league_id, year=year)
                db.add(row)
                added += 1
            row.is_current = (year == current)
    db.commit()
    return added


def collect_team_names(seasons: list[int]) -> dict[str, str]:
    """抓取全部目标 CSV，返回 {规范名: 原始名}。规范名经别名表转换。"""
    aliases = load_aliases()
    canonical: dict[str, str] = {}
    for league_id, code in LEAGUE_CODE_MAP.items():
        for year in seasons:
            sc = season_code(year)
            try:
                rows = fetch_league_csv(code, sc)
            except Exception as exc:  # noqa: BLE001
                print(f"  [跳过] {code}/{sc}: {exc}")
                continue
            for row in rows:
                for col in ("HomeTeam", "AwayTeam"):
                    raw = (row.get(col) or "").strip()
                    if not raw:
                        continue
                    norm = normalize_team_name(raw)
                    canon = aliases.get(norm, raw)
                    canonical.setdefault(canon, raw)
            print(f"  {code}/{sc}: {len(rows)} 场")
    return canonical


def seed_teams(db, canonical: dict[str, str]) -> tuple[int, int]:
    """写入球队，返回 (新增, 已存在)。"""
    existing = {
        normalize_team_name(n)
        for (n,) in db.query(Team.name).all()
        if n
    }
    added = 0
    skipped = 0
    for canon_name in sorted(canonical):
        if normalize_team_name(canon_name) in existing:
            skipped += 1
            continue
        country = None
        db.add(Team(
            id=synthetic_team_id(canon_name),
            name=canon_name,
            country=country,
        ))
        added += 1
    db.commit()
    return added, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="从免费数据源引导初始化 leagues / teams / fixtures")
    parser.add_argument("--seasons", nargs="*", type=int, default=None,
                        help=f"赛季年份，默认 {DEFAULT_SEASONS}")
    parser.add_argument("--leagues-only", action="store_true", help="只建联赛与球队，不回填比赛")
    args = parser.parse_args()

    seasons = args.seasons or DEFAULT_SEASONS
    db = SessionLocal()
    try:
        print("=" * 60)
        print(f"① 写入联赛与赛季（{len(LEAGUE_META)} 个联赛）")
        print("=" * 60)
        n = seed_leagues(db)
        print(f"  联赛: 新增 {n} 个，已存在 {len(LEAGUE_META) - n} 个")
        sn = seed_seasons(db, seasons)
        print(f"  赛季: 新增 {sn} 个（当前赛季 {max(seasons)}）")

        print()
        print("=" * 60)
        print(f"② 抓取赛季 {seasons} 收集队名")
        print("=" * 60)
        canonical = collect_team_names(seasons)
        print(f"  共收集到 {len(canonical)} 支球队")

        print()
        print("=" * 60)
        print("③ 写入球队")
        print("=" * 60)
        added, skipped = seed_teams(db, canonical)
        print(f"  新增 {added} 支，已存在 {skipped} 支")

        if args.leagues_only:
            print("\n--leagues-only，跳过比赛回填")
            return 0

        print()
        print("=" * 60)
        print(f"④ 回填历史比赛与统计（赛季 {seasons}）")
        print("=" * 60)
        result = sync_football_data(db, seasons=seasons)

        print()
        print("=" * 60)
        print("结果")
        print("=" * 60)
        print(json.dumps(
            {k: v for k, v in result.items() if k != "unresolved"},
            ensure_ascii=False, indent=2,
        ))
        unresolved = result.get("unresolved") or []
        if unresolved:
            print(f"\n未解析队名 {len(unresolved)} 个:")
            for name in unresolved[:30]:
                print(f"  {name}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())