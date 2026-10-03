from __future__ import annotations
from datetime import date, datetime
from statistics import pstdev
from typing import Iterable

REQUIRED = ("date", "open", "high", "low", "close", "volume")


def _to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v)[:10]
    return datetime.strptime(s, "%Y-%m-%d").date()


def normalize_ohlcv(rows: Iterable[dict]) -> list[dict]:
    out = []
    seen = set()
    for raw in rows:
        if not all(k in raw for k in REQUIRED):
            raise ValueError(f"行情字段不完整，需要: {', '.join(REQUIRED)}")
        try:
            d = _to_date(raw["date"])
            item = {
                "date": d,
                "open": float(raw["open"]),
                "high": float(raw["high"]),
                "low": float(raw["low"]),
                "close": float(raw["close"]),
                "volume": float(raw.get("volume") or 0),
            }
        except (TypeError, ValueError):
            continue
        if d in seen:
            continue
        seen.add(d)
        out.append(item)
    out.sort(key=lambda x: x["date"])
    return out


def _sma(values: list[float], n: int) -> list[float | None]:
    result = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            result[i] = total / n
    return result


def _ema(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    result = [values[0]]
    for v in values[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def _rolling_min(values: list[float], n: int) -> list[float]:
    return [min(values[max(0, i - n + 1):i + 1]) for i in range(len(values))]


def _rolling_max(values: list[float], n: int) -> list[float]:
    return [max(values[max(0, i - n + 1):i + 1]) for i in range(len(values))]


def _rolling_std(values: list[float], n: int) -> list[float | None]:
    out = [None] * len(values)
    for i in range(n - 1, len(values)):
        out[i] = pstdev(values[i - n + 1:i + 1])
    return out


def _ewm_alpha(values: list[float], alpha: float) -> list[float]:
    if not values:
        return []
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def _rsi(close: list[float], n: int = 14) -> list[float | None]:
    out = [None] * len(close)
    if len(close) <= n:
        return out
    gains = [0.0] * len(close)
    losses = [0.0] * len(close)
    for i in range(1, len(close)):
        delta = close[i] - close[i - 1]
        gains[i] = max(delta, 0.0)
        losses[i] = max(-delta, 0.0)
    avg_gain = sum(gains[1:n + 1]) / n
    avg_loss = sum(losses[1:n + 1]) / n
    out[n] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(n + 1, len(close)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def enrich(rows: Iterable[dict]) -> list[dict]:
    x = normalize_ohlcv(rows)
    close = [r["close"] for r in x]
    high = [r["high"] for r in x]
    low = [r["low"] for r in x]
    vol = [r["volume"] for r in x]
    if not x:
        return []

    ma = {n: _sma(close, n) for n in (5, 10, 20, 60)}
    ema12, ema26 = _ema(close, 12), _ema(close, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = _ema(dif, 9)
    macd_bar = [2 * (a - b) for a, b in zip(dif, dea)]

    ll, hh = _rolling_min(low, 9), _rolling_max(high, 9)
    rsv = []
    for c, lo, hi in zip(close, ll, hh):
        rsv.append(50.0 if hi == lo else (c - lo) / (hi - lo) * 100.0)
    k = _ewm_alpha(rsv, 1 / 3)
    d = _ewm_alpha(k, 1 / 3)
    j = [3 * a - 2 * b for a, b in zip(k, d)]

    rsi14 = _rsi(close, 14)
    boll_mid = ma[20]
    boll_std = _rolling_std(close, 20)
    boll_upper, boll_lower, boll_pos = [], [], []
    for c, mid, sd in zip(close, boll_mid, boll_std):
        if mid is None or sd is None:
            boll_upper.append(None); boll_lower.append(None); boll_pos.append(None)
        else:
            up, lo = mid + 2 * sd, mid - 2 * sd
            boll_upper.append(up); boll_lower.append(lo)
            boll_pos.append(None if up == lo else (c - lo) / (up - lo))

    v5, v20 = _sma(vol, 5), _sma(vol, 20)
    vr = [None if a is None or b in (None, 0) else a / b for a, b in zip(v5, v20)]

    tr = []
    for i in range(len(x)):
        if i == 0:
            tr.append(high[i] - low[i])
        else:
            pc = close[i - 1]
            tr.append(max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc)))
    atr14 = _sma(tr, 14)

    for i, row in enumerate(x):
        for n in (5, 10, 20, 60):
            row[f"ma{n}"] = ma[n][i]
        row.update({
            "dif": dif[i], "dea": dea[i], "macd_bar": macd_bar[i],
            "kdj_k": k[i], "kdj_d": d[i], "kdj_j": j[i], "rsi14": rsi14[i],
            "boll_mid": boll_mid[i], "boll_upper": boll_upper[i], "boll_lower": boll_lower[i], "boll_pos": boll_pos[i],
            "volume_ma5": v5[i], "volume_ma20": v20[i], "volume_ratio_5_20": vr[i], "atr14": atr14[i],
        })
    return x


def resample_weekly(rows: Iterable[dict]) -> list[dict]:
    x = normalize_ohlcv(rows)
    buckets = {}
    order = []
    for r in x:
        iso = r["date"].isocalendar()
        key = (iso[0], iso[1])
        if key not in buckets:
            buckets[key] = {
                "date": r["date"], "open": r["open"], "high": r["high"], "low": r["low"],
                "close": r["close"], "volume": r["volume"]
            }
            order.append(key)
        else:
            b = buckets[key]
            b["date"] = r["date"]
            b["high"] = max(b["high"], r["high"])
            b["low"] = min(b["low"], r["low"])
            b["close"] = r["close"]
            b["volume"] += r["volume"]
    return [buckets[k] for k in order]


def crossed(prev_a, prev_b, curr_a, curr_b) -> str:
    if None in (prev_a, prev_b, curr_a, curr_b):
        return ""
    if prev_a <= prev_b and curr_a > curr_b:
        return "金叉"
    if prev_a >= prev_b and curr_a < curr_b:
        return "死叉"
    return ""
