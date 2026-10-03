from __future__ import annotations
from pathlib import Path
from datetime import datetime
import html


def _sector_location(sectors, sector_name: str) -> str:
    return next((s['location'] for s in sectors if s['name'] == sector_name), '—')


def _display_source(source: str) -> str:
    return '价格网格' if source == '网格' else source


def _trigger_state(e: dict, location: str) -> str:
    """仅用于展示，不改变原有标的动作、仓位、阶段和位置计算规则。"""
    stage = e.get('sector_stage', '')
    action = e.get('action_signal', '')
    target = float(e.get('integrated_target_pct', 0) or 0)

    # 明确不参与条件优先。
    if stage == 'C' or target <= 0 or action in ('空仓', '卖出'):
        return '不参与'

    # A3 已经加速，继续沿用“等回踩、不追高”的思路。
    if stage == 'A3':
        return '回踩观察'

    # B 类仍属于低位等待。
    if stage == 'B':
        return '等待确认'

    if stage in ('A1', 'A2'):
        # 真正重点：板块已转强、位置不高、标的自身至少为持有，且综合仓位达到50%。
        if location in ('理想区', '合理区') and action in ('持有', '加仓', '买入') and target >= 50:
            return '重点触发'
        # 板块已转强，但位置已经偏高：有信号，不追高。
        if location == '偏高' and target > 0:
            return '触发但位置不佳'

    return '等待确认'


def _grade_html(grade: str) -> str:
    cls = 'pos' if grade in ('S', 'A') else 'neutral' if grade == 'B' else 'neg'
    return f"<span class='{cls}'><b>{html.escape(grade)}</b></span>"


def _action_html(action: str) -> str:
    if action in ('买入', '加仓'):
        cls = 'pos'
    elif action in ('减仓', '卖出', '空仓'):
        cls = 'neg'
    else:
        cls = 'neutral'
    return f"<span class='{cls}'><b>{html.escape(action)}</b></span>"


def _target_html(value: float) -> str:
    value = float(value)
    cls = 'pos' if value >= 50 else 'neg' if value <= 10 else 'neutral'
    return f"<span class='{cls}'><b>{value:.0f}%</b></span>"


def _trigger_html(state: str) -> str:
    cls = {
        '重点触发': 'trigger-key',
        '触发但位置不佳': 'trigger-warn',
        '回踩观察': 'trigger-neutral',
        '等待确认': 'trigger-neutral',
        '不参与': 'trigger-out',
    }.get(state, 'trigger-neutral')
    return f"<span class='badge {cls}'>{html.escape(state)}</span>"


def _row_class(state: str) -> str:
    return {
        '重点触发': 'row-key',
        '触发但位置不佳': 'row-warn',
        '回踩观察': 'row-neutral',
        '等待确认': 'row-neutral',
        '不参与': 'row-out',
    }.get(state, '')


