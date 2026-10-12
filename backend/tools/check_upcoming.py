"""检查今日窗口内待预测的未开赛比赛。"""
from datetime import datetime, timedelta

from sqlalchemy import text

from app.db.session import SessionLocal

now = datetime.now()
bj_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
start = bj_today + timedelta(hours=10, minutes=10)
end = start + timedelta(hours=24)
print("now        :", now)
print("window     :", start, "->", end)

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT f.id, f.date, f.home_name, f.away_name, f.league_name, f.status_short,
               (SELECT COUNT(*) FROM predictions p WHERE p.fixture_id = f.id) AS has_pred
        FROM fixtures f
        JOIN leagues l ON f.league_id = l.id
        WHERE f.date >= :s AND f.date < :e
          AND f.status_short = 'NS'
          AND l.enabled = 1
        ORDER BY f.date
    """), {"s": start, "e": end}).fetchall()
    print(f"\nNS fixtures in window: {len(rows)}")
    for r in rows:
        print(f"  {r[1]} | {r[2]} vs {r[3]} ({r[4]}) | pred={r[6]}")

    # 全库 NS 分布
    nxt = db.execute(text("""
        SELECT DATE(f.date) d, COUNT(*) c
        FROM fixtures f JOIN leagues l ON f.league_id = l.id
        WHERE f.status_short='NS' AND l.enabled=1 AND f.date >= :s
        GROUP BY DATE(f.date) ORDER BY d LIMIT 15
    """), {"s": start}).fetchall()
    print("\nupcoming NS by date:")
    for r in nxt:
        print(f"  {r[0]}: {r[1]}")
finally:
    db.close()