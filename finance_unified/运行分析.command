#!/bin/bash
cd "$(dirname "$0")" || exit 1
PYTHON=".venv/bin/python3"
if [ ! -x "$PYTHON" ]; then PYTHON="python3"; fi
echo "1. 全部分析  2. ETF日报  3. 板块与标的  4. 基金板块  5. ETF午间提醒"
read -r -p "请选择 [1-5]，回车运行全部：" choice
case "$choice" in
  1|"") "$PYTHON" main.py all ;;
  2) "$PYTHON" main.py etf ;;
  3) "$PYTHON" main.py sector ;;
  4) "$PYTHON" main.py fund ;;
  5) "$PYTHON" main.py etf --mode alert ;;
  *) echo "无效选择"; exit 2 ;;
esac
status=$?
if [ -f outputs/index.html ]; then open outputs/index.html; fi
read -r -p "按回车关闭窗口..."
exit "$status"
