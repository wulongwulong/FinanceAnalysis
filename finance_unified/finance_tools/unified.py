"""一次行业扫描与一份证券行情，生成统一研究报告。"""
from __future__ import annotations

from pathlib import Path

from .common.data_source import fetch_security
from .common.demo import etf_rows
from .portfolio import load_holdings, holdings_html, holdings_markdown, holdings_records


def run(root: Path, demo=False):
    from .etf.runner import collect
    from .fund.runner import run as scan

    holdings = load_holdings(root)
    snapshots = {}

    def fetch(code):
        if code not in snapshots:
            try:
                snapshots[code] = (etf_rows(int(code)), '离线演示（模拟数据）') if demo else fetch_security(code)
            except Exception as error:
                snapshots[code] = error
        value = snapshots[code]
        if isinstance(value, Exception):
            raise value
        return value

    try:
        items, errors, _ = collect(root, demo=demo, fetcher=fetch,
                                   extra_securities=[{**x, 'asset_type': '证券'} for x in holdings['positions'] if x['quantity'] > 0])
    except Exception as error:
        items, errors = [], [{'code': '', 'name': '监控名单', 'error': str(error)}]
    monitor = items + [{**error, 'status': '分析失败'} for error in errors]
    for position in holdings['positions']:
        item = next((x for x in monitor if x['code'] == position['code']), None)
        if item is None:
            item = {'code': position['code'], 'name': position['name'],
                    'status': '数量为0，未分析' if position['quantity'] == 0 else '未取得有效分析'}
            monitor.append(item)
        item.update(holding=position, holdings_updated_at=holdings['updated_at'])
    return scan(root, demo=demo, monitor=monitor, target_fetcher=fetch)


def securities_frame(targets, monitor):
    import pandas as pd

    by_code = {}
    for target in targets or []:
        if target['code']:
            by_code.setdefault(target['code'], {'targets': [], 'monitor': {}})['targets'].append(target)
    for item in monitor or []:
        by_code.setdefault(item['code'], {'targets': [], 'monitor': {}})['monitor'] = item
    rows = []
    for code, records in by_code.items():
        linked, item = records['targets'], records['monitor']
        target = linked[0] if linked else {}
        opportunity_action = target.get('action_signal', '')
        monitor_action = item.get('action_signal', '')
        conditions = '；'.join(f"{t['industry_name']}：{t['participation_condition']}" for t in linked)
        disagreement = bool(opportunity_action and monitor_action and opportunity_action != monitor_action)
        rows.append({
            '代码': code, '名称': item.get('name') or target.get('name', ''),
            '类型': target.get('asset_type') or item.get('asset_type') or ('ETF' if item.get('action_signal') else ''),
            '行业关联': '、'.join(dict.fromkeys(t['industry_name'] for t in linked)) or '未入选新机会，继续监控',
            '机会类型': '、'.join(dict.fromkeys(t['opportunity_type'] for t in linked)) or '日常监控',
            '行情日期': item.get('date') or target.get('date', ''),
            '来源': item.get('source') or target.get('source', ''),
            '机会条件': conditions or '依据标的自身行情监控',
            '日周线加权动作': opportunity_action or '—',
            '周线确认动作': monitor_action or '—',
            '技术判断': (f'加权：{opportunity_action}；确认：{monitor_action}' + ('（有分歧）' if disagreement else '')
                         if opportunity_action and monitor_action else f'周线确认：{monitor_action}' if monitor_action
                         else f'日周线加权：{opportunity_action}' if opportunity_action else '暂无有效判断'),
            '判断差异': f'存在分歧：加权{opportunity_action}，确认{monitor_action}' if disagreement else '一致' if opportunity_action and monitor_action else '单一技术口径',
            '首次参与状态': item.get('entry_state', '—'),
            '收盘价': item.get('close'),
            '涨跌幅%': None if item.get('pct_change') is None else item['pct_change'] * 100,
            '趋势状态': item.get('technical_state', '—'),
            '日线状态': item.get('daily_text', '—'), '周线状态': item.get('weekly_text', '—'),
            '周线确认': item.get('weekly_confirmation', '—'),
            '弱转强': item.get('weak_turn_state', '—'),
            '弱转强依据': item.get('weak_turn_reasons', '—'),
            '分析': item.get('analysis', '—'),
            '波动风险': item.get('volatility_risk', '—'),
            'ATR%': item.get('atr_pct'), '参考防守线': item.get('defense_line'),
            '监控参考仓位%': item.get('target_position_pct'),
            '仓位来源': item.get('position_source', '—'),
            '每日变化': item.get('signal_change_text', '—'),
            '数据状态': '；'.join(dict.fromkeys([t['status'] for t in linked] + ([item.get('status', '日期已确认')] if item else []))),
            '异常说明': '；'.join(dict.fromkeys([t['error'] for t in linked if t['error']] + ([item['error']] if item.get('error') else []))),
        })
    return pd.DataFrame(rows, columns=[
        '代码', '名称', '类型', '行业关联', '机会类型', '行情日期', '来源', '机会条件',
        '日周线加权动作', '周线确认动作', '技术判断', '判断差异', '首次参与状态', '波动风险', 'ATR%',
        '参考防守线', '监控参考仓位%', '仓位来源', '每日变化', '数据状态', '异常说明',
        '收盘价', '涨跌幅%', '趋势状态', '日线状态', '周线状态', '周线确认', '弱转强', '弱转强依据', '分析',
    ])


