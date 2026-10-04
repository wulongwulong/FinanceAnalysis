"""Finance 分析：一次运行，一份报告。"""
from __future__ import annotations
import argparse
import html
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = Path('analysis/03_最新文件/最新报告.html')


def build_index(root, report=None, error=None):
    outputs = root / 'outputs'
    outputs.mkdir(parents=True, exist_ok=True)
    path = outputs / 'index.html'
    if error is None:
        shutil.copyfile(report or outputs / REPORT, path)
    else:
        path.write_text(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Finance 分析</title>'
            '<h1>Finance 分析</h1>'
            f'<p>本次分析失败：{html.escape(str(error))}</p>'
            f'<p>运行时间：{datetime.now():%Y-%m-%d %H:%M:%S}</p>'
            '<p>本页没有展示本次有效分析结果。请根据错误提示检查安装环境或行情接口后重试。</p></html>',
            encoding='utf-8',
        )
    return path


def run_analysis(root, demo=False, mode='report'):
    try:
        if mode == 'alert':
            from .etf.runner import run
            report = run(root, demo=demo, mode='alert')
            print(f'标的提醒：{report}')
            return 0
        from .unified import run
        report = run(root, demo=demo)
        path = build_index(root, report=report)
        print(f'\nFinance 分析报告：{path}')
        return 0
    except (Exception, SystemExit) as error:
        message = f'缺少依赖 {error.name}，请先运行 安装环境.command' if isinstance(error, ModuleNotFoundError) else str(error)
        path = build_index(root, error=message)
        print(f'分析失败：{message}\n错误说明：{path}')
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description='Finance 分析：新机会、标的判断、日常监控与历史验证')
    # 保留旧命令与已安装定时任务兼容；正常启动都进入同一分析流程。
    parser.add_argument('task', nargs='?', default='analyze', help=argparse.SUPPRESS)
    parser.add_argument('--demo', action='store_true', help='使用模拟数据，报告和历史写入独立 demo 目录')
    parser.add_argument('--mode', choices=['report', 'alert'], default='report', help='完整分析或标的提醒，默认完整分析')
    parser.add_argument('--serve', action='store_true', help='分析后打开本机报告与持仓编辑服务')
    parser.add_argument('--holdings', action='store_true', help='直接维护实际持仓，不扫描行情')
    args = parser.parse_args(argv)
    if args.task not in ('analyze', 'all', 'fund', 'sector', 'etf'):
        parser.error('请直接运行 main.py，或使用 --demo / --mode alert')
    if (args.serve or args.holdings) and (args.demo or args.mode == 'alert'):
        parser.error('持仓编辑仅用于正式报告，不与演示或提醒模式组合')
    if args.holdings:
        from .portfolio import serve
        serve(ROOT, edit=True)
        return 0
    if not args.demo:
        status = run_analysis(ROOT, mode=args.mode)
        if args.serve:
            from .portfolio import serve
            serve(ROOT)
        return status
    with tempfile.TemporaryDirectory() as directory:
        demo_root = Path(directory)
        shutil.copytree(ROOT / 'config', demo_root / 'config')
        status = run_analysis(demo_root, demo=True, mode=args.mode)
        for folder in ('outputs', 'data'):
            if (demo_root / folder).exists():
                shutil.copytree(demo_root / folder, ROOT / folder / 'demo', dirs_exist_ok=True)
    print(f'演示报告：{ROOT / "outputs/demo/index.html"}')
    return status
