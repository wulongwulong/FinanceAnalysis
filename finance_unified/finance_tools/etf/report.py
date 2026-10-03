from __future__ import annotations
from pathlib import Path
from datetime import datetime, date
import html


def pct(v):
    return '—' if v is None else f"{v * 100:.2f}%"


def _md_weak(x):
    return x['weak_turn_state'] + (f"({x['weak_turn_reasons']})" if x['weak_turn_state'] != '未触发' and x['weak_turn_reasons'] else '')


def _risk_text(x):
    ap = x.get('atr_pct')
    dl = x.get('defense_line')
    risk = _risk_label(x.get('volatility_risk', '不足'))
    if ap is None:
        return risk
    defense = '' if dl is None else f" / 参考防守线 {dl:.3f}"
    return f"{risk}(ATR {ap:.2f}%){defense}"


def _esc(v):
    return html.escape(str(v if v is not None else ''))


def _badge(text, cls):
    return f"<span class='badge {cls}'>{_esc(text)}</span>"


def _action_badge(v):
    return _badge(v, 'pos') if v in ('买入', '加仓') else _badge(v, 'neg') if v in ('减仓', '卖出', '空仓') else _badge(v, 'neu')


def _state_badge(v):
    return _badge(v, 'pos') if '偏强' in v else _badge(v, 'neg') if '偏弱' in v else _badge(v, 'neu')


def _entry_badge(v):
    if v == '强势建仓':
        return _badge(v, 'pos')
    if v == '确认建仓':
        return _badge(v, 'pos')
    if v == '试仓':
        return _badge(v, 'warn')
    if v == '观察':
        return _badge(v, 'neu')
    return _badge(v, 'neg')


def _risk_label(risk):
    return {
        '低': '低波动｜相对稳定',
        '中': '中等波动｜正常',
        '高': '高波动｜谨慎',
        '很高': '极高波动｜高风险',
        '不足': '数据不足',
    }.get(risk, str(risk))


def _weak_badge(v):
    return _badge(v, 'pos') if v == '确认' else _badge(v, 'warn') if v == '观察' else _badge(v, 'muted')


def _change_badge(level, text):
    cls = {'转强': 'pos', '转弱': 'neg', '风险': 'warn', '混合': 'mix'}.get(level, 'muted')
    return _badge(text, cls)


def _risk_badge(x):
    risk = x.get('volatility_risk', '不足')
    cls = 'danger' if risk == '很高' else 'warn' if risk == '高' else 'neu' if risk == '中' else 'muted'
    ap = x.get('atr_pct')
    label = _risk_label(risk)
    txt = label if ap is None else f"{label} · {ap:.2f}%"
    return _badge(txt, cls)


def _row_class(x):
    if not x.get('is_significant_change'):
        return ''
    return {'转强': 'row-up', '转弱': 'row-down', '风险': 'row-risk', '混合': 'row-mix'}.get(x.get('signal_change_level'), 'row-change')


