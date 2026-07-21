#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  echo "尚未创建 .venv，请先运行 scripts/setup_environment.sh。" >&2
  exit 1
fi
exec "$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/main.py" "$@"
