from __future__ import annotations

import traceback
from pathlib import Path
from unittest.mock import patch


def run(root: Path, demo: bool = False) -> Path:
    from . import analyzer

    analyzer.configure_paths(root, demo=demo)
    try:
        if not demo:
            return analyzer.main()

        from ..common.demo import sector_rows

        analyzer.log("离线演示：全部行业和全球资产行情均为模拟数据。")
        names = [
            ("801010", "农林牧渔", "一级行业"),
            ("801030", "基础化工", "一级行业"),
            ("801040", "钢铁", "一级行业"),
            ("801050", "有色金属", "一级行业"),
            ("801080", "电子", "一级行业"),
            ("801110", "家用电器", "一级行业"),
            ("801120", "食品饮料", "一级行业"),
            ("801150", "医药生物", "一级行业"),
            ("801160", "公用事业", "一级行业"),
            ("801170", "交通运输", "一级行业"),
            ("801082", "半导体", "二级行业"),
            ("801751", "软件开发", "二级行业"),
        ]
        histories = {
            code: analyzer.norm(analyzer.pd.DataFrame(sector_rows(i + 1, 280, 1500 + i * 100)))
            for i, (code, _, _) in enumerate(names)
        }
        benchmark = analyzer.norm(analyzer.pd.DataFrame(sector_rows(100, 280, 4000)))
        assets = [
            ("黄金", 2600), ("WTI原油", 70), ("Brent原油", 75),
            ("标普500", 5000), ("纳斯达克100", 18000), ("纳斯达克综合", 15000),
            ("道琼斯", 40000), ("罗素2000", 2200), ("费城半导体SOX", 4500),
            ("美国10年期收益率", 4), ("VIX", 18), ("美元广义指数", 120),
        ]
        global_rows = []
        for i, (name, base) in enumerate(assets):
            data = analyzer.pd.DataFrame(sector_rows(200 + i, 280, base))
            row = analyzer.analyze(name, data, None, "全球资产")
            row["数据源"] = "离线演示（模拟数据）"
            global_rows.append(row)
        with patch.multiple(
            analyzer,
            benchmark=lambda: benchmark.copy(),
            sw_list=lambda: (names, []),
            sw_hist=lambda code: histories[code].copy(),
            global_data=lambda: analyzer.pd.DataFrame(global_rows),
        ):
            return analyzer.main()
    except Exception:
        (analyzer.LOG_REPORTS / f"{analyzer.RUN_TAG}_运行错误.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        raise
