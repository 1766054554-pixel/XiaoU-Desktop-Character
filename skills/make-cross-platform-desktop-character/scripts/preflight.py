#!/usr/bin/env python3
"""Check whether a XiaoU checkout is ready for local character production."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path


REQUIRED_PATHS = (
    "AGENTS.md",
    "agent-guide/AGENT_GUIDE.md",
    "tools/onepic_workflow.py",
    "tools/prepare_custom_pet.py",
    "assets/pet/manifest.json",
    ".gitignore",
)


def inspect(project: Path) -> dict[str, object]:
    missing = [relative for relative in REQUIRED_PATHS if not (project / relative).exists()]
    gitignore = (project / ".gitignore").read_text(encoding="utf-8") if not missing else ""
    private_rule = "user_assets/*" in gitignore and "!user_assets/README.md" in gitignore
    supported_system = platform.system() in {"Windows", "Darwin"}
    python_ok = sys.version_info[:2] == (3, 12)
    return {
        "ok": not missing and private_rule and supported_system and python_ok,
        "project": str(project),
        "platform": platform.system(),
        "python": platform.python_version(),
        "missing": missing,
        "private_assets_ignored": private_rule,
        "supported_platform": supported_system,
        "python_3_12": python_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查小u桌面角色制作环境")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = inspect(args.project.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
