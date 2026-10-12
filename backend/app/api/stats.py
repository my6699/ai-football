"""数据概览 API：看板「数据总览」区块的数据源。

返回各表的规模计数、预测命中率，以及定时任务的最近/下次执行时间。
命中率只在「已评估」（即比赛已结束、结果已回填）的样本上计算。
"""
import asyncio

from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import SessionLocal

router = APIRouter()


@router.get("/stats")
async def get_stats():
    return await asyncio.to_thread(_stats_sync)


def _stats_sync() -> dict:
    db = SessionLocal()
    try:
        leagues = db.execute(
            text("SELECT COUNT(*) FROM leagues WHERE enabled = 1")
        ).scalar()
        teams = db.execute(text("SELECT COUNT(*) FROM teams")).scalar()

        fx = dict(db.execute(text(
            """SELECT COUNT(*) AS total,
                      SUM(status_short = 'FT') AS finished,
                      SUM(status_short = 'NS') AS upcoming
               FROM fixtures"""
        )).fetchone()._mapping)

        pr = dict(db.execute(text(
            """SELECT COUNT(*) AS total,
                      SUM(win_correct IS NOT NULL) AS evaluated,
                      SUM(win_correct = 1) AS win_ok,
                      SUM(over25_correct = 1) AS ou_ok,
                      SUM(handicap_correct = 1) AS handicap_ok,
                      SUM(score_in_top3 = 1) AS top3_ok
               FROM predictions"""
        )).fetchone()._mapping)

        evaluated = int(pr["evaluated"] or 0)

        def pct(hit: int):
            return round(hit / evaluated * 100, 1) if evaluated else None

        tasks = db.execute(text(
            """SELECT id, name, last_run, next_run, is_enabled
               FROM scheduler_tasks ORDER BY id"""
        )).fetchall()

        return {
            "leagues": int(leagues or 0),
            "teams": int(teams or 0),
            "fixtures": {
                "total": int(fx["total"] or 0),
                "finished": int(fx["finished"] or 0),
                "upcoming": int(fx["upcoming"] or 0),
            },
            "predictions": {
                "total": int(pr["total"] or 0),
                "evaluated": evaluated,
                "win_acc": pct(int(pr["win_ok"] or 0)),
                "ou_acc": pct(int(pr["ou_ok"] or 0)),
                "handicap_acc": pct(int(pr["handicap_ok"] or 0)),
                "top3_acc": pct(int(pr["top3_ok"] or 0)),
            },
            "tasks": [
                {
                    "task_id": r.id,
                    "name": r.name,
                    "last_run": r.last_run.isoformat() if r.last_run else None,
                    "next_run": r.next_run.isoformat() if r.next_run else None,
                    "is_enabled": bool(r.is_enabled),
                }
                for r in tasks
            ],
        }
    finally:
        db.close()