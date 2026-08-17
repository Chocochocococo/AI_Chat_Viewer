#!/bin/sh
# Mac / Linux 用的啟動腳本（Windows 請用 啟動檢視器.cmd）
cd "$(dirname "$0")" || exit 1

for PY in python3 python; do
  if command -v "$PY" >/dev/null 2>&1; then
    exec "$PY" launch.py
  fi
done

echo "找不到 python3，請先安裝 Python 3.8 以上"
exit 1
