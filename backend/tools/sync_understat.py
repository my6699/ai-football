"""Understat 真实 xG 回填 CLI。

用法（在 backend/ 目录下）::

    python tools/sync_understat.py                     # 用 DB 里已启用联赛的全部赛季
    python tools/sync_understat.py --seasons 2024 2025
    python tools/sync_understat.py --leagues 39 140    # 只跑英超+西甲
    python tools/sync_understat.py --dry-run           # 只解析不写库

免费、无需 API key。写入 fixture_statistics.expected_goals，供 B 组 xg 特征使用。
与 football-data.co.uk 共用同一套比赛匹配逻辑，所以 xG 会挂到已建好的比赛上。
"""
import argparse
import json
import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from app.core.log_config import setup_logger  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.understat_service import (  # noqa: E402
    UNDERSTAT_LEAGUE_MAP,
    sync_understat,
)

setup_logger()


def main() -> int:
    parser = argparse.ArgumentParser(description="从 Understat 回填真实 xG")
    parser.add_argument(
        "--seasons", nargs="*", type=int, default=None,
        help="赛季年份列表，如 2024 2025；缺省用 DB 中已启用联赛的全部赛季",
    )
    parser.add_argument(
        "--leagues", nargs="*", type=int, default=None,
        help="只处理这些 API-Football league_id，如 39 140；缺省处理全部已启用联赛",
    )
    parser.add_argument("--dry-run", action="store_true", help="只解析不写库")
    args = parser.parse_args()

    print("支持的联赛映射 (API-Football league_id -> Understat slug):")
    for lid, slug in UNDERSTAT_LEAGUE_MAP.items():
        print(f"  {lid} -> {slug}")
    print("  (注意：Understat 不覆盖苏超 179)")
    print()

    db = SessionLocal()
    try:
        result = sync_understat(
            db,
            seasons=args.seasons,
            league_ids=args.leagues,
            dry_run=args.dry_run,
        )
    finally:
        db.close()

    print()
    print("=== 结果 ===")
    print(json.dumps(
        {k: v for k, v in result.items() if k != "unresolved"},
        ensure_ascii=False, indent=2,
    ))
    unresolved = result.get("unresolved") or []
    if unresolved:
        print(f"\n未解析队名 {len(unresolved)} 个（请补进 app/data/team_aliases.json）:")
        for name in unresolved:
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
