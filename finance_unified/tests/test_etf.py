import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from finance_tools.etf.engine import _apply_weekly_confirmation, _entry_state, compare_signal_change
from finance_tools.etf.history import _max_drawdown_close
from finance_tools.etf.runner import run


class CoreTests(unittest.TestCase):
    def test_weekly_confirmation_only_downgrades_conflict(self):
        self.assertEqual(_apply_weekly_confirmation('买入', '偏弱')[0], '加仓')
        self.assertEqual(_apply_weekly_confirmation('加仓', '偏弱')[0], '持有')
        self.assertEqual(_apply_weekly_confirmation('减仓', '偏强')[0], '持有')
        self.assertEqual(_apply_weekly_confirmation('买入', '偏强')[0], '买入')

    def test_true_drawdown_never_positive(self):
        future = [
            {'close': 100}, {'close': 110}, {'close': 105}, {'close': 120}, {'close': 90}
        ]
        dd = _max_drawdown_close(future, 100, 20)
        self.assertLessEqual(dd, 0)
        self.assertAlmostEqual(dd, -25.0, places=6)


    def test_entry_state_progression(self):
        self.assertEqual(_entry_state('持有', '偏弱', '未触发', '偏弱', '中'), '暂不建仓')
        self.assertEqual(_entry_state('持有', '中性', '未触发', '中性', '中'), '观察')
        self.assertEqual(_entry_state('持有', '偏强', '观察', '中性', '中'), '试仓')
        self.assertEqual(_entry_state('持有', '偏强', '确认', '偏强', '中'), '确认建仓')
        self.assertEqual(_entry_state('买入', '偏强', '确认', '偏强', '中'), '强势建仓')
        self.assertEqual(_entry_state('买入', '偏强', '确认', '偏强', '很高'), '观察')

    def test_signal_change_detects_action(self):
        base_daily = {'macd_cross': '', 'kdj_cross': '', 'ma_state': '站上20日线', 'kdj_zone': '中位'}
        prev = {'action_signal': '持有', 'entry_state': '观察', 'weak_turn_state': '未触发', 'daily': dict(base_daily), 'weekly_bias': '中性'}
        curr = {'action_signal': '加仓', 'entry_state': '确认建仓', 'weak_turn_state': '观察', 'daily': dict(base_daily), 'weekly_bias': '偏强'}
        out = compare_signal_change(curr, prev)
        self.assertTrue(out['is_significant_change'])
        self.assertIn('持有 → 加仓', out['signal_change_text'])
        self.assertIn('未触发 → 观察', out['signal_change_text'])
        self.assertIn('观察 → 确认建仓', out['signal_change_text'])

    def test_demo_report_and_alert_use_project_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config/etf').mkdir(parents=True)
            (root / 'config/rules.json').write_text(json.dumps({
                'default_positions': {'空仓': 0, '卖出': 10, '减仓': 30, '持有': 50, '加仓': 70, '买入': 80}
            }), encoding='utf-8')
            (root / 'config/etf/etfs.csv').write_text('code,name,enabled\n510300,测试ETF,1\n999999,停用ETF,0\n', encoding='utf-8')
            with patch('finance_tools.etf.runner.subprocess.run') as notify:
                report = run(root, demo=True)
                alert = run(root, demo=True, mode='alert')
            self.assertEqual(report, root / 'outputs/etf/latest.html')
            self.assertEqual(alert, root / 'outputs/etf/latest_alert.txt')
            self.assertIn('510300', report.read_text(encoding='utf-8'))
            self.assertNotIn('999999', report.read_text(encoding='utf-8'))
            self.assertTrue(alert.is_file())
            self.assertFalse((root / 'data').exists())
            notify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