def build(sectors, targets, globals_, errors, out_dir: Path, focus_count=5):
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    md = out_dir / f'板块与标的分析_V2.0_{stamp}.md'
    ht = out_dir / f'板块与标的分析_V2.0_{stamp}.html'
    data = out_dir / f'ChatGPT投资决策数据包_V2.0_{stamp}.md'

    lines = [
        '# 板块与标的分析 V2.0', '',
        f'生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}', '',
        '## 一、核心逻辑', '',
        '- 上层：板块阶段 / 位置 / 相对沪深300决定“方向和仓位上限”。',
        '- 下层：ETF / 股票 / LOF 共用同一套技术动作规则：空仓0%、卖出10%、减仓30%、持有50%、加仓70%、买入80%。',
        '- `position_grid.csv` 命中时，价格网格目标仓位优先；随后仍受板块阶段和位置上限约束。', '',
        '## 二、优先板块', '',
        '|板块|级别|阶段|机会|技术确认|风险|15天位置|6月位置|相对300(15日)|当前位置|板块建议|',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---|---|',
    ]
    for x in sectors[:15]:
        lines.append(
            f"|{x['name']}|{x['level']}|{x['stage_name']}|{x['opportunity_score']:.1f}|{x['timing_score']}/20|"
            f"{x['risk_score']:.1f}|{x['positions'].get('15天','—')}%|{x['positions'].get('6月','—')}%|"
            f"{x['rel_hs300_15']:.2f}%|{x['location']}|{x['recommendation']}|"
        )

    lines += [
        '', '## 三、重点板块对应标的执行', '',
        '### 标的执行字段说明', '',
        '- **标的技术动作**：只看该 ETF / 股票 / LOF 自身日线、周线、MACD、KDJ、均线、量能等得到的动作；默认对应空仓0%、卖出10%、减仓30%、持有50%、加仓70%、买入80%。',
        '- **标的目标仓位**：标的技术动作对应的仓位；若命中 `config/position_grid.csv`，则优先使用网格仓位。',
        '- **来源**：表示“标的目标仓位”如何确定。默认按标的技术动作映射仓位：空仓0%、卖出10%、减仓30%、持有50%、加仓70%、买入80%；如果当前价格命中 `config/position_grid.csv`，则采用对应网格仓位并显示为“价格网格”。价格网格优先于默认规则。来源只解释标的目标仓位的产生方式，不代表最终综合目标仓位。',
        '- **阶段上限**：板块阶段允许的最高仓位；当前规则 A1=50%、A2=70%、A3=35%、B=20%、C=0%。',
        '- **位置上限**：板块当前位置允许的最高仓位；当前规则 理想区=80%、合理区=70%、中性区=50%、偏高=30%。',
        '- **综合目标**：标的目标仓位确定后，再结合阶段上限、位置上限及系统总上限取最小值，得到最终参考仓位。',
        '- **触发状态**：重点触发=A1/A2 + 理想区/合理区 + 标的技术动作至少为持有 + 综合目标≥50%；触发但位置不佳=A1/A2但位置偏高且综合目标>0；回踩观察=A3且综合目标>0；等待确认=B或尚未满足重点触发条件；不参与=C、综合目标=0或标的技术动作为空仓/卖出。',
        '- **综合建议**：结合标的动作、板块阶段和位置给出的文字结论。', '',
        '> 标的执行会在**全部已扫描板块**中，为 `config/target_mapping.csv` 里启用的 ETF / 股票 / LOF 寻找优先级最高的匹配板块。', '',
        '|板块|板块阶段|当前位置|类型|标的|评级|标的技术动作|标的目标仓位|来源|阶段上限|位置上限|综合目标|触发状态|综合建议|',
        '|---|---|---|---|---|---|---|---:|---|---:|---:|---:|---|---|',
    ]
    for e in targets:
        location = _sector_location(sectors, e['sector_name'])
        trigger = _trigger_state(e, location)
        lines.append(
            f"|{e['sector_name']}|{e['sector_stage']}|{location}|{e.get('asset_type','ETF')}|{e['name']} {e['code']}|{e['grade']}|{e['action_signal']}|"
            f"{e['target_position_pct']:.0f}%|{_display_source(e['position_source'])}|{e['sector_cap_pct']:.0f}%|"
            f"{e['location_cap_pct']:.0f}%|{e['integrated_target_pct']:.0f}%|{trigger}|{e['integrated_advice']}|"
        )

    lines += ['', '## 四、全球资产环境', '']
    if globals_:
        lines += ['|资产|趋势|15日涨跌|15天位置|120天位置|来源|', '|---|---|---:|---:|---:|---|']
        lines += [
            f"|{g['name']}|{g['trend']}|{g['ret15']:.2f}%|{g['pos15'] if g['pos15'] is not None else '—'}%|"
            f"{g['pos120'] if g['pos120'] is not None else '—'}%|{g['source']}|"
            for g in globals_
        ]
    else:
        lines.append('- 全球资产数据本次未成功获取，不影响行业技术扫描。')

    lines += [
        '', '## 五、怎么读', '',
        '1. “标的目标仓位”是 ETF / 股票 / LOF 自身技术规则的结果。',
        '2. “来源”只解释标的目标仓位来自默认规则还是价格网格，不等于最终仓位。',
        '3. “综合目标”才是把标的目标仓位、板块阶段和位置约束叠加后的结果。',
        '4. “触发状态”用于快速区分今天真正值得重点看的标的、位置不佳的已触发标的、等待确认和不参与标的。',
        '5. A3 已加速默认不追；B 类默认继续等，不会因为单个标的短线金叉就直接给高综合仓位。',
        '6. 价格网格仓位优先读取 `config/position_grid.csv`，ETF / 股票 / LOF 均可使用。', '',
        '> 仅用于研究筛选与纪律化决策，不构成投资建议。',
    ]
    md.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    pack = [
        '# ChatGPT 投资决策数据包 V2.0', '',
        f'数据日期：{datetime.now():%Y-%m-%d}', '',
        '## 一、规则说明', '',
        'ETF / 股票 / LOF 技术动作统一对应：空仓0%、卖出10%、减仓30%、持有50%、加仓70%、买入80%；position_grid.csv 命中时网格目标优先。板块阶段/位置作为上层仓位上限，最终看“综合目标仓位”。', '',
        '## 二、TOP候选', '',
    ]
    for x in sectors[:15]:
        pack += [
            f"### {x['name']}（{x['level']}）",
            f"- 阶段：{x['stage_name']}；信号年龄 {x['signal_age']}日",
            f"- 机会 {x['opportunity_score']:.1f}；技术确认 {x['timing_score']}/20；风险 {x['risk_score']:.1f}；优先分 {x['priority_score']:.2f}",
            '- 七周期位置：' + '；'.join(f'{k} {v}%' for k, v in x['positions'].items()),
            f"- 相对沪深300：15日 {x['rel_hs300_15']:.2f}%；1月 {x['rel_hs300_20']:.2f}%",
            f"- MACD：{x['macd_state']}；KDJ：{x['kdj_state']}；BOLL：{x['boll_state']}；RSI {x['rsi14']}；量能5/20 {x['volume_ratio']}",
            f"- 当前位置：{x['location']}；理想观察区：{x['ideal_low']} ~ {x['ideal_high']}；失效区：< {x['invalid_below']}",
            f"- 规则建议：{x['recommendation']}", '',
        ]

    pack += ['', '## 三、标的执行层', '']
    for e in targets:
        location = _sector_location(sectors, e['sector_name'])
        trigger = _trigger_state(e, location)
        pack += [
            f"- {e['sector_name']} → [{e.get('asset_type','ETF')}] {e['name']}({e['code']})｜标的动作 {e['action_signal']}｜标的目标 {e['target_position_pct']:.0f}%（{_display_source(e['position_source'])}）｜"
            f"板块上限 {e['sector_cap_pct']:.0f}%｜位置上限 {e['location_cap_pct']:.0f}%｜综合目标 {e['integrated_target_pct']:.0f}%｜触发状态 {trigger}｜{e['integrated_advice']}"
        ]
    pack += [
        '', '## 四、给 ChatGPT 的分析任务', '',
        '1. 比较最近多个扫描日的 B→A1、A1→A2、A2→A3 与 A3 回踩。',
        '2. 优先找 A1/A2 且位置合理、相对沪深300增强、技术共振的方向。',
        '3. 标的技术动作与板块上层判断冲突时，以板块阶段/位置作为仓位上限，不机械追高。',
        '4. 联网核实产业催化、风险；ETF/LOF重点核实规模、流动性、费率和跟踪指数，股票重点核实公司与行业风险。',
        '5. 最终只保留3~5个方向，并明确开始观察 / 小仓试探 / 等回踩 / 暂不参与。',
        '6. 样本不足必须写“证据不足”，不得承诺收益。',
    ]
    data.write_text('\n'.join(pack) + '\n', encoding='utf-8')

    tr = ''.join(
        f"<tr><td>{html.escape(x['name'])}</td><td>{x['stage']}</td><td>{x['opportunity_score']:.1f}</td>"
        f"<td>{x['timing_score']}/20</td><td>{x['risk_score']:.1f}</td><td>{x['location']}</td><td>{x['recommendation']}</td></tr>"
        for x in sectors[:20]
    )

    et_rows = []
    for e in targets:
        location = _sector_location(sectors, e['sector_name'])
        trigger = _trigger_state(e, location)
        source = _display_source(e['position_source'])
        advice_cls = 'pos' if trigger == '重点触发' else 'warn' if trigger == '触发但位置不佳' else 'neg' if trigger == '不参与' else 'neutral'
        et_rows.append(
            f"<tr class='{_row_class(trigger)}'>"
            f"<td>{html.escape(e['sector_name'])}</td>"
            f"<td>{html.escape(e['sector_stage'])}</td>"
            f"<td>{html.escape(location)}</td>"
            f"<td>{html.escape(e.get('asset_type','ETF'))}</td>"
            f"<td>{html.escape(e['name'])}</td>"
            f"<td>{_grade_html(e['grade'])}</td>"
            f"<td>{_action_html(e['action_signal'])}</td>"
            f"<td>{e['target_position_pct']:.0f}%</td>"
            f"<td class='source'>{html.escape(source)}</td>"
            f"<td>{e['sector_cap_pct']:.0f}%</td>"
            f"<td>{e['location_cap_pct']:.0f}%</td>"
            f"<td>{_target_html(e['integrated_target_pct'])}</td>"
            f"<td>{_trigger_html(trigger)}</td>"
            f"<td><span class='{advice_cls}'>{html.escape(e['integrated_advice'])}</span></td>"
            f"</tr>"
        )
    et = ''.join(et_rows)

    css = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:28px;color:#222}
