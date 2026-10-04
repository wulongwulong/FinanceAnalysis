#!/bin/bash
cd "$(dirname "$0")" || exit 1
PYTHON=".venv/bin/python3"
if [ ! -x "$PYTHON" ]; then PYTHON="python3"; fi
"$PYTHON" main.py --holdings
