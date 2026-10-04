from datetime import date, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from finance_tools.common import demo
from finance_tools.etf.engine import analyze as analyze_etf
from finance_tools.etf import report as etf_report
from finance_tools.sector.sector_engine import analyze_sector
from finance_tools.sector.target_timing import analyze_target
from finance_tools.sector import report as sector_report


class ReportDateTests(unittest.TestCase):
    def setUp(self):
        config = Path(__file__).resolve().parents[1] / 'config'
        self.rules = json.loads((config / 'rules.json').read_text(encoding='utf-8'))
        self.settings = json.loads((config / 'sector/settings.json').read_text(encoding='utf-8'))

    def test_etf_demo_dates_are_independent_of_scan_day(self):
        with patch('finance_tools.common.demo.date') as dates:
            dates.today.return_value = date(2026, 9, 30)
            base = analyze_etf(demo.etf_rows(1), self.rules)
        base.update(code='510300', name='演示ETF', is_fresh=False,
                    is_significant_change=False, signal_change_text='无变化',
                    position_source='默认规则')
        items = [{**base, 'date': date(2026, 9, 25)}, {**base, 'date': '2026-09-30'}]
        with TemporaryDirectory() as directory, patch.object(etf_report, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 3, 15, 10)
            for rows, expected in ((items, '2026-09-25～2026-09-30'), (items[:1], '2026-09-25')):
                with self.subTest(expected=expected):
                    md, html = etf_report.build(rows, [], Path(directory))
                    self.assertIn(f'<meta name="market-data-date" content="{expected}">', html.read_text())
                    self.assertIn(f'行情日期：{expected}', md.read_text())
                    self.assertIn('生成时间：2026-10-03 15:10:00', md.read_text())

    def test_sector_demo_range_includes_all_industries_and_targets(self):
        with patch('finance_tools.common.demo.date') as dates:
            dates.today.return_value = date(2026, 9, 30)
            rows = demo.sector_rows(1)
            sector = analyze_sector(rows, demo.sector_rows(100), self.settings['sector_position_windows'])
            sector.update(name='演示板块', code='801001', level='二级行业')
            target = analyze_target(demo.etf_rows(1), sector, self.rules, self.settings, code='510300')
        target.update(name='演示ETF', sector_name=sector['name'], sector_stage=sector['stage'],
                      date=date(2026, 9, 25))
        sectors = [{**sector, 'name': f'行业{i}'} for i in range(20)]
        sectors.append({**sector, 'name': '榜单外C行业', 'stage': 'C',
                        'stage_name': 'C 普通/高位观察', 'date': '2026-10-01'})
        with TemporaryDirectory() as directory, patch.object(sector_report, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 3, 15, 10)
            cases = (
                (sectors, [target], '2026-09-25～2026-10-01'),
                ([sector], [], '2026-09-30'),
            )
            for industries, targets, expected in cases:
                with self.subTest(expected=expected):
                    md, html, pack = sector_report.build(industries, targets, [], [], Path(directory))
                    self.assertIn(f'<meta name="market-data-date" content="{expected}">', html.read_text())
                    self.assertIn(f'行情日期：{expected}', md.read_text())
                    self.assertIn(f'数据日期：{expected}', pack.read_text())
                    self.assertNotIn('数据日期：2026-10-03', pack.read_text())

    def test_no_market_rows_leave_metadata_empty(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            etf_md, etf_html = etf_report.build([], [], root / 'etf')
            sector_md, sector_html, sector_pack = sector_report.build([], [], [], [], root / 'sector')
            for html in (etf_html, sector_html):
                self.assertIn('<meta name="market-data-date" content="">', html.read_text())
            for markdown in (etf_md, sector_md):
                self.assertIn('行情日期：—', markdown.read_text())
            self.assertIn('数据日期：—', sector_pack.read_text())


if __name__ == '__main__':
    unittest.main()
