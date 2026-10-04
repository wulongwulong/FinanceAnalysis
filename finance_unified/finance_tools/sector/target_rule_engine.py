from __future__ import annotations
from ..common.indicators import enrich, resample_weekly
from ..common.technical_rules import period_state as _period_state, weak_turn_state, daily_scores, action_signal

STRATEGY_NAME = "日线打分、周线加权"


def analyze(rows: list[dict], rules: dict) -> dict:
    d = enrich(rows)
    if len(d) < 80:
        raise ValueError("至少需要80个交易日行情")
    w = enrich(resample_weekly(rows))
    if len(w) < 30:
        raise ValueError("周线样本不足")
    daily, weekly = _period_state(d), _period_state(w)
    c, p = d[-1], d[-2]

    weak_turn, weak_points, weak_reasons = weak_turn_state(c, p, daily)
    buy_score, sell_score, buy_reasons, sell_reasons = daily_scores(daily, weak_turn, weak_reasons)

    # 保留原策略：周线动能直接给日线买卖分加权。
    if weekly["macd_bar_state"] in ("红柱延长", "绿柱缩短"):
        buy_score += 1; buy_reasons.append("周线配合偏强")
    if weekly["macd_bar_state"] in ("红柱缩短", "绿柱延长"):
        sell_score += 1; sell_reasons.append("周线配合偏弱")
    reasons = buy_reasons + sell_reasons
    action = action_signal(buy_score, sell_score, daily["ma_state"])

    target = float(rules["default_positions"][action])
    daily_text = f"{daily['macd_bar_state']}{('/'+daily['macd_cross']) if daily['macd_cross'] else ''}，KDJ{daily['kdj_zone']}{('/'+daily['kdj_cross']) if daily['kdj_cross'] else ''}，{daily['ma_state']}，RSI{daily['rsi_state']}，布林{daily['boll_state']}，{daily['volume_state']}"
    weekly_text = f"{weekly['macd_bar_state']}{('/'+weekly['macd_cross']) if weekly['macd_cross'] else ''}，KDJ{weekly['kdj_zone']}{('/'+weekly['kdj_cross']) if weekly['kdj_cross'] else ''}，{weekly['ma_state']}"
    analysis = "；".join(reasons) if reasons else "信号中性，等待更明确变化"
    return {
        "date": daily["date"], "close": daily["close"], "pct_change": daily["pct_change"],
        "strategy_name": STRATEGY_NAME,
        "action_signal": action, "buy_score": buy_score, "sell_score": sell_score,
        "default_position_pct": target, "target_position_pct": target,
        "position_source": "默认规则", "position_note": "",
        "weak_turn_state": weak_turn, "weak_turn_score": weak_points,
        "weak_turn_reasons": "、".join(weak_reasons),
        "daily": daily, "weekly": weekly,
        "daily_text": daily_text, "weekly_text": weekly_text, "analysis": analysis,
    }
