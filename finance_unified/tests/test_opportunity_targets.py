from datetime import date
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from finance_tools.common import demo
from finance_tools.fund import opportunities


RULES = {'default_positions': {'空仓': 0, '卖出': 10, '减仓': 30,
                               '持有': 50, '加仓': 70, '买入': 80}}


class OpportunityTargetTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        mapping = self.root / 'config/sector/target_mapping.csv'
        mapping.parent.mkdir(parents=True)
        mapping.write_text(
            'sector_keywords,code,name,type,enabled\n'
            '软件开发;半导体,513130,共同ETF,ETF,1\n'
            '软件开发,2,测试股票,STOCK,1\n'
            '煤炭,161725,测试LOF,LOF,1\n'
            '电力,999999,停用ETF,ETF,0\n', encoding='utf-8')
        (self.root / 'config/rules.json').write_text(json.dumps(RULES), encoding='utf-8')
        with patch('finance_tools.common.demo.date') as dates:
            dates.today.return_value = date(2026, 9, 30)
            self.rows = demo.etf_rows(6)

    def industry(self, name, classification='A1 低位刚转强', **extra):
        return {'名称': name, '分类': classification, '行业代码': '801001',
                '最新日期': '2026-09-30', '日期确认': True,
                '当前位置': '理想区', '最终建议': '优先研究', **extra}

    def test_both_opportunities_map_all_asset_types_and_analyze_each_security_once(self):
        industries = [self.industry('软件开发'), self.industry('半导体', 'A2 低位转强'),
                      self.industry('煤炭', 'C 趋势机会'), self.industry('油气', 'C 趋势机会'),
                      self.industry('电力'), self.industry('半导体', 'A3 已加速'),
                      self.industry('银行', 'B 低位等待')]
        before = [dict(row) for row in industries]
        with patch.object(opportunities, 'fetch_security', return_value=(self.rows, '测试行情源')) as fetch, \
             patch.object(opportunities, 'analyze', wraps=opportunities.analyze) as analyze:
            results = opportunities.build_targets(self.root, industries)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(analyze.call_count, 3)
        self.assertEqual({call.args[0] for call in fetch.call_args_list}, {'513130', '000002', '161725'})
        shared = [r for r in results if r['code'] == '513130']
        self.assertEqual({r['industry_name'] for r in shared}, {'软件开发', '半导体'})
        mapped = [r for r in results if r['code']]
        self.assertEqual({r['asset_type'] for r in mapped}, {'ETF', 'STOCK', 'LOF'})
        self.assertEqual({r['opportunity_type'] for r in mapped}, {'低位转强', '趋势延续'})
        self.assertEqual({r['status'] for r in mapped}, {'正常'})
        for row in mapped:
            self.assertEqual(row['date'], '2026-09-30')
            self.assertEqual(row['source'], '测试行情源')
            self.assertEqual(row['strategy_name'], '日线打分、周线加权')
            self.assertTrue(row['daily_text'])
            self.assertTrue(row['weekly_text'])
            self.assertIn('技术条件偏强', row['participation_condition'])
            self.assertNotIn('target_position_pct', row)
            self.assertNotIn('integrated_target_pct', row)
        unmatched = {r['industry_name'] for r in results if r['status'] == '未匹配'}
        self.assertEqual(unmatched, {'油气', '电力'})
        self.assertFalse(any(r['code'] == '999999' for r in results))
        self.assertEqual(industries, before)

    def test_fetch_failure_remains_visible_for_every_association_and_is_not_retried(self):
        industries = [self.industry('半导体'), self.industry('半导体Ⅱ', 'C 趋势机会')]
        with patch.object(opportunities, 'fetch_security', side_effect=RuntimeError('行情接口失败')) as fetch, \
             patch.object(opportunities, 'analyze') as analyze:
            results = opportunities.build_targets(self.root, industries)
        fetch.assert_called_once_with('513130')
        analyze.assert_not_called()
        self.assertEqual(len(results), 2)
        for row in results:
            self.assertEqual(row['status'], '取数失败')
            self.assertEqual(row['code'], '513130')
            self.assertIn('行情接口失败', row['error'])
            self.assertIn('等待更新', row['participation_condition'])

    def test_insufficient_history_retains_available_market_date_and_source(self):
        with patch.object(opportunities, 'fetch_security', return_value=(self.rows[-20:], '短样本源')):
            row = opportunities.build_targets(self.root, [self.industry('半导体')])[0]
        self.assertEqual(row['status'], '数据不足')
        self.assertEqual(row['source'], '短样本源')
        self.assertEqual(row['date'], '2026-09-30')
        self.assertEqual(row['action_signal'], '')
        self.assertIn('至少需要80个交易日', row['error'])

    def test_analysis_failure_keeps_the_target_and_available_market_metadata(self):
        with patch.object(opportunities, 'fetch_security', return_value=(self.rows, '测试源')), \
             patch.object(opportunities, 'analyze', side_effect=RuntimeError('技术分析异常')):
            row = opportunities.build_targets(self.root, [self.industry('半导体')])[0]
        self.assertEqual(row['status'], '分析失败')
        self.assertEqual(row['code'], '513130')
        self.assertEqual(row['date'], '2026-09-30')
        self.assertEqual(row['source'], '测试源')
        self.assertIn('技术分析异常', row['error'])

    def test_stale_or_unconfirmed_industry_dates_override_strong_technical_conditions(self):
        industries = [self.industry('半导体'),
                      self.industry('半导体Ⅱ', **{'最新日期': '2026-10-01'}),
                      self.industry('半导体', 'C 趋势机会', **{'日期确认': False}),
                      self.industry('半导体', **{'最新日期': ''})]
        with patch.object(opportunities, 'fetch_security', return_value=(self.rows, '测试源')) as fetch:
            results = opportunities.build_targets(self.root, industries)
        fetch.assert_called_once_with('513130')
        self.assertEqual(results[0]['status'], '正常')
        self.assertEqual(results[1]['status'], '待更新')
        self.assertIn('标的行情待更新', results[1]['participation_condition'])
        for row in results[2:]:
            self.assertEqual(row['status'], '待更新')
            self.assertEqual(row['participation_condition'], '行业行情日期未确认，等待更新')
        self.assertEqual({r['action_signal'] for r in results}, {'加仓'})

    def test_missing_dates_are_unconfirmed_and_equal_or_older_industry_dates_are_current(self):
        for value in (None, float('nan'), '', 'NaT', 'not a date'):
            with self.subTest(value=value), \
                 patch.object(opportunities, 'fetch_security', return_value=(self.rows, '测试源')):
                row = opportunities.build_targets(self.root, [self.industry('半导体', **{'最新日期': value})])[0]
            self.assertEqual(row['industry_date'], '')
            self.assertEqual(row['status'], '待更新')
            self.assertEqual(row['participation_condition'], '行业行情日期未确认，等待更新')
        for value in (date(2026, 9, 30), '2026-09-29'):
            with self.subTest(value=value), \
                 patch.object(opportunities, 'fetch_security', return_value=(self.rows, '测试源')):
                row = opportunities.build_targets(self.root, [self.industry('半导体', **{'最新日期': value})])[0]
            self.assertEqual(row['status'], '正常')
            self.assertIn('技术条件偏强', row['participation_condition'])

    @unittest.skipUnless(importlib.util.find_spec('pandas') and importlib.util.find_spec('numpy'),
                         'DataFrame 边界检查需要 pandas/numpy')
    def test_pandas_missing_dates_and_numpy_false_confirmation_are_not_confirmed(self):
        import numpy as np
        import pandas as pd

        cases = [({'最新日期': pd.NaT}, ''), ({'最新日期': pd.NA}, ''),
                 ({'日期确认': np.bool_(False)}, '2026-09-30')]
        for extra, expected_date in cases:
            with self.subTest(extra=extra), \
                 patch.object(opportunities, 'fetch_security', return_value=(self.rows, '测试源')):
                row = opportunities.build_targets(self.root, [self.industry('半导体', **extra)])[0]
            self.assertEqual(row['industry_date'], expected_date)
            self.assertEqual(row['status'], '待更新')
            self.assertEqual(row['participation_condition'], '行业行情日期未确认，等待更新')

    def test_conditions_describe_existing_technical_actions_without_positions(self):
        for action, expected in [('买入', '偏强'), ('加仓', '偏强'), ('持有', '继续观察'),
                                 ('卖出', '等待重新转强'), ('减仓', '等待重新转强'), ('空仓', '等待重新转强')]:
            with self.subTest(action=action):
                signal = {'date': '2026-09-30', 'action_signal': action, 'weak_turn_state': '观察',
                          'daily_text': '日线状态', 'weekly_text': '周线状态', 'analysis': '分析原因'}
                with patch.object(opportunities, 'fetch_security', return_value=(self.rows, '测试源')), \
                     patch.object(opportunities, 'analyze', return_value=signal):
                    row = opportunities.build_targets(self.root, [self.industry('半导体', 'C 趋势机会')])[0]
                self.assertEqual(row['status'], '正常')
                self.assertIn('技术条件', row['participation_condition'])
                self.assertIn(expected, row['participation_condition'])
                self.assertNotIn('target_position_pct', row)

    def test_demo_uses_configured_securities_and_never_accesses_network(self):
        with patch('socket.socket', side_effect=AssertionError('演示不得访问网络')), \
             patch.object(opportunities, 'fetch_security', side_effect=AssertionError('演示不得取在线行情')) as fetch:
            rows = opportunities.build_targets(self.root, [self.industry('半导体', 'C 趋势机会')], demo=True)
        fetch.assert_not_called()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['code'], '513130')
        self.assertEqual(rows[0]['source'], '离线演示（模拟数据）')

    def test_standalone_demo_without_configuration_does_not_invent_securities(self):
        with TemporaryDirectory() as directory, \
             patch('socket.socket', side_effect=AssertionError('演示不得访问网络')):
            rows = opportunities.build_targets(Path(directory), [self.industry('半导体'),
                                                                  self.industry('煤炭', 'C 趋势机会')], demo=True)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['status'], '未配置')
            self.assertEqual(row['code'], '')
            self.assertIn('未配置标的映射', row['participation_condition'])


if __name__ == '__main__':
    unittest.main()
