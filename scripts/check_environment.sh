#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "当前脚本用于 macOS；Windows 请运行 scripts/check_environment.ps1。" >&2
  exit 1
fi

for candidate in python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
    [[ "$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" == "3.12" ]]; then
    echo "[通过] Python: $candidate"
    command -v git >/dev/null 2>&1 && git --version || true
    echo "[通过] macOS 环境检查完成，未修改系统配置。"
    exit 0
  fi
done

echo "未找到 Python 3.12。请先从 python.org 安装 Python 3.12。" >&2
exit 1
