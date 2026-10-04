import contextlib
import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finance_tools import cli


class ProjectTests(unittest.TestCase):
    def test_index_is_the_complete_report_not_a_module_link_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / 'outputs' / cli.REPORT
            report.parent.mkdir(parents=True)
            content = '<h1>Finance 分析</h1><section id="low-turn">低位转强</section><section id="securities">标的判断</section>'
            report.write_text(content, encoding='utf-8')
            self.assertEqual(cli.build_index(root).read_text(encoding='utf-8'), content)

    def test_failed_run_shows_current_error_and_does_not_publish_old_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / 'outputs' / cli.REPORT
            report.parent.mkdir(parents=True)
            report.write_text('old successful result', encoding='utf-8')
            with patch('finance_tools.unified.run', side_effect=RuntimeError('本次取数失败 <timeout>')), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.run_analysis(root), 1)
            page = (root / 'outputs/index.html').read_text(encoding='utf-8')
            self.assertIn('本次取数失败 &lt;timeout&gt;', page)
            self.assertNotIn('old successful result', page)
            self.assertEqual(report.read_text(), 'old successful result')

    def test_default_and_legacy_commands_use_one_pipeline(self):
        for argv in ([], ['all'], ['fund'], ['sector'], ['etf']):
            with self.subTest(argv=argv), patch.object(cli, 'run_analysis', return_value=0) as run:
                self.assertEqual(cli.main(argv), 0)
                run.assert_called_once_with(cli.ROOT, mode='report')

    @unittest.skipUnless(importlib.util.find_spec('pandas') and importlib.util.find_spec('numpy'), '演示需要 pandas/numpy')
    def test_independent_project_demo_publishes_one_report_and_preserves_formal_files(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '独立项目'
            root.mkdir()
            shutil.copytree(cli.ROOT / 'finance_tools', root / 'finance_tools', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(cli.ROOT / 'config', root / 'config')
            shutil.copy2(cli.ROOT / 'main.py', root / 'main.py')
            history = root / 'data/fund/history.csv'
            history.parent.mkdir(parents=True)
            history.write_text('formal history sentinel')
            holdings = root / 'data/portfolio/holdings.json'
            holdings.parent.mkdir(parents=True)
            holdings.write_text('{"updated_at":"2026-09-30T15:00:00","positions":[{"code":"601398","name":"正式持仓不得进入演示","quantity":100,"average_cost":5,"note":""}]}')
            original_holdings = holdings.read_text()
            report = root / 'outputs/index.html'
            report.parent.mkdir(parents=True)
            report.write_text('formal report sentinel')
            result = subprocess.run([sys.executable, str(root / 'main.py'), '--demo'], cwd=directory, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            demo = root / 'outputs/demo'
            page = (demo / 'index.html').read_text(encoding='utf-8')
            for expected in ('Finance 分析', 'id="low-turn"', 'id="trend"', 'id="securities"', 'id="global"', 'id="history"', '159869'):
                self.assertIn(expected, page)
            for old in ('V1.0', 'V2.0', '查看报告', 'href="etf/', 'href="sector/', 'href="fund/'):
                self.assertNotIn(old, page)
            self.assertFalse((demo / 'etf').exists())
            self.assertFalse((demo / 'sector').exists())
            self.assertFalse((demo / 'fund').exists())
            latest = demo / 'analysis/03_最新文件'
            self.assertEqual((latest / '最新报告.html').read_text(), page)
            securities = pd.read_csv(latest / '最新_标的与监控.csv', dtype={'代码': str})
            self.assertFalse(securities['代码'].duplicated().any())
            self.assertIn('159869', securities['代码'].tolist())
            self.assertTrue((root / 'data/demo/fund/history.csv').is_file())
            self.assertTrue(pd.read_csv(latest / '最新_实际持仓.csv').empty)
            self.assertNotIn('正式持仓不得进入演示', page)
            self.assertEqual(holdings.read_text(), original_holdings)
            self.assertEqual(history.read_text(), 'formal history sentinel')
            self.assertEqual(report.read_text(), 'formal report sentinel')


if __name__ == '__main__':
    unittest.main()
