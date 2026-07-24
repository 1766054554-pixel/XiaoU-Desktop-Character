"""
本模块负责桌面角色默认配置、用户配置、尺寸和窗口位置状态的加载与保存。

职责范围：
- 从项目内只读 JSON 读取默认功能设置；
- 从当前用户本地应用数据目录读取上次窗口位置和用户选择的显示尺寸；
- 校验窗口、移动、动画和转身节奏并忽略未知字段；
- 在用户配置目录保存窗口位置、显示尺寸、说话开关、桌面空间偏好和双人靠近互动开关，其他体验参数采用项目默认值。

Agent 快速定位：
- 配置数据结构位于 PetSettings；
- 合并和校验逻辑位于 load_settings()；
- 持久化入口位于 save_settings()；
- 不应把机器相关的绝对路径写入项目默认配置。

输入为 JSON 文件，输出为 PetSettings 实例。保存操作会创建用户配置目录并原子写入
`start_x`、`start_y`、`display_height`、`speech_enabled`、`join_all_spaces` 与
`peer_interaction_enabled`，不会覆盖项目默认配置。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .resources import resource_path


@dataclass
class PetSettings:
    """保存桌面角色可配置参数和上次窗口位置。"""

    display_height: int = 150
    movement_interval_ms: int = 16
    movement_step: int = 1
    walk_frame_interval_ms: int = 90
    turn_pause_ms: int = 240
    idle_min_ms: int = 3000
    idle_max_ms: int = 7000
    action_min_ms: int = 3500
    action_max_ms: int = 7000
    inactive_sit_ms: int = 300000
    inactive_sleep_ms: int = 600000
    mood_update_interval_ms: int = 30000
    always_on_top: bool = True
    speech_enabled: bool = True
    # True=全部桌面空间都在；False=只留在当前桌面
    join_all_spaces: bool = True
    # True=发现其他桌宠靠近时自动互动
    peer_interaction_enabled: bool = True
    start_x: int | None = None
    start_y: int | None = None


def user_settings_path() -> Path:
    """返回当前用户可写的设置文件路径。"""

    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".desktop_pet"
    folder = "XiaoUDesktopCharacter"
    try:
        from .branding import load_branding

        folder = load_branding().settings_folder or folder
    except Exception:
        pass
    return root / folder / "settings.json"


def _read_json(path: Path) -> dict[str, Any]:
    """读取 JSON 对象；文件不存在时返回空对象。"""

    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取配置文件 {path}：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"配置文件必须包含 JSON 对象：{path}")
    return value


def _validated(data: dict[str, Any]) -> PetSettings:
    """过滤未知字段并对关键数值执行安全范围校验。"""

    allowed = {field.name for field in fields(PetSettings)}
    clean = {key: value for key, value in data.items() if key in allowed}
    settings = PetSettings(**clean)
    settings.display_height = min(600, max(120, int(settings.display_height)))
    settings.movement_interval_ms = min(
        100,
        max(16, int(settings.movement_interval_ms)),
    )
    settings.movement_step = min(12, max(1, int(settings.movement_step)))
    settings.walk_frame_interval_ms = min(
        500,
        max(50, int(settings.walk_frame_interval_ms)),
    )
    settings.turn_pause_ms = min(1200, max(0, int(settings.turn_pause_ms)))
    settings.idle_min_ms = max(500, int(settings.idle_min_ms))
    settings.idle_max_ms = max(settings.idle_min_ms, int(settings.idle_max_ms))
    settings.action_min_ms = max(1000, int(settings.action_min_ms))
    settings.action_max_ms = max(
        settings.action_min_ms,
        int(settings.action_max_ms),
    )
    settings.inactive_sit_ms = max(5000, int(settings.inactive_sit_ms))
    settings.inactive_sleep_ms = max(
        settings.inactive_sit_ms + 5000,
        int(settings.inactive_sleep_ms),
    )
    settings.mood_update_interval_ms = min(
        300000,
        max(10000, int(settings.mood_update_interval_ms)),
    )
    settings.speech_enabled = bool(settings.speech_enabled)
    settings.join_all_spaces = bool(settings.join_all_spaces)
    settings.peer_interaction_enabled = bool(settings.peer_interaction_enabled)
    settings.always_on_top = bool(settings.always_on_top)
    return settings


def load_settings(
    default_path: Path | None = None,
    override_path: Path | None = None,
) -> PetSettings:
    """合并默认与用户配置；损坏的用户配置回退为默认配置。"""

    default_file = default_path or resource_path("config/settings.json")
    user_file = override_path or user_settings_path()
    base = _read_json(default_file)
    try:
        override = _read_json(user_file)
    except ValueError:
        override = {}
    base.update(
        {
            key: value
            for key, value in override.items()
            if key
            in {
                "display_height",
                "start_x",
                "start_y",
                "speech_enabled",
                "join_all_spaces",
                "peer_interaction_enabled",
            }
        }
    )
    return _validated(base)


def save_settings(settings: PetSettings, path: Path | None = None) -> Path:
    """将设置原子写入用户目录并返回最终路径。"""

    target = path or user_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    state = {
        "display_height": settings.display_height,
        "speech_enabled": settings.speech_enabled,
        "join_all_spaces": settings.join_all_spaces,
        "peer_interaction_enabled": settings.peer_interaction_enabled,
        "start_x": settings.start_x,
        "start_y": settings.start_y,
    }
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target
