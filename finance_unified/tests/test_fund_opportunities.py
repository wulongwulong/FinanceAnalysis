import importlib.util
import unittest
from unittest.mock import patch


@unittest.skipUnless(
    importlib.util.find_spec("numpy") and importlib.util.find_spec("pandas"),
    "基金分析需要 numpy 和 pandas",
)
class FundOpportunityReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pandas as pd
        from finance_tools.common.demo import sector_rows
        from finance_tools.fund import analyzer

        cls.pd = pd
        cls.analyzer = analyzer
        cls.row = analyzer.analyze("样例行业", pd.DataFrame(sector_rows(1, 280, 1000)), level="一级行业")

    def industries(self, rows):
        return self.pd.DataFrame([{**self.row, **row} for row in rows])

    def render(self, ind, targets=None):
        empty = self.pd.DataFrame()
        with patch.multiple(
            self.analyzer, create=True, TODAY="2026-10-03", NOW="2026-10-03 15:10:00",
            SCAN_SLOT="收盘", SCAN_TIME="15:10:00",
        ):
            html = self.analyzer.make_html(ind, empty, [], [], empty, empty, targets)
            markdown = self.analyzer.make_md(ind, empty, empty, empty, targets)
            pack = self.analyzer.decision_pack_markdown(ind, empty, empty, empty, empty, targets)
        return html, markdown, pack

    def opportunity_sections(self, reports):
        html, markdown, pack = reports
        return (
            (
                html.split('<section id="low-turn">', 1)[1].split("</section>", 1)[0],
                html.split('<section id="trend">', 1)[1].split("</section>", 1)[0],
            ),
            (
                markdown.split("## 低位转强（A1/A2）", 1)[1].split("## 趋势延续（C）", 1)[0],
                markdown.split("## 趋势延续（C）", 1)[1].split("## 后续观察", 1)[0],
            ),
            (
                pack.split("### 低位转强（A1/A2）", 1)[1].split("### 趋势延续（C）", 1)[0],
                pack.split("### 趋势延续（C）", 1)[1].split("## 四、", 1)[0],
            ),
        )

    def test_reports_separate_opportunities_and_keep_observations_and_input(self):
        ind = self.industries([
            {"名称": "低位A1", "分类": "A1 低位刚转强 ★★★★★"},
            {"名称": "低位A2", "分类": "A2 低位转强 ★★★★"},
            {"名称": "加速A3", "分类": "A3 低位启动后已加速 ★★★"},
            {"名称": "等待B", "分类": "B 低位等待"},
            {"名称": "趋势先行", "分类": "C 趋势机会", "机会分": 10},
            {"名称": "趋势高分", "分类": "C 趋势机会", "机会分": 90},
        ])
        before = ind.copy(deep=True)
        reports = self.render(ind)
        sections = self.opportunity_sections(reports)
        for low_turn, trend in sections:
            self.assertIn("低位A1", low_turn)
            self.assertIn("低位A2", low_turn)
            self.assertNotIn("趋势先行", low_turn)
            self.assertIn("趋势先行", trend)
            self.assertIn("趋势高分", trend)
            self.assertNotIn("低位A1", trend)
            for observation in ("加速A3", "等待B"):
                self.assertNotIn(observation, low_turn + trend)
        for report in reports:
            self.assertIn("加速A3", report)
            self.assertIn("等待B", report)
            self.assertIn("行业多周期策略", report)
            self.assertIn("候选不代表实际买卖动作", report)
        for _, trend in sections[:2]:
            self.assertLess(trend.index("趋势先行"), trend.index("趋势高分"))
        self.assertLess(sections[2][1].index("趋势高分"), sections[2][1].index("趋势先行"))
        self.pd.testing.assert_frame_equal(ind, before)

    def test_empty_opportunity_groups_keep_observations(self):
        ind = self.industries([
            {"名称": "加速A3", "分类": "A3 低位启动后已加速 ★★★"},
            {"名称": "等待B", "分类": "B 低位等待"},
        ])
        sections = self.opportunity_sections(self.render(ind))
        for low_turn, trend in sections:
            self.assertIn("暂无", low_turn)
            self.assertIn("暂无", trend)
            self.assertNotIn("加速A3", low_turn + trend)
            self.assertNotIn("等待B", low_turn + trend)

    def test_trend_candidates_survive_more_than_fifteen_low_turn_candidates(self):
        rows = [
            {"名称": f"低位行业{i}", "分类": "A1 低位刚转强 ★★★★★"}
            for i in range(16)
        ]
        rows.append({"名称": "独立趋势候选", "分类": "C 趋势机会"})
        reports = self.render(self.industries(rows))
        for low_turn, trend in self.opportunity_sections(reports):
            self.assertNotIn("独立趋势候选", low_turn)
            self.assertIn("独立趋势候选", trend)
        for report in reports[1:]:
            self.assertIn("趋势延续机会（C）：1", report)

    def test_reports_show_associations_errors_and_actual_quote_dates(self):
        ind = self.industries([
            {"名称": "低位行业", "分类": "A1 低位刚转强 ★★★★★", "最新日期": "2026-09-30", "数据源": "缓存行情", "数据状态": "缓存回退、日期未确认"},
            {"名称": "趋势行业", "分类": "C 趋势机会", "最新日期": "2026-09-30", "数据源": "测试源", "数据状态": "日期已确认"},
        ])
        base = dict.fromkeys(self.analyzer.TARGET_COLUMNS, "")
        targets = [
            {**base, "industry_name": "低位行业", "opportunity_type": "低位转强", "industry_classification": "A1", "industry_date": "2026-09-30", "industry_position": "合理区", "industry_advice": "优先研究", "code": "159001", "name": "关联ETF", "date": "2026-09-30", "source": "标的测试源", "strategy_name": "日线打分、周线加权", "status": "待更新", "participation_condition": "行业行情日期未确认，等待更新"},
            {**base, "industry_name": "趋势行业", "opportunity_type": "趋势延续", "industry_classification": "C", "industry_date": "2026-09-30", "industry_position": "偏高", "industry_advice": "等待回踩", "code": "000001", "name": "失败标的", "strategy_name": "日线打分、周线加权", "status": "取数失败", "participation_condition": "取数失败，等待更新", "error": "接口 <失败>"},
        ]
        reports = self.render(ind, targets)
        for report in reports:
            for expected in ("机会对应标的", "关联ETF", "失败标的", "取数失败", "行业行情日期未确认，等待更新", "行情截至：2026-09-30", "缓存回退 1 项", "日期未确认 1 项"):
                self.assertIn(expected, report)
        self.assertIn('<meta name="market-data-date" content="2026-09-30">', reports[0])
        self.assertIn("接口 &lt;失败&gt;", reports[0])
        self.assertNotIn("接口 <失败>", reports[0])
        self.assertIn("扫描日期：2026-10-03", reports[2])
        self.assertNotIn("数据日期：2026-10-03", reports[2])


if __name__ == "__main__":
    unittest.main()