table{border-collapse:collapse;width:100%;margin:15px 0}
th,td{padding:9px;border-bottom:1px solid #ddd;text-align:left;font-size:14px}
th{background:#f5f5f5}
.note{padding:14px 16px;background:#f6f8fa;border-radius:8px;line-height:1.7}
.note b{font-weight:650}.note .item{display:inline-block;margin-right:18px;margin-bottom:3px}
.pos{color:#d32f2f}.neg{color:#2e7d32}.neutral{color:#1565c0}.warn{color:#ef6c00}.source{color:#666}
.badge{display:inline-block;padding:3px 8px;border-radius:999px;font-weight:700;white-space:nowrap}
.trigger-key{color:#b71c1c;background:#ffebee}
.trigger-warn{color:#e65100;background:#fff3e0}
.trigger-neutral{color:#0d47a1;background:#eaf2ff}
.trigger-out{color:#1b5e20;background:#e8f5e9}
.row-key{background:#fffafa}.row-warn{background:#fffdf7}.row-neutral{background:#fbfdff}.row-out{background:#fbfdfb}
""".strip()

    etf_note = """
<div class='note'><b>标的执行字段说明：</b><br>
<span class='item'><b>标的技术动作</b>：只看该 ETF / 股票 / LOF 自身技术面得到的动作；默认对应空仓0%、卖出10%、减仓30%、持有50%、加仓70%、买入80%。</span><br>
<span class='item'><b>标的目标仓位</b>：标的技术动作对应的仓位；若命中 <code>config/position_grid.csv</code>，则优先使用网格仓位。</span><br>
<span class='item'><b>来源</b>：表示“标的目标仓位”如何确定。默认按标的技术动作映射仓位；如果当前价格命中 <code>config/position_grid.csv</code>，则采用对应网格仓位并显示为“价格网格”。<b>价格网格优先于默认规则</b>。来源只解释标的目标仓位的产生方式，不代表最终综合目标仓位。</span><br>
<span class='item'><b>阶段上限</b>：板块阶段允许的最高仓位；A1=50%、A2=70%、A3=35%、B=20%、C=0%。</span><br>
<span class='item'><b>位置上限</b>：板块位置允许的最高仓位；理想区=80%、合理区=70%、中性区=50%、偏高=30%。</span><br>
<span class='item'><b>综合目标</b>：标的目标仓位确定后，再结合阶段上限、位置上限及系统总上限取最小值，得到最终参考仓位。</span><br>
<span class='item'><b>触发状态</b>：<b>重点触发</b>=A1/A2 + 理想区/合理区 + 标的技术动作至少为持有 + 综合目标≥50%；<b>触发但位置不佳</b>=A1/A2但位置偏高且综合目标&gt;0；<b>回踩观察</b>=A3且综合目标&gt;0；<b>等待确认</b>=B或尚未满足重点触发条件；<b>不参与</b>=C、综合目标=0或标的技术动作为空仓/卖出。</span><br>
<span class='item'><b>综合建议</b>：结合标的动作、板块阶段和位置给出的文字结论。</span><br>
<span class='item'>标的执行会在全部已扫描板块中，为 <code>config/target_mapping.csv</code> 中启用的 ETF / 股票 / LOF 寻找优先级最高的匹配板块。</span>
</div>
""".strip()

    ht.write_text(
        f"<!doctype html><meta charset='utf-8'><style>{css}</style>"
        f"<h1>板块与标的分析 V2.0</h1>"
        "<div class='note'><b>参数说明：</b><br>"
        "<span class='item'><b>阶段</b>：A1=低位刚转强，A2=转强确认，A3=启动后已加速，B=低位等待。</span><br>"
        "<span class='item'><b>机会</b>：板块综合机会评分，越高代表越值得关注，不等于上涨概率。</span><br>"
        "<span class='item'><b>技术确认</b>：满分20分，综合 MA20、MACD、KDJ、BOLL、量能及相对沪深300表现；越高代表当前技术条件越充分。</span><br>"
        "<span class='item'><b>风险</b>：综合位置、过热与趋势衰减等风险，分数越高越需谨慎。</span><br>"
        "<span class='item'><b>位置</b>：当前价格在多周期区间中的位置，主要分为理想区、合理区、中性区、偏高。</span><br>"
        "<span class='item'><b>建议</b>：综合阶段、机会、技术确认、风险和位置后给出的当前操作建议。</span></div>"
        f"<h2>行业扫描</h2><table><tr><th>板块</th><th>阶段</th><th>机会</th><th>技术确认</th><th>风险</th><th>位置</th><th>建议</th></tr>{tr}</table>"
        f"<h2>标的执行</h2>{etf_note}"
        f"<table><tr><th>板块</th><th>板块阶段</th><th>当前位置</th><th>类型</th><th>标的</th><th>评级</th><th>标的技术动作</th><th>标的目标仓位</th><th>来源</th><th>阶段上限</th><th>位置上限</th><th>综合目标</th><th>触发状态</th><th>综合建议</th></tr>{et}</table>"
        "<p>仅用于研究，不构成投资建议。</p>",
        encoding='utf-8'
    )

    for src, name in [(md, 'latest.md'), (ht, 'latest.html'), (data, 'latest_chatgpt_pack.md')]:
        (out_dir / name).write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
    return md, ht, data
