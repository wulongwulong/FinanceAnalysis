from __future__ import annotations
from .indicators import crossed


def round_value(v, n=3):
    return None if v is None else round(float(v), n)


def _bar_state(curr, prev):
    b, p = curr["macd_bar"], prev["macd_bar"]
    if b >= 0:
        return "红柱延长" if b > p else "红柱缩短"
    return "绿柱延长" if abs(b) > abs(p) else "绿柱缩短"


def period_state(x: list[dict]) -> dict:
    c, p = x[-1], x[-2]
    macd_cross = crossed(p["dif"], p["dea"], c["dif"], c["dea"])
    kdj_cross = crossed(p["kdj_k"], p["kdj_d"], c["kdj_k"], c["kdj_d"])
    bar_state = _bar_state(c, p)
    if c["kdj_k"] >= 80 and c["kdj_d"] >= 80:
        kdj_zone = "高位"
    elif c["kdj_k"] <= 20 and c["kdj_d"] <= 20:
        kdj_zone = "低位"
    else:
        kdj_zone = "中位"
    mas = [c.get(f"ma{n}") for n in (5, 10, 20, 60)]
    if all(v is not None for v in mas) and c["close"] > c["ma5"] > c["ma10"] > c["ma20"] > c["ma60"]:
        ma_state = "多头排列"
    elif all(v is not None for v in mas) and c["close"] < c["ma5"] < c["ma10"] < c["ma20"] < c["ma60"]:
        ma_state = "空头排列"
    elif c.get("ma20") is not None and c["close"] >= c["ma20"]:
        ma_state = "站上20日线"
    elif c.get("ma20") is not None:
        ma_state = "跌破20日线"
    else:
        ma_state = "均线不足"
    rsi = c.get("rsi14")
    rsi_state = "不足" if rsi is None else "偏热" if rsi >= 70 else "偏冷" if rsi <= 30 else "中性"
    bp = c.get("boll_pos")
    boll_state = "不足" if bp is None else "突破上轨" if bp >= 1 else "靠近上轨" if bp >= .8 else "跌破下轨" if bp <= 0 else "靠近下轨" if bp <= .2 else "通道中部"
    vr = c.get("volume_ratio_5_20")
    volume_state = "不足" if vr is None else "明显放量" if vr >= 1.35 else "明显缩量" if vr <= .75 else "量能平稳"
    return {
        "date": c["date"].isoformat(), "close": round_value(c["close"]),
        "pct_change": round_value(c["close"] / p["close"] - 1, 4),
        "macd_bar_state": bar_state, "macd_cross": macd_cross,
        "kdj_zone": kdj_zone, "kdj_cross": kdj_cross,
        "kdj_k": round_value(c["kdj_k"], 1), "kdj_d": round_value(c["kdj_d"], 1), "kdj_j": round_value(c["kdj_j"], 1),
        "ma_state": ma_state, "rsi14": round_value(rsi, 1), "rsi_state": rsi_state,
        "boll_state": boll_state, "volume_state": volume_state, "volume_ratio": round_value(vr, 2),
    }


def weak_turn_state(c: dict, p: dict, daily: dict) -> tuple[str, int, list[str]]:
    reclaim_ma20 = p.get("ma20") is not None and p["close"] < p["ma20"] and c.get("ma20") is not None and c["close"] >= c["ma20"]
    was_weak = p["macd_bar"] < 0 or (p.get("ma20") is not None and p["close"] < p["ma20"])
    weak_points, weak_reasons = 0, []
    if was_weak and daily["macd_bar_state"] in ("红柱延长", "绿柱缩短"):
        weak_points += 1; weak_reasons.append("动能改善")
    if daily["macd_cross"] == "金叉":
        weak_points += 2; weak_reasons.append("MACD金叉")
    if daily["kdj_cross"] == "金叉":
        weak_points += 1; weak_reasons.append("KDJ金叉")
    if reclaim_ma20:
        weak_points += 2; weak_reasons.append("收复MA20")
    if daily["ma_state"] == "多头排列":
        weak_points += 2; weak_reasons.append("多头排列")
    if daily["volume_state"] == "明显放量":
        weak_points += 1; weak_reasons.append("放量")
    weak_turn = "确认" if was_weak and (weak_points >= 5 or (reclaim_ma20 and daily["macd_cross"] == "金叉")) else "观察" if was_weak and weak_points >= 2 else "未触发"

    return weak_turn, weak_points, weak_reasons


def daily_scores(daily: dict, weak_turn: str, weak_reasons: list[str]) -> tuple[int, int, list[str], list[str]]:
    buy_score, sell_score, buy_reasons, sell_reasons = 0, 0, [], []
    if weak_turn == "确认":
        buy_score += 3; buy_reasons.append(f"日线弱转强确认({'、'.join(weak_reasons)})")
    elif weak_turn == "观察":
        buy_score += 1; buy_reasons.append(f"日线弱转强观察({'、'.join(weak_reasons)})")
    if daily["macd_cross"] == "金叉":
        buy_score += 2; buy_reasons.append("日线MACD金叉")
    if daily["kdj_cross"] == "金叉":
        buy_score += 1; buy_reasons.append("日线KDJ金叉")
    if daily["ma_state"] in ("站上20日线", "多头排列"):
        buy_score += 1; buy_reasons.append(f"日线{daily['ma_state']}")
    if daily["volume_state"] == "明显放量":
        buy_score += 1; buy_reasons.append("明显放量")

    if daily["kdj_zone"] == "高位" and daily["kdj_cross"] == "死叉":
        sell_score += 3; sell_reasons.append("日线KDJ高位死叉")
    elif daily["kdj_zone"] == "高位":
        sell_score += 1; sell_reasons.append("日线KDJ高位")
    if daily["macd_cross"] == "死叉":
        sell_score += 2; sell_reasons.append("日线MACD死叉")
    if daily["macd_bar_state"] in ("红柱缩短", "绿柱延长"):
        sell_score += 1; sell_reasons.append("日线动能转弱")
    if daily["ma_state"] in ("跌破20日线", "空头排列"):
        sell_score += 1; sell_reasons.append(f"日线{daily['ma_state']}")

    return buy_score, sell_score, buy_reasons, sell_reasons


def action_signal(buy_score: int, sell_score: int, ma_state: str) -> str:
    if sell_score >= 5 and sell_score >= buy_score + 2:
        return "卖出"
    elif sell_score >= 3 and sell_score >= buy_score:
        return "减仓"
    elif buy_score >= 6 and buy_score >= sell_score + 2:
        return "买入"
    elif buy_score >= 4 and buy_score > sell_score:
        return "加仓"
    elif ma_state == "空头排列" and sell_score >= 2 and buy_score <= 1:
        return "空仓"
    else:
        return "持有"
