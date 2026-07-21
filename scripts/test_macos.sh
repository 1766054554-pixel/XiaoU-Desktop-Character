#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
.venv/bin/python main.py --smoke-test-ms 1500
