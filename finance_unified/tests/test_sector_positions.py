import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from finance_tools.sector import runner
from finance_tools.sector.target_timing import analyze_target


class SectorPositionTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            'close': 1.1, 'action_signal': '持有', 'default_position_pct': 50,
            'target_position_pct': 50, 'position_source': '默认规则', 'position_note': '',
        }
        self.sector = {'stage': 'A2', 'location': '理想区', 'timing_score': 15}
        self.settings = {
            'sector_stage_caps': {'A2': 70}, 'location_caps': {'理想区': 80},
            'max_integrated_target_pct': 80,
        }

    def grid(self, target):
        return [{'code': '159995', 'lower': 1, 'upper': 1.2,
                 'target_position_pct': target, 'note': '测试网格'}]

    def test_runner_applies_grid_before_caps(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config/sector'
            config.mkdir(parents=True)
            (root / 'config/rules.json').write_text('{}', encoding='utf-8')
            (config / 'settings.json').write_text(json.dumps({
                **self.settings, 'sector_position_windows': [15, 120], 'final_focus_count': 5,
            }), encoding='utf-8')
            (config / 'target_mapping.csv').write_text(
                'sector_keywords,code,name,type,enabled\n软件开发,159995,测试ETF,ETF,1\n', encoding='utf-8')
            (config / 'position_grid.csv').write_text(
                'code,lower,upper,target_position_pct,note\n159995,1,1.2,70,测试网格\n', encoding='utf-8')
            with patch('finance_tools.sector.runner.analyze_sector',
                       side_effect=lambda *args: {**self.sector, 'priority_score': 1}), \
                 patch('finance_tools.sector.runner.update_sector_history'), \
                 patch('finance_tools.sector.target_timing.analyze_base', return_value=self.base), \
                 patch('finance_tools.sector.runner.build',
                       return_value=(root / 'a', root / 'b', root / 'c')) as build, \
                 patch('finance_tools.sector.runner.analyze_target', wraps=analyze_target) as analyze, \
                 contextlib.redirect_stdout(io.StringIO()):
                runner.run(root, demo=True)
            target = build.call_args.args[1][0]
            self.assertEqual(target['target_position_pct'], 70)
            self.assertEqual(target['integrated_target_pct'], 70)
            self.assertEqual(analyze.call_args.kwargs['code'], '159995')
            self.assertEqual(analyze.call_args.kwargs['grid'], self.grid(70))

    def test_grid_overrides_default_before_caps(self):
        with patch('finance_tools.sector.target_timing.analyze_base', return_value=self.base):
            for target in (70, 30, 0):
                with self.subTest(target=target):
                    result = analyze_target([], self.sector, {}, self.settings,
                                            code='159995', grid=self.grid(target))
                    self.assertEqual(result['target_position_pct'], target)
                    self.assertEqual(result['integrated_target_pct'], target)
                    self.assertEqual(result['position_source'], '网格')
                    if target == 0:
                        self.assertEqual(result['grade'], 'C')
                        self.assertEqual(result['integrated_advice'], '暂不参与')

    def test_each_cap_applies_without_rounding_above_it(self):
        with patch('finance_tools.sector.target_timing.analyze_base', return_value=self.base):
            for cap_name in ('sector_stage_caps', 'location_caps', 'max_integrated_target_pct'):
                for cap in (25, 68):
                    with self.subTest(cap_name=cap_name, cap=cap):
                        settings = {'sector_stage_caps': {'A2': 90}, 'location_caps': {'理想区': 90},
                                    'max_integrated_target_pct': 90}
                        if cap_name == 'sector_stage_caps':
                            settings[cap_name] = {'A2': cap}
                        elif cap_name == 'location_caps':
                            settings[cap_name] = {'理想区': cap}
                        else:
                            settings[cap_name] = cap
                        result = analyze_target([], self.sector, {}, settings,
                                                code='159995', grid=self.grid(90))
                        self.assertEqual(result['integrated_target_pct'], cap)

    def test_zero_target_cancels_buy_advice_without_new_positive_grade_threshold(self):
        base = {**self.base, 'action_signal': '买入', 'default_position_pct': 80,
                'target_position_pct': 80}
        with patch('finance_tools.sector.target_timing.analyze_base', return_value=base):
            zero = analyze_target([], self.sector, {}, self.settings,
                                  code='159995', grid=self.grid(0))
            positive = analyze_target([], self.sector, {}, self.settings,
                                      code='159995', grid=self.grid(30))
        self.assertEqual((zero['grade'], zero['integrated_advice']), ('C', '暂不参与'))
        self.assertEqual(positive['grade'], 'S')
        self.assertEqual(positive['integrated_target_pct'], 30)

    def test_existing_call_without_grid_keeps_default_target(self):
        with patch('finance_tools.sector.target_timing.analyze_base', return_value=self.base):
            result = analyze_target([], self.sector, {}, self.settings)
        self.assertEqual(result['target_position_pct'], 50)
        self.assertEqual(result['integrated_target_pct'], 50)
        self.assertEqual(result['position_source'], '默认规则')
        self.assertEqual(result['grade'], 'A')
        self.assertNotIn('持有', result['integrated_advice'])


if __name__ == '__main__':
    unittest.main()
