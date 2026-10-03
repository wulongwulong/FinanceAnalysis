from __future__ import annotations
from datetime import datetime, timedelta
import json
import subprocess
import urllib.parse
import urllib.request

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36'


def _http_get(url, params=None, headers=None, timeout=18):
    headers = {'User-Agent': UA, **(headers or {})}
    full = url + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(full, headers=headers)
    first_error = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        first_error = e
    # macOS 上如果 Python 自带 SSL 与某网站握手异常，回退系统 curl。
    try:
        cmd = ['/usr/bin/curl', '-L', '--silent', '--show-error', '--max-time', str(timeout)]
        for k, v in headers.items():
            cmd += ['-H', f'{k}: {v}']
        cmd += [full]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout
        raise RuntimeError(p.stderr.strip() or f'curl exit {p.returncode}')
    except Exception as e:
        raise RuntimeError(f'网络请求失败：urllib={first_error}; curl={e}') from e


def _json_get(url, params=None, headers=None, timeout=18):
    txt = _http_get(url, params, headers, timeout)
    try:
        return json.loads(txt)
    except Exception as e:
        raise RuntimeError(f'返回内容不是有效JSON: {txt[:160]}') from e


def list_sw_indices(level):
    url = 'https://www.swsresearch.com/institute-sw/api/index_publish/current/'
    base = {'page': '1', 'page_size': '50', 'indextype': level}
    first = _json_get(url, base)
    count = int((first.get('data') or {}).get('count') or 0)
    out = []; seen = set()
    for page in range(1, max(1, (count + 49) // 50) + 1):
        data = first if page == 1 else _json_get(url, {**base, 'page': str(page)})
        for item in (data.get('data') or {}).get('results') or []:
            if isinstance(item, dict):
                code = item.get('swindexcode') or item.get('swIndexCode') or item.get('indexCode')
                name = item.get('swindexname') or item.get('swIndexName') or item.get('indexName')
            else:
                code = item[0] if len(item) > 0 else None
                name = item[1] if len(item) > 1 else None
            if code and name and str(code) not in seen:
                seen.add(str(code)); out.append({'code': str(code), 'name': str(name)})
    if not out:
        raise RuntimeError(f'申万{level}列表为空')
    return out


def fetch_sw_history(code):
    data = _json_get('https://www.swsresearch.com/institute-sw/api/index_publish/trend/',
                     {'swindexcode': str(code), 'period': 'DAY'})
    rows = [
        {'date': r.get('bargaindate'), 'open': r.get('openindex'), 'high': r.get('maxindex'),
         'low': r.get('minindex'), 'close': r.get('closeindex'), 'volume': r.get('bargainamount') or 0}
        for r in data.get('data') or [] if isinstance(r, dict)
    ]
    if len(rows) < 130:
        raise RuntimeError(f'申万历史行情不足({len(rows)}条)')
    return rows


def market_id(code):
    return '1' if str(code).startswith(('5', '6', '9')) else '0'


def market_prefix(code):
    return 'sh' if str(code).startswith(('5', '6', '9')) else 'sz'


def _eastmoney_kline(code, secid=None, lookback=950):
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=lookback)).strftime('%Y%m%d')
    params = {
        'secid': secid or f'{market_id(code)}.{code}', 'ut': '7eea3edcaed734bea9cbfc24409ed989',
        'fields1': 'f1,f2,f3,f4,f5,f6', 'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt': '101', 'fqt': '1', 'beg': start, 'end': end,
    }
    data = _json_get('https://push2his.eastmoney.com/api/qt/stock/kline/get', params)
    rows = []
    for line in (data.get('data') or {}).get('klines') or []:
        p = line.split(',')
        if len(p) >= 6:
            rows.append({'date': p[0], 'open': p[1], 'close': p[2], 'high': p[3], 'low': p[4], 'volume': p[5]})
    if len(rows) < 80:
        raise RuntimeError(f'东方财富行情不足({len(rows)}条)')
    return rows


def _sina_kline(symbol):
    data = _json_get('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData',
                     {'symbol': symbol, 'scale': '240', 'ma': 'no', 'datalen': '1023'},
                     {'Referer': 'https://finance.sina.com.cn/'})
    rows = [{'date': r.get('day'), 'open': r.get('open'), 'high': r.get('high'),
             'low': r.get('low'), 'close': r.get('close'), 'volume': r.get('volume') or 0}
            for r in data or []]
    if len(rows) < 80:
        raise RuntimeError(f'新浪行情不足({len(rows)}条)')
    return rows


def _fetch_daily(code, lookback, sources, error_label, secid=None, symbol=None):
    errors = []
    try:
        return _eastmoney_kline(str(code), secid, lookback), sources[0]
    except Exception as e:
        errors.append(f'东财:{e}')
    try:
        return _sina_kline(symbol or market_prefix(code) + str(code)), sources[1]
    except Exception as e:
        errors.append(f'新浪:{e}')
    raise RuntimeError(error_label + '获取失败；' + ' | '.join(errors))


def fetch_security(code, lookback_days=950):
    """获取沪深交易所上市标的日线；ETF、股票、LOF共用。"""
    return _fetch_daily(code, lookback_days, ('东方财富行情', '新浪行情(备用)'), '标的行情')


def fetch_etf_daily(code, lookback_days=900):
    return _fetch_daily(code, lookback_days, ('东方财富 ETF', '新浪 ETF(备用)'), 'ETF行情')


def fetch_hs300():
    return _fetch_daily('000300', 950, ('东方财富沪深300', '新浪沪深300(备用)'),
                        '沪深300', secid='1.000300', symbol='sh000300')
