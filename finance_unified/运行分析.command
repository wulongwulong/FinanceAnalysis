#!/bin/bash
cd "$(dirname "$0")" || exit 1
PYTHON=".venv/bin/python3"
if [ ! -x "$PYTHON" ]; then PYTHON="python3"; fi
echo "Finance 分析：新机会 → 标的判断 → 日常监控 → 历史验证"
"$PYTHON" main.py --serve
status=$?
read -r -p "按回车关闭窗口..."
exit "$status"
