"""日报：今日赛事预测 + 昨日预测命中率。直接查库。"""
import json
from datetime import datetime, timedelta

from sqlalchemy import text

from app.db.session import SessionLocal

TODAY = "2026-10-10"
YESTERDAY = "2026-10-09"


def window(date_str: str):
    """与 API 一致：当天 10:10 ~ 次日 10:10。"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    s = d + timedelta(hours=10, minutes=10)
    e = d + timedelta(hours=34, minutes=10)
    return s.strftime("%Y-%m-%d %H:%M:%S"), e.strftime("%Y-%m-%d %H:%M:%S")


def main():
    db = SessionLocal()
    try:
        cols = [r[0] for r in db.execute(text("SHOW COLUMNS FROM predictions")).fetchall()]
        print("PREDICTION COLUMNS:", ", ".join(cols))

        # ── 今日预测 ──
        s, e = window(TODAY)
        rows = db.execute(text("""
            SELECT p.fixture_id, p.match_date, p.win_home, p.win_draw, p.win_away,
                   p.over25_prob, p.top3_scores, p.handicap,
                   p.llm_win, p.llm_score, p.llm_win_pct, p.llm_handicap,
                   p.llm_over_under, p.llm_ou_line, p.llm_ou_type,
                   COALESCE(ht.name_zh, p.home_name) home_name,
                   COALESCE(at.name_zh, p.away_name) away_name,
                   COALESCE(lg.name_zh, p.league_name) league_name,
                   f.status_short, f.goals_home, f.goals_away
            FROM predictions p
            LEFT JOIN fixtures f ON p.fixture_id = f.id
            LEFT JOIN teams ht ON f.home_id = ht.id
            LEFT JOIN teams at ON f.away_id = at.id
            LEFT JOIN leagues lg ON f.league_id = lg.id
            WHERE p.match_date >= :s AND p.match_date < :e
            ORDER BY p.match_date ASC
        """), {"s": s, "e": e}).fetchall()
        print(f"\n=== TODAY ({TODAY}) predictions: {len(rows)} ===")
        for r in rows:
            d = dict(r._mapping)
            print(json.dumps(d, ensure_ascii=False, default=str))

        # ── 昨日命中 ──
        s2, e2 = window(YESTERDAY)
        rows2 = db.execute(text("""
            SELECT p.fixture_id, p.match_date, p.win_home, p.win_draw, p.win_away,
                   p.over25_prob, p.top3_scores, p.handicap,
                   f.status_short, f.goals_home, f.goals_away
            FROM predictions p
            LEFT JOIN fixtures f ON p.fixture_id = f.id
            WHERE p.match_date >= :s AND p.match_date < :e
              AND f.goals_home IS NOT NULL AND f.goals_away IS NOT NULL
            ORDER BY p.match_date ASC
        """), {"s": s2, "e": e2}).fetchall()
        print(f"\n=== YESTERDAY ({YESTERDAY}) finished predictions: {len(rows2)} ===")
        win_hit = over_hit = top3_hit = 0
        n = 0
        for r in rows2:
            d = dict(r._mapping)
            gh, ga = d["goals_home"], d["goals_away"]
            if gh is None or ga is None:
                continue
            n += 1
            probs = {"home": d["win_home"] or 0, "draw": d["win_draw"] or 0, "away": d["win_away"] or 0}
            pred = max(probs, key=probs.get)
            actual = "home" if gh > ga else ("away" if ga > gh else "draw")
            w = pred == actual
            win_hit += w
            tot = gh + ga
            o = (d["over25_prob"] or 0) >= 0.5
            ov = o == (tot > 2.5)
            over_hit += ov
            t3 = d["top3_scores"]
            if isinstance(t3, str):
                try:
                    t3 = json.loads(t3)
                except Exception:
                    t3 = None
            actual_score = f"{gh}-{ga}"
            in3 = False
            if isinstance(t3, list):
                in3 = any((x.get("score") if isinstance(x, dict) else None) == actual_score for x in t3)
            top3_hit += in3
            print(json.dumps({
                "match": f"{d['fixture_id']}", "date": str(d["match_date"]),
                "pred_win": pred, "actual": actual_score, "win_hit": w,
                "over25_pred": o, "over25_hit": ov, "top3_hit": in3,
            }, ensure_ascii=False))
        if n:
            print(f"\nSUMMARY yesterday n={n} win_acc={win_hit/n:.1%} over25_acc={over_hit/n:.1%} top3_acc={top3_hit/n:.1%}")
        else:
            print("\nSUMMARY yesterday: 无已完赛的预测样本")
    finally:
        db.close()


if __name__ == "__main__":
    main()