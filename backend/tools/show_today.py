"""展示今日窗口内的预测结果。"""
import json
import sys
from datetime import datetime, timedelta

from sqlalchemy import text

from app.db.session import SessionLocal

now = datetime.now()
bj_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
start = bj_today + timedelta(hours=10, minutes=10)
end = start + timedelta(hours=24)

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT p.fixture_id, p.match_date, p.win_home, p.win_draw, p.win_away,
               p.over25_prob, p.top3_scores, p.handicap,
               p.llm_win, p.llm_win_pct, p.llm_score, p.llm_handicap,
               p.llm_ou_line, p.llm_ou_type, p.llm_brief,
               COALESCE(ht.name_zh, p.home_name) home_name,
               COALESCE(at.name_zh, p.away_name) away_name,
               COALESCE(lg.name_zh, p.league_name) league_name,
               f.status_short
        FROM predictions p
        LEFT JOIN fixtures f ON p.fixture_id = f.id
        LEFT JOIN teams ht ON f.home_id = ht.id
        LEFT JOIN teams at ON f.away_id = at.id
        LEFT JOIN leagues lg ON f.league_id = lg.id
        WHERE p.match_date >= :s AND p.match_date < :e
        ORDER BY p.match_date
    """), {"s": start, "e": end}).fetchall()
    print(f"today predictions: {len(rows)}\n")
    for r in rows:
        d = dict(r._mapping)
        p = {"home": d["win_home"], "draw": d["win_draw"], "away": d["win_away"]}
        pick = max(p, key=p.get)
        cn = {"home": "主胜", "draw": "平局", "away": "客胜"}[pick]
        t3 = d["top3_scores"]
        if isinstance(t3, str):
            try:
                t3 = json.loads(t3)
            except Exception:
                t3 = None
        t3s = " / ".join(x.get("score", "") for x in t3) if isinstance(t3, list) else "-"
        print(f"{d['match_date']} | {d['home_name']} vs {d['away_name']} ({d['league_name']}) [{d['status_short']}]")
        print(f"   XGB: 主{p['home']:.2f} 平{p['draw']:.2f} 客{p['away']:.2f} -> {cn}"
              f" | 大2.5 {(d['over25_prob'] or 0):.2f} | 让球 {d['handicap']} | top3 {t3s}")
        print(f"   LLM: {d['llm_win']} {d['llm_win_pct']} | 比分 {d['llm_score']} | 大小 {d['llm_ou_type']}{d['llm_ou_line']}")
        brief = (d.get("llm_brief") or "").replace("\n", " ")
        print(f"   简述: {brief[:120]}")
        print()
finally:
    db.close()