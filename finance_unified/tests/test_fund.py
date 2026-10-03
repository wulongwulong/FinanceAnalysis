import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finance_tools.fund.runner import run


@unittest.skipUnless(
    importlib.util.find_spec("numpy") and importlib.util.find_spec("pandas"),
    "基金分析需要 numpy 和 pandas",
)
class FundDemoTest(unittest.TestCase):
    def test_demo_runs_offline_and_writes_complete_report_package(self):
        import pandas as pd

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch("socket.socket", side_effect=AssertionError("演示不得访问网络")):
                report = run(root, demo=True)
            latest = root / "outputs/fund/03_最新文件"
            self.assertEqual(report, latest / "最新报告.html")
            self.assertTrue(report.is_file())
            industries = pd.read_csv(latest / "最新_量化结果.csv")
            self.assertEqual(len(industries), 12)
            self.assertTrue({"分类", "最终建议", "理想观察区", "扫描时段"}.issubset(industries.columns))
            assets = pd.read_csv(latest / "最新_全球资产.csv")
            self.assertEqual(len(assets), 12)
            self.assertTrue(assets["数据源"].eq("离线演示（模拟数据）").all())
            for path in (
                "data/fund/history.csv",
                "data/fund/a1_signals.csv",
                "outputs/fund/02_滚动汇总/最近7日_决策汇总.md",
                "outputs/fund/02_滚动汇总/最近20日_决策汇总.md",
                "outputs/chatgpt/fund/03_最新数据/最新报告.html",
                "outputs/chatgpt/fund/04_历史验证/history.csv",
            ):
                self.assertTrue((root / path).is_file(), path)
            before = pd.read_csv(root / "data/fund/history.csv")
            with patch("socket.socket", side_effect=AssertionError("演示不得访问网络")):
                run(root, demo=True)
            after = pd.read_csv(root / "data/fund/history.csv")
            self.assertEqual(len(before), len(after))


if __name__ == "__main__":
    unittest.main()
