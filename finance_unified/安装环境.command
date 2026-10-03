#!/bin/bash
set -e
cd "$(dirname "$0")" || exit 1
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
echo "统一环境已安装。现在可以运行 运行分析.command 或 离线演示.command。"
read -r -p "按回车关闭窗口..."