def securities_html(targets, monitor):
    from .fund.analyzer import table_rows
    from .etf.report import monitoring_html

    frame = securities_frame(targets, monitor)
    cols = ['代码', '名称', '行业关联', '机会条件', '技术判断', '波动风险', '行情日期', '数据状态']
    detail_cols = list(frame.columns)
    return holdings_html(holdings_records(monitor)) + '<section id="securities"><h2>标的判断与日常监控</h2><div class="note">机会对应标的与监控名单合在这里。同一代码共用本次行情；日周线加权用于机会技术条件，周线确认用于日常监控，有分歧时同时展示。未入选新机会的标的仍然保留。实际持仓由你维护，参考仓位不能用于计算实际调仓量。</div>' + monitoring_html(monitor) + '<h3>机会关联与技术分歧</h3><table><thead><tr>' + ''.join(f'<th>{c}</th>' for c in cols) + '</tr></thead><tbody>' + table_rows(frame, cols) + '</tbody></table><details><summary>完整字段与取数明细</summary><table><thead><tr>' + ''.join(f'<th>{c}</th>' for c in detail_cols) + '</tr></thead><tbody>' + table_rows(frame, detail_cols) + '</tbody></table></details></section>'


def securities_markdown(targets, monitor):
    frame = securities_frame(targets, monitor)
    lines = [holdings_markdown(monitor), '', '## 标的判断与日常监控', '', '机会对应标的与监控名单共用行情，未入选新机会的标的继续跟踪。技术口径有分歧时分别展示；实际持仓由你维护。', '']
    changes = [x for x in monitor or [] if x.get('is_significant_change')]
    lines += ['### 今日重要变化', '']
    lines += [f"- {x['code']} {x['name']}：{x['signal_change_text']}" for x in changes] or ['- 本次无重要变化。']
    lines += ['', '### 全部标的与监控明细', '']
    for row in frame.fillna('—').to_dict('records'):
        position = '—' if row['监控参考仓位%'] == '—' else f"{row['监控参考仓位%']}%"
        lines += [
            f"### {row['代码']} {row['名称']}",
            f"- {row['机会类型']}；行业：{row['行业关联']}；{row['机会条件']}",
            f"- 行情：{row['行情日期']}；来源：{row['来源']}；{row['数据状态']}",
            f"- 日周线加权：{row['日周线加权动作']}；周线确认：{row['周线确认动作']}；{row['判断差异']}",
            f"- 首次参与：{row['首次参与状态']}；波动风险：{row['波动风险']}；监控参考仓位：{position}；{row['每日变化']}",
            f"- 收盘价：{row['收盘价']}；涨跌幅：{row['涨跌幅%']}%；趋势状态：{row['趋势状态']}",
            f"- 日线状态：{row['日线状态']}；周线状态：{row['周线状态']}；周线确认：{row['周线确认']}",
            f"- 弱转强：{row['弱转强']}；依据：{row['弱转强依据']}；ATR：{row['ATR%']}%；参考防守线：{row['参考防守线']}",
            f"- 分析：{row['分析']}",
        ]
        if row['异常说明']:
            lines.append(f"- 异常：{row['异常说明']}")
        lines.append('')
    return '\n'.join(lines)
