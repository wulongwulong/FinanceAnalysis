#!/bin/bash
set -e
cd "$(dirname "$0")" || exit 1
TASK_PYTHON="$PWD/.venv/bin/python3"
if [ ! -x "$TASK_PYTHON" ]; then TASK_PYTHON="$(command -v python3)"; fi
"$TASK_PYTHON" - "$PWD" <<'PY'
import plistlib
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
agents = Path.home() / 'Library/LaunchAgents'
agents.mkdir(parents=True, exist_ok=True)
outputs = root / 'outputs/etf'
outputs.mkdir(parents=True, exist_ok=True)
for mode, hour in (('alert', 11), ('report', 15)):
    label = f'com.local.etf.monitor.{mode}'
    path = agents / f'{label}.plist'
    config = {
        'Label': label,
        'ProgramArguments': [sys.executable, str(root / 'main.py'), 'etf', '--mode', mode],
        'WorkingDirectory': str(root),
        'StartCalendarInterval': [{'Weekday': day, 'Hour': hour, 'Minute': 30} for day in range(1, 6)],
        'StandardOutPath': str(outputs / f'{mode}_schedule.log'),
        'StandardErrorPath': str(outputs / f'{mode}_schedule.err.log'),
    }
    subprocess.run(['launchctl', 'unload', str(path)], capture_output=True)
    path.write_bytes(plistlib.dumps(config))
    subprocess.run(['launchctl', 'load', str(path)], check=True)
print('ETF定时任务已切换到本项目：工作日11:30午间提醒、15:30收盘日报。')
PY
read -r -p "按回车关闭窗口..."
