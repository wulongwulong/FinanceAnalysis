#!/bin/bash
cd "$(dirname "$0")" || exit 1
PYTHON=".venv/bin/python3"
if [ ! -x "$PYTHON" ]; then PYTHON="python3"; fi
"$PYTHON" main.py --demo
status=$?
if [ -f outputs/demo/index.html ]; then open outputs/demo/index.html; fi
read -r -p "按回车关闭窗口..."
exit "$status"
