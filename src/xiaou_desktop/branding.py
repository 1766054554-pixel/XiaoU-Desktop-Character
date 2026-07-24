"""
本模块读取可选的 user_assets/branding.json，用于鸡蛋壳等定制角色的名称、配色与菜单。

若文件不存在，则回退为小u默认粉色主题，保证公开演示构建不受影响。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .resources import resource_path


@dataclass
class BrandTheme:
    menu_bg: str = "#fff9fb"
    menu_border: str = "#e8afc2"
    menu_selected: str = "#f9dce7"
    menu_separator: str = "#eadde2"
    title: str = "#1f3552"
    muted: str = "#665a62"
    speech_border: tuple[int, int, int, int] = (231, 169, 191, 245)
    speech_fill: tuple[int, int, int, int] = (255, 249, 251, 248)
    speech_text: str = "#28354a"
    affinity: str = "#df5b86"
    energy: str = "#4387c7"
    boredom: str = "#d69a31"
    hunger: str = "#6c9d56"
    bar_track: str = "#ece8eb"
    heart_main: tuple[int, int, int, int] = (255, 105, 150, 245)
    heart_soft: tuple[int, int, int, int] = (255, 165, 195, 235)


@dataclass
class Branding:
    character_id: str = "xiaou"
    display_name: str = "小u"
    settings_folder: str = "XiaoUDesktopCharacter"
    theme: BrandTheme = field(default_factory=BrandTheme)
    status_prefix: str = "小u现在："
    size_menu_label: str = "小u大小"
    labels: dict[str, str] = field(default_factory=dict)
    speech_lines: tuple[str, ...] = ()
    state_speech: dict[str, tuple[str, ...]] = field(default_factory=dict)
    peer_speech: tuple[str, ...] = ()
    peer_notice_speech: tuple[str, ...] = ()
    peer_approach_speech: tuple[str, ...] = ()
    peer_miss_speech: tuple[str, ...] = ()
    menu: dict[str, Any] = field(default_factory=dict)

    @property
    def is_custom(self) -> bool:
        return self.character_id != "xiaou" and bool(self.menu.get("groups"))


def _as_rgba(value: Any, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return tuple(int(v) for v in value)  # type: ignore[return-value]
    return fallback


def load_branding() -> Branding:
    """加载定制品牌配置；缺失或演示模式下返回小u默认值。"""

    import os

    if os.environ.get("ONEPIC_USE_DEMO_ASSETS") == "1":
        return Branding()
    try:
        path = resource_path("user_assets/branding.json")
    except FileNotFoundError:
        return Branding()
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_theme = data.get("theme", {})
    theme = BrandTheme(
        menu_bg=str(raw_theme.get("menu_bg", BrandTheme.menu_bg)),
        menu_border=str(raw_theme.get("menu_border", BrandTheme.menu_border)),
        menu_selected=str(raw_theme.get("menu_selected", BrandTheme.menu_selected)),
        menu_separator=str(raw_theme.get("menu_separator", BrandTheme.menu_separator)),
        title=str(raw_theme.get("title", BrandTheme.title)),
        muted=str(raw_theme.get("muted", BrandTheme.muted)),
        speech_border=_as_rgba(raw_theme.get("speech_border"), BrandTheme.speech_border),
        speech_fill=_as_rgba(raw_theme.get("speech_fill"), BrandTheme.speech_fill),
        speech_text=str(raw_theme.get("speech_text", BrandTheme.speech_text)),
        affinity=str(raw_theme.get("affinity", BrandTheme.affinity)),
        energy=str(raw_theme.get("energy", BrandTheme.energy)),
        boredom=str(raw_theme.get("boredom", BrandTheme.boredom)),
        hunger=str(raw_theme.get("hunger", BrandTheme.hunger)),
        bar_track=str(raw_theme.get("bar_track", BrandTheme.bar_track)),
        heart_main=_as_rgba(raw_theme.get("heart_main"), BrandTheme.heart_main),
        heart_soft=_as_rgba(raw_theme.get("heart_soft"), BrandTheme.heart_soft),
    )
    state_speech = {
        str(key): tuple(str(line) for line in lines[:8])
        for key, lines in dict(data.get("state_speech", {})).items()
        if isinstance(lines, list)
    }
    peer_dialogue = data.get("peer_dialogue")
    peer_speech_raw = data.get("peer_speech", [])
    peer_notice_raw: list[Any] = []
    peer_approach_raw: list[Any] = []
    peer_miss_raw: list[Any] = []
    if isinstance(peer_dialogue, dict):
        peer_speech_raw = peer_dialogue.get("meet", peer_speech_raw)
        peer_notice_raw = list(peer_dialogue.get("notice", []))
        peer_approach_raw = list(peer_dialogue.get("approach", []))
        peer_miss_raw = list(peer_dialogue.get("miss", []))
    else:
        peer_notice_raw = list(data.get("peer_notice_speech", []))
        peer_approach_raw = list(data.get("peer_approach_speech", []))
        peer_miss_raw = list(data.get("peer_miss_speech", []))
    return Branding(
        character_id=str(data.get("character_id", "xiaou")),
        display_name=str(data.get("display_name", "小u")),
        settings_folder=str(data.get("settings_folder", "XiaoUDesktopCharacter")),
        theme=theme,
        status_prefix=str(data.get("status_prefix", "小u现在：")),
        size_menu_label=str(data.get("size_menu_label", "小u大小")),
        labels={str(k): str(v) for k, v in dict(data.get("labels", {})).items()},
        speech_lines=tuple(str(line) for line in list(data.get("speech_lines", []))[:80]),
        state_speech=state_speech,
        peer_speech=tuple(str(line) for line in list(peer_speech_raw or [])[:40]),
        peer_notice_speech=tuple(str(line) for line in peer_notice_raw[:24]),
        peer_approach_speech=tuple(str(line) for line in peer_approach_raw[:24]),
        peer_miss_speech=tuple(str(line) for line in peer_miss_raw[:16]),
        menu=dict(data.get("menu", {})),
    )
