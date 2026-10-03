from __future__ import annotations
from pathlib import Path
from datetime import datetime
import csv

FIELDS = [
    "signal_date", "code", "name", "close", "action_signal", "trend_state", "entry_state",
    "target_position_pct", "weak_turn_state", "weekly_bias", "volatility_risk",
    "buy_score", "sell_score", "ret_5", "ret_10", "ret_20", "ret_40", "max_drawdown_20"
]
EVENT_FIELDS = [
    "run_time", "signal_date", "code", "name", "action_signal", "trend_state", "entry_state",
    "weak_turn_state", "signal_change_level", "signal_change_text"
]


def _read_csv(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, fields: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def _max_drawdown_close(future: list[dict], entry: float, days: int = 20) -> float | None:
    # 真正的 peak-to-trough 最大回撤：用每日收盘价计算，结果始终 <= 0。
    if not future:
        return None
    closes = [entry]
    for x in future[1:days + 1]:
        try:
            closes.append(float(x["close"]))
        except Exception:
            pass
    if len(closes) < 2:
        return 0.0
    peak = closes[0]
    max_dd = 0.0
    for c in closes[1:]:
        peak = max(peak, c)
        dd = c / peak - 1.0
        max_dd = min(max_dd, dd)
    return max_dd * 100.0


def update_history(path: Path, item: dict, enriched_daily: list[dict] | None = None):
    """只保存收盘正式信号；同一交易日同一代码只保留最终一条。"""
    rows = _read_csv(path)
    key = (str(item["date"]), item["code"])
    same_idx = None
    for i, r in enumerate(rows):
        if (r.get("signal_date"), r.get("code")) == key:
            same_idx = i
            break

    qualifies = item["weak_turn_state"] != "未触发" or item["action_signal"] in ("买入", "加仓", "减仓", "卖出", "空仓")
    payload = {
        "signal_date": item["date"], "code": item["code"], "name": item["name"], "close": item["close"],
        "action_signal": item["action_signal"], "trend_state": item.get("technical_state", ""),
        "entry_state": item.get("entry_state", ""),
        "target_position_pct": item["target_position_pct"], "weak_turn_state": item["weak_turn_state"],
        "weekly_bias": item.get("weekly_bias", ""), "volatility_risk": item.get("volatility_risk", ""),
        "buy_score": item["buy_score"], "sell_score": item["sell_score"],
        "ret_5": "", "ret_10": "", "ret_20": "", "ret_40": "", "max_drawdown_20": ""
    }
    if qualifies:
        if same_idx is None:
            rows.append(payload)
        else:
            old = rows[same_idx]
            for k in ("ret_5", "ret_10", "ret_20", "ret_40", "max_drawdown_20"):
                payload[k] = old.get(k, "")
            rows[same_idx] = payload
    elif same_idx is not None:
        # 如果盘中曾经触发、收盘已消失，则正式历史不保留这条盘中信号。
        rows.pop(same_idx)

    if enriched_daily:
        d = sorted(enriched_daily, key=lambda x: x["date"])
        for r in rows:
            if r.get("code") != item["code"]:
                continue
            try:
                sd = datetime.strptime(r["signal_date"], "%Y-%m-%d").date()
            except Exception:
                continue
            future = [x for x in d if x["date"] >= sd]
            if not future:
                continue
            try:
                entry = float(r["close"])
            except Exception:
                continue
            for n in (5, 10, 20, 40):
                if len(future) > n:
                    r[f"ret_{n}"] = f"{(float(future[n]['close']) / entry - 1) * 100:.2f}"
            dd = _max_drawdown_close(future, entry, 20)
            if dd is not None:
                r["max_drawdown_20"] = f"{dd:.2f}"

    _write_csv(path, FIELDS, rows)


def record_event(path: Path, item: dict):
    if not item.get("is_significant_change"):
        return
    rows = _read_csv(path)
    payload = {
        "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signal_date": item["date"], "code": item["code"], "name": item["name"],
        "action_signal": item["action_signal"], "trend_state": item.get("technical_state", ""),
        "entry_state": item.get("entry_state", ""),
        "weak_turn_state": item["weak_turn_state"], "signal_change_level": item.get("signal_change_level", ""),
        "signal_change_text": item.get("signal_change_text", ""),
    }
    key = (payload["signal_date"], payload["code"], payload["action_signal"], payload["signal_change_text"])
    exists = any((r.get("signal_date"), r.get("code"), r.get("action_signal"), r.get("signal_change_text")) == key for r in rows)
    if not exists:
        rows.append(payload)
        _write_csv(path, EVENT_FIELDS, rows)
