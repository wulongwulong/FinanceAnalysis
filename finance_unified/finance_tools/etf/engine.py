from __future__ import annotations
from ..common.indicators import enrich, resample_weekly
from ..common.technical_rules import round_value as _f, period_state, weak_turn_state, daily_scores, action_signal

STRATEGY_NAME = "日线触发、周线确认"

ACTION_STRENGTH = {"空仓": 0, "卖出": 1, "减仓": 2, "持有": 3, "加仓": 4, "买入": 5}
WEAK_STRENGTH = {"未触发": 0, "观察": 1, "确认": 2}
ENTRY_STRENGTH = {"暂不建仓": 0, "观察": 1, "试仓": 2, "确认建仓": 3, "强势建仓": 4}


def _period_state(x: list[dict]) -> dict:
    state = period_state(x)
    c = x[-1]
    atr = c.get("atr14")
    atr_pct = None if atr is None or not c.get("close") else atr / c["close"] * 100.0
    state.update({"atr14": _f(atr, 4), "atr_pct": _f(atr_pct, 2)})
    return state


def _weekly_bias(weekly: dict) -> tuple[str, int, int]:
    strong = weak = 0
    if weekly["macd_bar_state"] in ("红柱延长", "绿柱缩短"):
        strong += 1
    if weekly["macd_bar_state"] in ("红柱缩短", "绿柱延长"):
        weak += 1
    if weekly["macd_cross"] == "金叉":
        strong += 2
    elif weekly["macd_cross"] == "死叉":
        weak += 2
    if weekly["kdj_cross"] == "金叉":
        strong += 1
    elif weekly["kdj_cross"] == "死叉":
        weak += 1
    if weekly["ma_state"] == "多头排列":
        strong += 2
    elif weekly["ma_state"] == "站上20日线":
        strong += 1
    elif weekly["ma_state"] == "空头排列":
        weak += 2
    elif weekly["ma_state"] == "跌破20日线":
        weak += 1
    diff = strong - weak
    return ("偏强" if diff >= 2 else "偏弱" if diff <= -2 else "中性", strong, weak)


def _apply_weekly_confirmation(action: str, weekly_bias: str) -> tuple[str, str]:
    # 周线只负责确认/否决，不负责把中性日线直接升级成买卖信号。
    if action in ("买入", "加仓"):
        if weekly_bias == "偏弱":
            downgraded = "加仓" if action == "买入" else "持有"
            return downgraded, f"周线偏弱，{action}降级为{downgraded}"
        if weekly_bias == "偏强":
            return action, "周线确认偏强"
        return action, "周线中性，不加权"
    if action in ("空仓", "卖出", "减仓"):
        if weekly_bias == "偏强":
            softened = {"空仓": "卖出", "卖出": "减仓", "减仓": "持有"}[action]
            return softened, f"周线偏强，{action}缓和为{softened}"
        if weekly_bias == "偏弱":
            return action, "周线确认偏弱"
        return action, "周线中性，不加权"
    return action, f"周线{weekly_bias}"


def _technical_state(action: str, buy_score: int, sell_score: int, daily: dict, weekly_bias: str) -> str:
    if action in ("买入", "加仓"):
        return "偏强"
    if action in ("空仓", "卖出", "减仓"):
        return "偏弱"
    net = buy_score - sell_score
    if net >= 2 and weekly_bias != "偏弱":
        return "偏强"
    if net <= -2 and weekly_bias != "偏强":
        return "偏弱"
    if daily["ma_state"] in ("站上20日线", "多头排列") and weekly_bias == "偏强":
        return "偏强"
    if daily["ma_state"] in ("跌破20日线", "空头排列") and weekly_bias == "偏弱":
        return "偏弱"
    return "中性"


