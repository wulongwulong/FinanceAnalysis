import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finance_tools import cli, unified
from finance_tools.common.demo import etf_rows


@unittest.skipUnless(importlib.util.find_spec('pandas') and importlib.util.find_spec('numpy'), '需要 pandas/numpy')
class UnifiedTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        shutil.copytree(cli.ROOT / 'config', self.root / 'config')

    def test_opportunities_and_monitoring_fetch_each_code_once_and_keep_all_associations(self):
        import pandas as pd
        with patch('socket.socket', side_effect=AssertionError('演示不得联网')), \
             patch.object(unified, 'etf_rows', wraps=etf_rows) as fetch, \
             patch('finance_tools.sector.runner.run', side_effect=AssertionError('不得重复行业扫描')):
            report = unified.run(self.root, demo=True)
        codes = [call.args[0] for call in fetch.call_args_list]
        self.assertEqual(len(codes), len(set(codes)))
        frame = pd.read_csv(report.parent / '最新_标的与监控.csv', dtype={'代码': str})
        self.assertEqual(len(frame), len(codes))
        self.assertFalse(frame['代码'].duplicated().any())
        shared = frame[frame['代码'].eq('513130')].iloc[0]
        self.assertIn('软件开发', shared['行业关联'])
        self.assertIn('半导体', shared['行业关联'])
        self.assertIn('159869', frame['代码'].tolist())
        self.assertTrue(frame.loc[frame['代码'].eq('159869'), '机会类型'].eq('日常监控').all())
        self.assertIn('Finance 分析', report.read_text())

    def test_important_changes_and_full_monitoring_are_visible_and_exported(self):
        item = {
            'code': '512800', 'name': '银行<ETF>', 'date': '2026-09-30',
            'close': .853, 'pct_change': .0143, 'action_signal': '持有',
            'technical_state': '偏强', 'entry_state': '试仓', 'target_position_pct': 50,
            'position_source': '默认规则', 'source': '测试源',
            'is_significant_change': True, 'signal_change_level': '转强',
            'signal_change_text': '建仓状态：观察 → 试仓；重新站上MA20',
            'daily_text': '日线测试', 'weekly_text': '周线测试',
            'weekly_confirmation': '周线中性', 'weak_turn_state': '观察',
            'weak_turn_reasons': '动能改善', 'volatility_risk': '低',
            'atr_pct': 1.41, 'defense_line': .829, 'analysis': '分析测试',
        }
        failed = {'code': '159995', 'name': '半导体ETF', 'status': '分析失败', 'error': '行情失败<原因>'}
        rendered = unified.securities_html([], [item, failed])
        self.assertIn('今日重要变化', rendered)
        self.assertIn('全部监控', rendered)
        self.assertIn("class='change-card row-up'", rendered)
        self.assertLess(rendered.index('全部监控'), rendered.index('<details>'))
        for value in ('日线测试', '周线测试', '周线中性', '分析测试', '0.829', '1.43%', '动能改善'):
            self.assertIn(value, rendered)
        self.assertIn('银行&lt;ETF&gt;', rendered)
        self.assertIn('行情失败&lt;原因&gt;', rendered)
        row = unified.securities_frame([], [item]).iloc[0]
        for column, value in [('收盘价', .853), ('涨跌幅%', 1.43), ('趋势状态', '偏强'),
                              ('日线状态', '日线测试'), ('周线状态', '周线测试'),
                              ('周线确认', '周线中性'), ('弱转强', '观察'),
                              ('弱转强依据', '动能改善'), ('分析', '分析测试')]:
            self.assertEqual(row[column], value)
        markdown = unified.securities_markdown([], [item, failed])
        self.assertIn('今日重要变化', markdown)
        self.assertIn('日线测试', markdown)
        self.assertIn('参考防守线：0.829', markdown)
        self.assertIn('本次无重要变化', unified.securities_html([], [{**item, 'is_significant_change': False}]))
        self.assertIn('行情失败&lt;原因&gt;', unified.securities_html([], [failed]))

    def test_failed_shared_quote_is_not_retried_or_replaced_with_positive_conditions(self):
        def fetch(code):
            if code == '159995':
                raise OSError('共享行情失败')
            return etf_rows(int(code)), '测试源'

        def scan(root, demo, monitor, target_fetcher):
            from finance_tools.fund.opportunities import build_targets
            industries = [{'名称': '半导体', '分类': 'C 趋势机会', '最新日期': '2026-10-02'},
                          {'名称': '半导体Ⅱ', '分类': 'A2 低位转强', '最新日期': '2026-10-02'}]
            targets = build_targets(root, industries, fetcher=target_fetcher)
            return unified.securities_frame(targets, monitor)

        with patch.object(unified, 'fetch_security', side_effect=fetch) as provider, \
             patch('finance_tools.fund.runner.run', side_effect=scan):
            frame = unified.run(self.root)
        self.assertEqual(sum(call.args[0] == '159995' for call in provider.call_args_list), 1)
        failed = frame[frame['代码'].eq('159995')].iloc[0]
        self.assertIn('取数失败', failed['数据状态'])
        self.assertIn('共享行情失败', failed['异常说明'])
        self.assertNotIn('技术条件偏强', failed['机会条件'])


if __name__ == '__main__':
    unittest.main()
