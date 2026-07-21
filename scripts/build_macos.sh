#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
export XIAOU_INCLUDE_USER_ASSETS=0

if [[ "${1:-}" == "--include-user-assets" ]]; then
  .venv/bin/python tools/onepic_workflow.py check-package
  export XIAOU_INCLUDE_USER_ASSETS=1
fi

.venv/bin/pyinstaller --noconfirm --clean XiaoUDesktopCharacter-Mac.spec
echo "生成完成：dist/XiaoU.app"