def _atr_risk(daily: dict, rules: dict) -> tuple[str, float | None]:
    atr_pct = daily.get("atr_pct")
    if atr_pct is None:
        return "不足", None
    thresholds = rules.get("atr_risk_thresholds_pct", {})
    low = float(thresholds.get("low", 1.5))
    medium = float(thresholds.get("medium", 2.5))
    high = float(thresholds.get("high", 4.0))
    risk = "低" if atr_pct <= low else "中" if atr_pct <= medium else "高" if atr_pct <= high else "很高"
    atr = daily.get("atr14")
    defense = None if atr is None else max(0.0, float(daily["close"]) - 2.0 * float(atr))
    return risk, defense


def _entry_state(action: str, technical_state: str, weak_turn: str, weekly_bias: str, volatility_risk: str) -> str:
    """给“当前空仓的人”看的首次建仓状态，不改变原技术动作与目标仓位。"""
    # 已经出现明确防守动作时，不建议新建仓。
    if action in ("空仓", "卖出", "减仓"):
        return "暂不建仓"

    # 极高波动时只观察，不因为技术信号直接追入。
    if volatility_risk == "很高":
        return "观察" if technical_state != "偏弱" else "暂不建仓"

    # 最强：最终动作已经到“买入”，且没有被周线否决。
    if action == "买入" and technical_state == "偏强" and weekly_bias != "偏弱":
        return "强势建仓"

    # 正式确认：加仓动作，或弱转强已经确认；周线不能偏弱。
    if action == "加仓" and technical_state == "偏强" and weekly_bias != "偏弱":
        return "确认建仓"
    if weak_turn == "确认" and technical_state == "偏强" and weekly_bias != "偏弱":
        return "确认建仓"

    # 第一笔试仓：弱转强观察 + 趋势偏强 + 周线不弱。
    if weak_turn == "观察" and technical_state == "偏强" and weekly_bias != "偏弱":
        return "试仓"

    # 没到建仓条件，但仍值得继续跟踪。
    if action in ("买入", "加仓"):
        return "观察"
    if action == "持有" and technical_state in ("偏强", "中性"):
        return "观察"
    return "暂不建仓"


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

    # 日线负责触发；周线不再直接给买卖分加分，而是在动作产生后负责确认/否决。
    buy_score, sell_score, buy_reasons, sell_reasons = daily_scores(daily, weak_turn, weak_reasons)
    reasons = buy_reasons + sell_reasons
    raw_action = action_signal(buy_score, sell_score, daily["ma_state"])

    weekly_bias, weekly_strong_score, weekly_weak_score = _weekly_bias(weekly)
    action, weekly_confirmation = _apply_weekly_confirmation(raw_action, weekly_bias)
    if weekly_confirmation:
        reasons.append(weekly_confirmation)
    technical_state = _technical_state(action, buy_score, sell_score, daily, weekly_bias)
    volatility_risk, defense_line = _atr_risk(daily, rules)
    entry_state = _entry_state(action, technical_state, weak_turn, weekly_bias, volatility_risk)

    target = float(rules["default_positions"][action])
    daily_text = f"{daily['macd_bar_state']}{('/'+daily['macd_cross']) if daily['macd_cross'] else ''}，KDJ{daily['kdj_zone']}{('/'+daily['kdj_cross']) if daily['kdj_cross'] else ''}，{daily['ma_state']}，RSI{daily['rsi_state']}，布林{daily['boll_state']}，{daily['volume_state']}"
    weekly_text = f"{weekly['macd_bar_state']}{('/'+weekly['macd_cross']) if weekly['macd_cross'] else ''}，KDJ{weekly['kdj_zone']}{('/'+weekly['kdj_cross']) if weekly['kdj_cross'] else ''}，{weekly['ma_state']}"
    analysis = "；".join(reasons) if reasons else "信号中性，等待更明确变化"
    return {
        "date": daily["date"], "close": daily["close"], "pct_change": daily["pct_change"],
        "strategy_name": STRATEGY_NAME,
        "raw_action_signal": raw_action, "action_signal": action, "buy_score": buy_score, "sell_score": sell_score,
        "default_position_pct": target, "target_position_pct": target,
        "position_source": "默认规则", "position_note": "",
        "technical_state": technical_state, "entry_state": entry_state,
        "weekly_bias": weekly_bias, "weekly_confirmation": weekly_confirmation,
        "weekly_strong_score": weekly_strong_score, "weekly_weak_score": weekly_weak_score,
        "volatility_risk": volatility_risk, "atr_pct": daily.get("atr_pct"), "defense_line": _f(defense_line, 3),
        "weak_turn_state": weak_turn, "weak_turn_score": weak_points,
        "weak_turn_reasons": "、".join(weak_reasons),
        "daily": daily, "weekly": weekly,
        "daily_text": daily_text, "weekly_text": weekly_text, "analysis": analysis,
    }


