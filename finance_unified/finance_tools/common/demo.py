from __future__ import annotations
from datetime import date, timedelta
import math
import random


def _business_days(n):
    d = date.today(); out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def sector_rows(seed=1, n=280, base=1000):
    rng = random.Random(seed); dates = _business_days(n); close = base; rows = []
    for i, d in enumerate(dates):
        phase = max(0, i - (n - 40)) / 39
        drift = .0002 + (-.0015 + .0035 * phase if i >= n - 40 else 0)
        ret = rng.gauss(drift, .012); close *= math.exp(ret)
        op = close * (1 + rng.gauss(0, .003))
        hi = max(op, close) * (1 + rng.uniform(.001, .012))
        lo = min(op, close) * (1 - rng.uniform(.001, .012))
        vol = rng.randint(1_000_000, 15_000_000)
        rows.append({'date': d, 'open': op, 'high': hi, 'low': lo, 'close': close, 'volume': vol})
    return rows


def etf_rows(seed=7):
    rng = random.Random(seed); dates = _business_days(260); close = 1.0; rows = []
    for i, d in enumerate(dates):
        drift = .0005 + (-.003 + .007 * max(0, i - (len(dates) - 25)) / 24 if i >= len(dates) - 25 else 0)
        ret = rng.gauss(drift, .012); close *= math.exp(ret)
        op = close * (1 + rng.gauss(0, .003))
        hi = max(op, close) * (1 + rng.uniform(.001, .012))
        lo = min(op, close) * (1 - rng.uniform(.001, .012))
        vol = rng.randint(5_000_000, 25_000_000)
        rows.append({'date': d, 'open': op, 'high': hi, 'low': lo, 'close': close, 'volume': vol})
    return rows
