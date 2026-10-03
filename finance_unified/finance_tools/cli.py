"""独立项目的分析入口与报告目录。"""
from __future__ import annotations
import argparse
import html
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = {'etf': 'ETF每日监控', 'sector': '板块与标的分析', 'fund': '基金板块与历史验证'}
REPORTS = {
    'etf': Path('etf/latest.html'),
    'sector': Path('sector/latest.html'),
    'fund': Path('fund/03_最新文件/最新报告.html'),
}


def build_index(root, statuses=None, demo=False, reports=None):
    outputs = root / 'outputs'
    outputs.mkdir(parents=True, exist_ok=True)
    rows = []
    for task, name in NAMES.items():
        relative = (reports or {}).get(task, REPORTS[task])
        report = outputs / relative
        status = (statuses or {}).get(task, '已有报告' if report.exists() else '尚未运行')
        link = f'<a href="{relative.as_posix()}">查看报告</a>' if report.exists() else ''
        modified = datetime.fromtimestamp(report.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S') if report.exists() else '—'
        rows.append(f'<tr><td>{name}</td><td>{html.escape(status)}</td><td>{modified}</td><td>{link}</td></tr>')
    title = 'Finance 综合分析' + (' · 离线演示（模拟数据）' if demo else '')
    text = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;color:#243047;background:#f7f9fc}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:18px;text-align:left;border-bottom:1px solid #e2e8f0}}a{{color:#245fca}}.scroll{{overflow:auto}}p{{line-height:1.7}}</style>
<h1>{title}</h1><p>行业筛选 → 标的执行 → 日常监控与历史验证。报告更新于各模块运行时。</p>
<div class="scroll"><table><tr><th>分析功能</th><th>本次状态</th><th>报告时间</th><th>报告入口</th></tr>{''.join(rows)}</table></div>
<p>三套策略保留各自的分类和周线规则；同一标的出现不同信号时，请结合报告中的规则与时段比较。</p>
<p>仅用于研究、量化筛选和决策辅助。</p></html>'''
    path = outputs / 'index.html'
    path.write_text(text, encoding='utf-8')
    return path


def run_tasks(root, tasks, demo=False, mode='report', limit=0):
    # 延迟导入：使用ETF或板块模块无需安装基金模块的第三方依赖。
    from .etf.runner import run as run_etf
    from .sector.runner import run as run_sector
    from .fund.runner import run as run_fund

    runners = {'etf': lambda: run_etf(root, demo=demo, mode=mode),
               'sector': lambda: run_sector(root, demo=demo, limit=limit),
               'fund': lambda: run_fund(root, demo=demo)}
    statuses = {}
    reports = {}
    for task in tasks:
        print(f'\n===== {NAMES[task]} =====', flush=True)
        try:
            result = runners[task]()
            reports[task] = result.resolve().relative_to((root / 'outputs').resolve())
            statuses[task] = '完成'
            print(f'报告：{result}', flush=True)
        except ModuleNotFoundError as error:
            statuses[task] = f'失败：缺少依赖 {error.name}，请运行 安装环境.command'
            print(statuses[task], flush=True)
        except (Exception, SystemExit) as error:
            statuses[task] = f'失败：{error}'
            print(statuses[task], flush=True)
    path = build_index(root, statuses, demo=demo, reports=reports)
    print(f'\n统一报告入口：{path}')
    return 1 if any(status.startswith('失败') for status in statuses.values()) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Finance统一分析项目')
    parser.add_argument('task', choices=[*NAMES, 'all'], nargs='?', default='all')
    parser.add_argument('--demo', action='store_true', help='使用模拟数据；报告写入 outputs/demo，历史写入 data/demo')
    parser.add_argument('--mode', choices=['report', 'alert'], default=None, help='ETF运行模式，默认 report')
    parser.add_argument('--limit', type=int, default=None, help='板块与标的扫描数量，0表示全部')
    args = parser.parse_args(argv)
    if args.mode is not None and args.task not in ('etf', 'all'):
        parser.error('--mode 仅适用于 etf / all')
    if args.limit is not None and (args.task not in ('sector', 'all') or args.limit < 0):
        parser.error('--limit 仅适用于 sector / all，且不能小于0')
    tasks = list(NAMES) if args.task == 'all' else [args.task]
    if not args.demo:
        return run_tasks(ROOT, tasks, mode=args.mode or 'report', limit=args.limit or 0)

    # 演示从空历史开始，结束后仅保存到独立的演示目录。
    with tempfile.TemporaryDirectory() as directory:
        demo_root = Path(directory)
        shutil.copytree(ROOT / 'config', demo_root / 'config')
        status = run_tasks(demo_root, tasks, demo=True, mode=args.mode or 'report', limit=args.limit or 0)
        for folder in ('outputs', 'data'):
            if (demo_root / folder).exists():
                shutil.copytree(demo_root / folder, ROOT / folder / 'demo', dirs_exist_ok=True)
    print(f'演示报告：{ROOT / "outputs/demo/index.html"}')
    return status