def compare_signal_change(current: dict, previous: dict | None) -> dict:
    out = dict(current)
    if not previous:
        out.update({"signal_change_text": "无昨日可比数据", "signal_change_level": "中性", "is_significant_change": False})
        return out

    changes, tones = [], []
    pa, ca = previous["action_signal"], current["action_signal"]
    if pa != ca:
        changes.append(f"技术动作：{pa} → {ca}")
        tones.append("转强" if ACTION_STRENGTH.get(ca, 0) > ACTION_STRENGTH.get(pa, 0) else "转弱")

    pe, ce = previous.get("entry_state", "暂不建仓"), current.get("entry_state", "暂不建仓")
    if pe != ce:
        changes.append(f"建仓状态：{pe} → {ce}")
        tones.append("转强" if ENTRY_STRENGTH.get(ce, 0) > ENTRY_STRENGTH.get(pe, 0) else "转弱")

    pw, cw = previous["weak_turn_state"], current["weak_turn_state"]
    if pw != cw:
        changes.append(f"弱转强：{pw} → {cw}")
        tones.append("转强" if WEAK_STRENGTH.get(cw, 0) > WEAK_STRENGTH.get(pw, 0) else "转弱")

    if current["daily"].get("macd_cross") and current["daily"].get("macd_cross") != previous["daily"].get("macd_cross"):
        cross = current["daily"]["macd_cross"]
        changes.append(f"新出现MACD{cross}")
        tones.append("转强" if cross == "金叉" else "转弱")

    if current["daily"].get("kdj_cross") and current["daily"].get("kdj_cross") != previous["daily"].get("kdj_cross"):
        cross = current["daily"]["kdj_cross"]
        changes.append(f"新出现KDJ{cross}")
        tones.append("转强" if cross == "金叉" else "转弱")

    above = ("站上20日线", "多头排列")
    below = ("跌破20日线", "空头排列")
    pma, cma = previous["daily"].get("ma_state"), current["daily"].get("ma_state")
    if pma in below and cma in above:
        changes.append("重新站上MA20")
        tones.append("转强")
    elif pma in above and cma in below:
        changes.append("跌破MA20")
        tones.append("转弱")

    if previous["daily"].get("kdj_zone") != "高位" and current["daily"].get("kdj_zone") == "高位":
        changes.append("KDJ进入高位")
        tones.append("风险")

    if previous.get("weekly_bias") != current.get("weekly_bias"):
        changes.append(f"周线：{previous.get('weekly_bias','—')} → {current.get('weekly_bias','—')}")
        tones.append("转强" if current.get("weekly_bias") == "偏强" else "转弱" if current.get("weekly_bias") == "偏弱" else "中性")

    if not changes:
        level = "中性"
        text = "无重要变化"
        significant = False
    else:
        active_tones = {t for t in tones if t != "中性"}
        if len(active_tones) > 1:
            level = "混合"
        elif active_tones:
            level = next(iter(active_tones))
        else:
            level = "中性"
        text = "；".join(changes)
        significant = any(t in ("转强", "转弱", "风险") for t in tones)

    out.update({"signal_change_text": text, "signal_change_level": level, "is_significant_change": significant})
    return out
