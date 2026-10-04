#!/usr/bin/env python3
from __future__ import annotations
import csv, json, subprocess
from datetime import date, datetime, time
from pathlib import Path

from ..common.data_source import fetch_etf_daily
from .engine import analyze, compare_signal_change, ACTION_STRENGTH
from ..common.indicators import enrich
from ..common.position_grid import load_grid, apply_grid
from .history import update_history, record_event
from .report import build
from ..common.demo import etf_rows as demo_rows


def load_config(root: Path):
    rules = json.loads((root / 'config/rules.json').read_text(encoding='utf-8'))
    with (root / 'config/etf/etfs.csv').open('r', encoding='utf-8-sig', newline='') as f:
        etfs = [r for r in csv.DictReader(f) if str(r.get('enabled', '1')).strip().lower() not in ('0', 'false')]
    return rules, etfs, load_grid(root / 'config/etf/position_grid.csv')


def _alert_bits(r: dict, prev: dict | None):
    bits = []
    # KDJ高位仍保留风险提醒。
    if r['daily']['kdj_zone'] == '高位':
        bits.append(f"日线KDJ高位(K={r['daily']['kdj_k']},D={r['daily']['kdj_d']},J={r['daily']['kdj_j']})")
    if r['weekly']['kdj_zone'] == '高位':
        bits.append(f"周线KDJ高位(K={r['weekly']['kdj_k']},D={r['weekly']['kdj_d']},J={r['weekly']['kdj_j']})")
    # 弱转强只在“新触发/升级”时提醒，避免每天重复。
    if prev and prev.get('weak_turn_state') != r.get('weak_turn_state') and r.get('weak_turn_state') != '未触发':
        bits.append(f"弱转强：{prev.get('weak_turn_state')}→{r.get('weak_turn_state')}({r.get('weak_turn_reasons') or '组合信号'})")
    # 六档动作发生变化时提醒。
    if prev and prev.get('action_signal') != r.get('action_signal'):
        direction = '升级' if ACTION_STRENGTH.get(r['action_signal'], 0) > ACTION_STRENGTH.get(prev['action_signal'], 0) else '降级'
        bits.append(f"技术动作{direction}：{prev.get('action_signal')}→{r.get('action_signal')}")
    return bits


def collect(root: Path, demo=False, mode='report', fetcher=None, extra_securities=()):
    rules, etfs, grid = load_config(root); items = []; errors = []; alerts = []
    known = {e['code'].strip() for e in etfs}
    for security in extra_securities:
        if security['code'] not in known:
            etfs.append(security)
            known.add(security['code'])
    today = date.today().isoformat(); now = datetime.now()

    for i, e in enumerate(etfs):
        code = e['code'].strip(); name = e['name'].strip() or code
        try:
            rows, source = fetcher(code) if fetcher is not None else (demo_rows(10 + i), '离线模拟数据') if demo else fetch_etf_daily(code)
            current = analyze(rows, rules)
            previous = analyze(rows[:-1], rules) if len(rows) > 81 else None
            r = compare_signal_change(current, previous)
            r.update({'code': code, 'name': name, 'source': source, 'asset_type': e.get('asset_type', 'ETF')})
            r = apply_grid(r, grid)
            r['is_fresh'] = (r['date'] == today) if not demo else True
            items.append(r)

            if not demo and r['is_fresh']:
                record_event(root / 'data/etf/events.csv', r)
                # 正式信号只在收盘后写入，盘中变化只进 events.csv。
                if mode == 'report' and now.time() >= time(15, 0):
                    update_history(root / 'data/etf/signals.csv', r, enrich(rows))

            if r['is_fresh']:
                bits = _alert_bits(r, previous)
                if bits:
                    alerts.append(f"{code} {name} | 技术动作:{r['action_signal']} | 趋势状态:{r['technical_state']} | 建仓状态:{r['entry_state']} | 目标仓位:{r['target_position_pct']:.0f}% | " + '；'.join(bits))
            print(f"OK  {code} {name}: {r['action_signal']} / 趋势{r['technical_state']} / 建仓{r['entry_state']} / 目标{r['target_position_pct']:.0f}% / {r['signal_change_text']}")
        except Exception as ex:
            errors.append({'code': code, 'name': name, 'error': str(ex)}); print(f"ERR {code} {name}: {ex}")

    return items, errors, alerts


def run(root: Path, demo=False, mode='report') -> Path:
    items, errors, alerts = collect(root, demo=demo, mode=mode)
    fresh_count = sum(1 for x in items if x.get('is_fresh'))
    if mode == 'alert':
        if items and fresh_count == 0 and not demo:
            latest = max((x['date'] for x in items), default='—')
            text = f"午间提醒：\n今日无新行情（最新行情日 {latest}），不发送重复提醒。\n"
        else:
            text = 'KDJ高位 / 弱转强新触发 / 技术动作变化提醒：\n' + ('\n'.join(alerts) if alerts else '本次无触发。') + '\n'
        p = root / 'outputs/etf/latest_alert.txt'; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding='utf-8')
        print('\n' + text); print(f'提醒文件：{p}')
        if alerts and fresh_count > 0 and not demo:
            summary = f'本次触发 {len(alerts)} 只ETF，请查看 latest_alert.txt'
            try:
                subprocess.run(['/usr/bin/osascript', '-e', f'display notification "{summary}" with title "ETF每日技术监控"'], check=False, capture_output=True, text=True)
            except Exception:
                pass
    else:
        # 重要变化优先，其次按动作强弱和买卖分差排序。
        items.sort(key=lambda x: (1 if x.get('is_significant_change') else 0, ACTION_STRENGTH.get(x['action_signal'], 0), x['buy_score'] - x['sell_score']), reverse=True)
        md, ht = build(items, errors, root / 'outputs/etf')
        print(f"\n完成：{len(items)} 只ETF，异常 {len(errors)} 只\nMarkdown: {md}\nHTML: {ht}")
        if not demo:
            msg = f"日报已生成：{len(items)}只ETF，重要变化{sum(1 for x in items if x.get('is_significant_change'))}只，异常{len(errors)}只"
            try:
                subprocess.run(['/usr/bin/osascript', '-e', f'display notification "{msg}" with title "ETF每日技术监控"'], check=False, capture_output=True, text=True)
            except Exception:
                pass
    if not items:
        raise RuntimeError('ETF分析失败：' + '；'.join(f"{e['code']} {e['error']}" for e in errors))
    return root / 'outputs/etf' / ('latest_alert.txt' if mode == 'alert' else 'latest.html')
