from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..common.data_source import fetch_security
from ..common.demo import etf_rows
from ..common.indicators import normalize_ohlcv
from ..sector.runner import load_mapping, map_targets
from ..sector.target_rule_engine import STRATEGY_NAME, analyze


def _date_text(value) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return ''


def build_targets(root: Path, industries: list[dict], demo: bool = False, fetcher=None) -> list[dict]:
    """将完整行业 records 中的 A1/A2/C 映射为研究标的，不计算仓位。"""
    root = Path(root)
    mapping_error = rules_error = ''
    try:
        mapping = load_mapping(root)
    except FileNotFoundError:
        mapping = []
        mapping_error = '未配置标的映射：config/sector/target_mapping.csv'
    except Exception as exc:
        mapping = []
        mapping_error = f'标的映射配置异常：{exc}'
    try:
        rules = json.loads((root / 'config/rules.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        rules = {}
        rules_error = '未配置技术规则：config/rules.json'
    except Exception as exc:
        rules = {}
        rules_error = f'技术规则配置异常：{exc}'

    outputs, cache = [], {}
    for industry in industries:
        classification = str(industry.get('分类', ''))
        if classification.startswith(('A1', 'A2')):
            opportunity_type = '低位转强'
        elif classification.startswith('C'):
            opportunity_type = '趋势延续'
        else:
            continue
        base = {
            'industry_name': industry['名称'],
            'industry_code': str(industry.get('行业代码', '')),
            'industry_classification': classification,
            'industry_date': _date_text(industry.get('最新日期')),
            'industry_position': industry.get('当前位置', ''),
            'industry_advice': industry.get('最终建议', ''),
            'opportunity_type': opportunity_type,
            'code': '', 'name': '', 'asset_type': '', 'date': '', 'source': '',
            'strategy_name': STRATEGY_NAME, 'action_signal': '', 'weak_turn_state': '',
            'daily_text': '', 'weekly_text': '', 'analysis': '', 'error': '',
        }
        if mapping_error:
            outputs.append({**base, 'status': '未配置' if '未配置' in mapping_error else '配置异常',
                            'participation_condition': mapping_error, 'error': mapping_error})
            continue
        matched = {m['code']: m for m in map_targets(industry['名称'], mapping)}
        if not matched:
            outputs.append({**base, 'status': '未匹配',
                            'participation_condition': '配置标的池中暂无对应标的'})
            continue
        for code, target in matched.items():
            if code not in cache:
                result = {'date': '', 'source': '', 'action_signal': '', 'weak_turn_state': '',
                          'daily_text': '', 'weekly_text': '', 'analysis': '', 'error': ''}
                if rules_error:
                    result.update(status='未配置' if '未配置' in rules_error else '配置异常',
                                  participation_condition=rules_error, error=rules_error)
                else:
                    try:
                        rows, source = fetcher(code) if fetcher is not None else (etf_rows(int(code)), '离线演示（模拟数据）') if demo else fetch_security(code)
                        result['source'] = source
                    except Exception as exc:
                        status = '数据不足' if '不足' in str(exc) else '取数失败'
                        result.update(status=status, participation_condition=f'{status}，等待更新', error=str(exc))
                    else:
                        try:
                            rows = normalize_ohlcv(rows)
                            if rows:
                                result['date'] = rows[-1]['date'].isoformat()
                            signal = analyze(rows, rules)
                            for field in ('date', 'action_signal', 'weak_turn_state', 'daily_text', 'weekly_text', 'analysis'):
                                result[field] = signal[field]
                            action = signal['action_signal']
                            condition = ('技术条件偏强，待结合行业位置确认' if action in ('买入', '加仓')
                                         else '技术条件：继续观察' if action == '持有'
                                         else '技术条件：等待重新转强')
                            result.update(status='正常', participation_condition=condition)
                        except Exception as exc:
                            status = '数据不足' if '不足' in str(exc) or '至少需要' in str(exc) else '分析失败'
                            result.update(status=status, participation_condition=f'{status}，等待更新', error=str(exc))
                cache[code] = result
            row = {**base, **cache[code], 'code': code, 'name': target['name'],
                   'asset_type': target['type']}
            if row['status'] == '正常':
                confirmed = str(industry.get('日期确认', True)).lower() in ('true', '1')
                if not base['industry_date'] or not confirmed:
                    row.update(status='待更新', participation_condition='行业行情日期未确认，等待更新')
                elif row['date'] < base['industry_date']:
                    row.update(status='待更新', participation_condition='标的行情待更新，技术条件仅供历史观察')
            outputs.append(row)
    return outputs
