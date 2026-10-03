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
    def test_module_failure_does_not_stop_other_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('finance_tools.etf.runner.run', side_effect=RuntimeError('test failure')), \
                 patch('finance_tools.sector.runner.run', return_value=root / 'outputs/sector/latest.html') as sector, \
                 patch('finance_tools.fund.runner.run', return_value=root / 'outputs/fund/03_最新文件/最新报告.html') as fund, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.run_tasks(root, list(cli.NAMES)), 1)
            sector.assert_called_once_with(root, demo=False, limit=0)
            fund.assert_called_once_with(root, demo=False)
            self.assertIn('test failure', (root / 'outputs/index.html').read_text())

    @unittest.skipUnless(importlib.util.find_spec('pandas') and importlib.util.find_spec('numpy'), '基金演示需要 pandas/numpy')
    def test_independent_project_all_demo_preserves_formal_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '独立项目'
            root.mkdir()
            shutil.copytree(cli.ROOT / 'finance_tools', root / 'finance_tools', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(cli.ROOT / 'config', root / 'config')
            shutil.copy2(cli.ROOT / 'main.py', root / 'main.py')
            history = root / 'data/sector/sector_signals.csv'
            history.parent.mkdir(parents=True)
            history.write_text('formal history sentinel')
            report = root / 'outputs/sector/latest.html'
            report.parent.mkdir(parents=True)
            report.write_text('formal report sentinel')
            result = subprocess.run([sys.executable, str(root / 'main.py'), 'all', '--demo'], cwd=directory, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('ERR ', result.stdout)
            self.assertNotIn('失败：', result.stdout)
            for relative in cli.REPORTS.values():
                self.assertGreater((root / 'outputs/demo' / relative).stat().st_size, 100)
            self.assertTrue((root / 'outputs/demo/index.html').is_file())
            self.assertTrue((root / 'data/demo/fund/history.csv').is_file())
            self.assertEqual(history.read_text(), 'formal history sentinel')
            self.assertEqual(report.read_text(), 'formal report sentinel')


if __name__ == '__main__':
    unittest.main()