def build(items, errors, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    md = out_dir / f'ETF每日技术监控_{stamp}.md'
    ht = out_dir / f'ETF每日技术监控_{stamp}.html'
    today = date.today().isoformat()
    fresh_count = sum(1 for x in items if x.get('is_fresh'))
    latest_market_date = max((x.get('date', '') for x in items), default='—')
    changes = [x for x in items if x.get('is_significant_change')]

    freshness = '今日行情已更新' if fresh_count else f'今日无新行情，最新行情日 {latest_market_date}；不写入重复正式信号'
    lines = [
        '# ETF每日技术监控 V1.0', '', f'生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}', f'行情状态：{freshness}', '',
        '规则：日线负责触发，周线负责确认/否决；技术动作对应默认目标仓位，`config/etf/position_grid.csv` 命中时网格仓位优先。', '',
        '## 今日重要变化', ''
    ]
    if changes:
        for x in changes:
            lines.append(f"- **{x['code']} {x['name']}**｜{x['signal_change_text']}｜操作建议 {x['action_signal']} / 趋势{x['technical_state']} / 建仓{x['entry_state']} / 目标仓位{x['target_position_pct']:.0f}%")
    else:
        lines.append('- 本次无重要变化。')
    lines += ['', '## 全部监控', '',
        '|代码|名称|日期|收盘价|涨跌幅|技术动作|趋势状态|建仓状态|目标仓位|仓位来源|信号变化|日线状态|周线状态|周线确认|弱转强|波动风险/参考防守线|分析|',
        '|---|---|---|---:|---:|---|---|---|---:|---|---|---|---|---|---|---|---|']
    for x in items:
        lines.append(
            f"|{x['code']}|{x['name']}|{x['date']}|{x['close']:.3f}|{pct(x['pct_change'])}|{x['action_signal']}|{x['technical_state']}|"
            f"{x['entry_state']}|{x['target_position_pct']:.0f}%|{x['position_source']}|{x['signal_change_text']}|{x['daily_text']}|{x['weekly_text']}|"
            f"{x['weekly_confirmation']}|{_md_weak(x)}|{_risk_text(x)}|{x['analysis']}|"
        )
    if errors:
        lines += ['', '## 数据异常', ''] + [f"- {e['code']} {e['name']}: {e['error']}" for e in errors]
    lines += [
        '',
        '> 建仓状态是给当前空仓的人看的：暂不建仓 / 观察 / 试仓 / 确认建仓 / 强势建仓。试仓参考20%～30%，确认建仓参考30%～50%，强势建仓仍建议结合目标仓位分批执行。',
        '> 默认仓位：空仓0%、卖出10%、减仓30%、持有50%、加仓70%、买入80%。目标仓位是建议配置比例，不是目标价格。',
        '> 波动风险基于 ATR14/价格衡量振幅大小：低波动更稳定，高波动表示振幅更大、需要更谨慎；它不代表涨跌方向，也不直接改变技术动作。参考防守线 = 收盘价 - 2×ATR14。',
        '> 历史正式信号只在收盘后写入 `data/etf/signals.csv`；盘中重要变化写入 `data/etf/events.csv`。',
        '> 仅用于研究，不构成投资建议。'
    ]
    md.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    important_html = ''.join(
        f"<div class='change-card {_row_class(x)}'><div class='change-title'>{_esc(x['code'])} {_esc(x['name'])}</div>"
        f"<div>{_change_badge(x.get('signal_change_level'), x.get('signal_change_text'))}</div>"
        f"<div class='sub'>操作建议：{_action_badge(x['action_signal'])} ｜ 趋势{_state_badge(x['technical_state'])} ｜ 建仓{_entry_badge(x['entry_state'])} ｜ 目标仓位 <b>{x['target_position_pct']:.0f}%</b></div></div>"
        for x in changes
    ) or "<div class='empty'>本次无重要变化。</div>"

    rows = []
    for x in items:
        weak = _weak_badge(x['weak_turn_state'])
        change = _change_badge(x.get('signal_change_level'), x.get('signal_change_text'))
        defense = '—' if x.get('defense_line') is None else f"{x['defense_line']:.3f}"
        rows.append(
            f"<tr class='{_row_class(x)}'>"
            f"<td>{_esc(x['code'])}</td><td>{_esc(x['name'])}</td><td>{_esc(x['date'])}</td><td>{x['close']:.3f}</td><td>{pct(x['pct_change'])}</td>"
            f"<td>{_action_badge(x['action_signal'])}</td><td>{_state_badge(x['technical_state'])}</td><td>{_entry_badge(x['entry_state'])}</td><td><b>{x['target_position_pct']:.0f}%</b></td><td>{_esc(x['position_source'])}</td>"
            f"<td>{change}</td><td>{_esc(x['daily_text'])}</td><td>{_esc(x['weekly_text'])}</td><td>{_esc(x['weekly_confirmation'])}</td><td>{weak}</td>"
            f"<td>{_risk_badge(x)}<div class='tiny'>参考防守线 {defense}</div></td><td>{_esc(x['analysis'])}</td></tr>"
        )
    css = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:28px;color:#222;background:#fff}
h1{margin-bottom:6px}.meta{color:#666;margin-bottom:14px}.note{background:#f6f8fa;padding:14px 16px;border-radius:10px;margin:14px 0;line-height:1.75}
.change-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin:12px 0 20px}.change-card{border:1px solid #e5e7eb;border-radius:10px;padding:12px;background:#fff}.change-title{font-weight:700;margin-bottom:7px}.sub{margin-top:8px;color:#555}.empty{color:#777;padding:10px 0}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}th{background:#f5f5f5;position:sticky;top:0;z-index:1}
.badge{display:inline-block;padding:2px 7px;border-radius:999px;font-weight:650;line-height:1.5;white-space:normal}.pos{color:#b42318;background:#fff0ee}.neg{color:#16794a;background:#edf8f1}.neu{color:#175cd3;background:#eef4ff}.warn{color:#a15c00;background:#fff4df}.danger{color:#b42318;background:#ffe4e2}.muted{color:#667085;background:#f2f4f7}.mix{color:#6941c6;background:#f4f0ff}
.row-up{background:#fffafa}.row-down{background:#f7fcf8}.row-risk{background:#fffaf2}.row-mix{background:#faf8ff}.row-change{background:#fbfbfb}.tiny{font-size:11px;color:#777;margin-top:3px}
@media(max-width:900px){body{margin:14px}table{font-size:12px}.change-grid{grid-template-columns:1fr}}
"""
    errs = '' if not errors else '<h2>数据异常</h2><ul>' + ''.join(f"<li>{_esc(e['code'])} {_esc(e['name'])}: {_esc(e['error'])}</li>" for e in errors) + '</ul>'
    html_text = f"""<!doctype html><meta charset='utf-8'><style>{css}</style>
<h1>ETF每日技术监控 V1.0</h1><div class='meta'>生成时间：{datetime.now():%Y-%m-%d %H:%M:%S} ｜ {freshness}</div>
<div class='note'><b>本版重点：</b>日线负责触发，周线负责确认/否决；“趋势状态”表示技术面强弱；“建仓状态”专门回答当前空仓是否适合首次建仓；“信号变化”突出今天相对上一交易日发生了什么；“波动风险”只表示振幅大小，不代表涨跌方向，也不直接改动作。<br>
<b>建仓状态：</b>暂不建仓＝不参与；观察＝继续等信号；试仓＝可考虑20%～30%第一笔；确认建仓＝可考虑30%～50%分批建立；强势建仓＝强信号，仍建议结合目标仓位分批执行。<br>
<b>默认仓位：</b>空仓0%、卖出10%、减仓30%、持有50%、加仓70%、买入80%。命中 <code>position_grid.csv</code> 时网格优先。</div>
<h2>今日重要变化</h2><div class='change-grid'>{important_html}</div>
<h2>全部监控</h2><div style='overflow:auto'><table><tr><th>代码</th><th>名称</th><th>日期</th><th>收盘价</th><th>涨跌幅</th><th>技术动作</th><th>趋势状态</th><th>建仓状态</th><th>目标仓位</th><th>来源</th><th>信号变化</th><th>日线状态</th><th>周线状态</th><th>周线确认</th><th>弱转强</th><th>波动风险</th><th>分析</th></tr>{''.join(rows)}</table></div>
{errs}<p>仅用于研究，不构成投资建议。</p>"""
    ht.write_text(html_text, encoding='utf-8')
    (out_dir / 'latest.md').write_text(md.read_text(encoding='utf-8'), encoding='utf-8')
    (out_dir / 'latest.html').write_text(ht.read_text(encoding='utf-8'), encoding='utf-8')
    return md, ht
