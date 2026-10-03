from __future__ import annotations
from ..common.indicators import enrich, resample_weekly, crossed


def _f(v, n=3):
    return None if v is None else round(float(v), n)


def _bar_state(curr, prev):
    b, p = curr["macd_bar"], prev["macd_bar"]
    if b >= 0:
        return "红柱延长" if b > p else "红柱缩短"
    return "绿柱延长" if abs(b) > abs(p) else "绿柱缩短"


def _period_state(x: list[dict]) -> dict:
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
        "date": c["date"].isoformat(), "close": _f(c["close"]),
        "pct_change": _f(c["close"] / p["close"] - 1, 4),
        "macd_bar_state": bar_state, "macd_cross": macd_cross,
        "kdj_zone": kdj_zone, "kdj_cross": kdj_cross,
        "kdj_k": _f(c["kdj_k"], 1), "kdj_d": _f(c["kdj_d"], 1), "kdj_j": _f(c["kdj_j"], 1),
        "ma_state": ma_state, "rsi14": _f(rsi, 1), "rsi_state": rsi_state,
        "boll_state": boll_state, "volume_state": volume_state, "volume_ratio": _f(vr, 2),
    }


def analyze(rows: list[dict], rules: dict) -> dict:
    d = enrich(rows)
    if len(d) < 80:
        raise ValueError("至少需要80个交易日行情")
    w = enrich(resample_weekly(rows))
    if len(w) < 30:
        raise ValueError("周线样本不足")
    daily, weekly = _period_state(d), _period_state(w)
    c, p = d[-1], d[-2]

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

    buy_score, sell_score, reasons = 0, 0, []
    weekly_strong = weekly["macd_bar_state"] in ("红柱延长", "绿柱缩短")
    weekly_weak = weekly["macd_bar_state"] in ("红柱缩短", "绿柱延长")

    if weak_turn == "确认":
        buy_score += 3; reasons.append(f"日线弱转强确认({'、'.join(weak_reasons)})")
    elif weak_turn == "观察":
        buy_score += 1; reasons.append(f"日线弱转强观察({'、'.join(weak_reasons)})")
    if daily["macd_cross"] == "金叉":
        buy_score += 2; reasons.append("日线MACD金叉")
    if daily["kdj_cross"] == "金叉":
        buy_score += 1; reasons.append("日线KDJ金叉")
    if daily["ma_state"] in ("站上20日线", "多头排列"):
        buy_score += 1; reasons.append(f"日线{daily['ma_state']}")
    if daily["volume_state"] == "明显放量":
        buy_score += 1; reasons.append("明显放量")
    if weekly_strong:
        buy_score += 1; reasons.append("周线配合偏强")

    if daily["kdj_zone"] == "高位" and daily["kdj_cross"] == "死叉":
        sell_score += 3; reasons.append("日线KDJ高位死叉")
    elif daily["kdj_zone"] == "高位":
        sell_score += 1; reasons.append("日线KDJ高位")
    if daily["macd_cross"] == "死叉":
        sell_score += 2; reasons.append("日线MACD死叉")
    if daily["macd_bar_state"] in ("红柱缩短", "绿柱延长"):
        sell_score += 1; reasons.append("日线动能转弱")
    if daily["ma_state"] in ("跌破20日线", "空头排列"):
        sell_score += 1; reasons.append(f"日线{daily['ma_state']}")
    if weekly_weak:
        sell_score += 1; reasons.append("周线配合偏弱")

    if sell_score >= 5 and sell_score >= buy_score + 2:
        action = "卖出"
    elif sell_score >= 3 and sell_score >= buy_score:
        action = "减仓"
    elif buy_score >= 6 and buy_score >= sell_score + 2:
        action = "买入"
    elif buy_score >= 4 and buy_score > sell_score:
        action = "加仓"
    elif daily["ma_state"] == "空头排列" and sell_score >= 2 and buy_score <= 1:
        action = "空仓"
    else:
        action = "持有"

    target = float(rules["default_positions"][action])
    daily_text = f"{daily['macd_bar_state']}{('/'+daily['macd_cross']) if daily['macd_cross'] else ''}，KDJ{daily['kdj_zone']}{('/'+daily['kdj_cross']) if daily['kdj_cross'] else ''}，{daily['ma_state']}，RSI{daily['rsi_state']}，布林{daily['boll_state']}，{daily['volume_state']}"
    weekly_text = f"{weekly['macd_bar_state']}{('/'+weekly['macd_cross']) if weekly['macd_cross'] else ''}，KDJ{weekly['kdj_zone']}{('/'+weekly['kdj_cross']) if weekly['kdj_cross'] else ''}，{weekly['ma_state']}"
    analysis = "；".join(reasons) if reasons else "信号中性，等待更明确变化"
    return {
        "date": daily["date"], "close": daily["close"], "pct_change": daily["pct_change"],
        "action_signal": action, "buy_score": buy_score, "sell_score": sell_score,
        "default_position_pct": target, "target_position_pct": target,
        "position_source": "默认规则", "position_note": "",
        "weak_turn_state": weak_turn, "weak_turn_score": weak_points,
        "weak_turn_reasons": "、".join(weak_reasons),
        "daily": daily, "weekly": weekly,
        "daily_text": daily_text, "weekly_text": weekly_text, "analysis": analysis,
    }
