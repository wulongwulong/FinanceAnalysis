from datetime import date
import hashlib
import json
import unittest
from unittest.mock import patch

from finance_tools.common import demo
from finance_tools.etf.engine import analyze as analyze_etf
from finance_tools.sector.target_rule_engine import analyze as analyze_sector


RULES = {'default_positions': {'空仓': 0, '卖出': 10, '减仓': 30,
                               '持有': 50, '加仓': 70, '买入': 80}}


class SharedRuleTests(unittest.TestCase):
    @patch('finance_tools.common.demo.date')
    def test_complete_outputs_match_before_rule_extraction(self, dates):
        dates.today.return_value = date(2026, 9, 30)
        cases = []
        for seed in range(100):
            cases.append((f'etf:{seed}', demo.etf_rows(seed)))
            cases.append((f'sector:{seed}', demo.sector_rows(seed)))
        for ret in (-.15, -.05, -.02, -.01, 0, .01, .02, .05, .15):
            rows = demo.etf_rows(7)
            for i, row in enumerate(rows[-20:], 1):
                factor = (1 + ret) ** i
                for field in ('open', 'high', 'low', 'close'):
                    row[field] *= factor
            cases.append((f'trend:{ret}', rows))

        outputs = []
        for case, rows in cases:
            with self.subTest(case=case):
                etf, sector = analyze_etf(rows, RULES), analyze_sector(rows, RULES)
                self.assertEqual(etf.pop('strategy_name'), '日线触发、周线确认')
                self.assertEqual(sector.pop('strategy_name'), '日线打分、周线加权')
                outputs.append({'case': case, 'etf': etf, 'sector': sector})

        # Captured from both old engines before extraction: all fields, nested
        # indicators, ATR values, positions and the order of analysis reasons.
        payload = json.dumps(outputs, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         '6dde0a4e75abb1103c564bf361f8a1b8046e1fd2e915cab5a88ebf3a24b28725')

    @patch('finance_tools.common.demo.date')
    def test_weekly_strategies_keep_their_existing_disagreements(self, dates):
        dates.today.return_value = date(2026, 9, 30)
        cases = [
            # Weekly momentum can lift sector's daily score past its threshold.
            (demo.etf_rows(6), ('持有', 3, 0), ('加仓', 4, 0)),
            # ETF weekly confirmation vetoes one level of a daily buy signal.
            (demo.sector_rows(26), ('加仓', 7, 0), ('买入', 7, 1)),
            # ETF softens a reduction in a strong weekly trend; sector does not.
            (demo.etf_rows(29), ('持有', 1, 4), ('减仓', 2, 4)),
        ]
        for rows, etf_expected, sector_expected in cases:
            with self.subTest(etf=etf_expected, sector=sector_expected):
                etf, sector = analyze_etf(rows, RULES), analyze_sector(rows, RULES)
                fields = ('action_signal', 'buy_score', 'sell_score')
                self.assertEqual(tuple(etf[k] for k in fields), etf_expected)
                self.assertEqual(tuple(sector[k] for k in fields), sector_expected)
                for field in ('weak_turn_state', 'weak_turn_score', 'weak_turn_reasons'):
                    self.assertEqual(etf[field], sector[field])
                self.assertEqual({k: v for k, v in etf['daily'].items()
                                  if k not in ('atr14', 'atr_pct')}, sector['daily'])


if __name__ == '__main__':
    unittest.main()
