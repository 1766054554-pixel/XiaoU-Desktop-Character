"""
本机多角色靠近互动的 presence 通道。

两只（或多只）桌宠各自独立进程运行时，通过用户缓存目录下的小 JSON
互相广播位置；靠近后由窗口层触发同步动作与对白。不经过网络。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True)
class PeerPresence:
    """一只桌宠对外广播的瞬时状态。"""

    character_id: str
    display_name: str
    x: float
    y: float
    width: int
    height: int
    facing: int
    busy: bool
    ts: float
    # 正在走向的对方 id；空字符串表示没有在走近
    approaching_id: str = ""
    # 正在与谁碰面互动；空字符串表示没有
    meeting_id: str = ""
    # 对话导演（较小 character_id）选定的剧本与开聊墙钟时间
    chat_id: int = -1
    chat_started_at: float = 0.0
    # 同步动作：如 peer_meet / hug；空字符串表示没有
    sync_action: str = ""
    sync_action_at: float = 0.0

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0


# 共享对白剧本：短一点、有来有回；偶数句导演说，奇数句另一方接
DEFAULT_PEER_CONVERSATIONS: tuple[tuple[str, ...], ...] = (
    (
        "{peer}，今天脑子转得动吗？",
        "勉勉强强……你呢？",
        "我还行，看见你就好些了。",
        "那我再站一会儿。",
    ),
    (
        "偷偷说，刚才差点把你认成图标。",
        "喂！我有那么扁吗？",
        "没有，就是桌面太挤了。",
        "那你挨我近一点，省地方。",
    ),
    (
        "要不要一起偷懒两分钟？",
        "成交。计时开始。",
        "……好像已经过了。",
        "那再偷一分钟。",
    ),
    (
        "心心库存还有，你要吗？",
        "要。多给两颗。",
        "贪心。",
        "对你才会贪心。",
    ),
    (
        "忙完记得眨眨眼，别一直盯屏幕。",
        "你怎么比我妈还碎碎念。",
        "碎碎念也是关心。",
        "……知道了，谢谢你。",
    ),
    (
        "如果桌面会说话，它大概在催我们工作。",
        "那就让它催，我们先站着。",
        "你今天脾气很好。",
        "因为你来了呀。",
    ),
    (
        "等下要是走散了，你就招招手。",
        "好，你也别装失踪。",
        "我不会。",
        "嗯，我信你。",
    ),
    (
        "有点想听你胡扯一句。",
        "那我正式宣布：今天的风是甜的。",
        "……行，录取。",
        "嘿嘿。",
    ),
)

# 对白轮换要快一点，免得干等；自言自语另走更慢节奏
DIALOGUE_TURN_S = 4.2
SOLO_MURMUR_MIN_GAP_S = 18.0
SYNC_ACTION_HOLD_S = 5.5
# 碰面保持稍远并肩距离；拥抱不再额外贴近，避免远近平移
STAND_OVERLAP_RATIO = 0.48
PEER_INTERRUPT_COOLDOWN_S = 32.0
# 被拆散后偶尔仍想找回去：短冷静后再追
PEER_REAPPROACH_CHANCE = 0.42
PEER_REAPPROACH_COOLDOWN_S = (7.0, 16.0)


def dialogue_turn_index(
    chat_started_at: float,
    *,
    now: float | None = None,
    turn_s: float = DIALOGUE_TURN_S,
) -> int:
    """根据开聊时间计算当前该说第几句；尚未开始返回 -1。"""

    if chat_started_at <= 0:
        return -1
    wall = time.time() if now is None else now
    if wall < chat_started_at:
        return -1
    return int((wall - chat_started_at) / turn_s)


def dialogue_line_for_turn(
    conversation: tuple[str, ...] | list[str],
    turn: int,
) -> str | None:
    """取剧本中某一轮的台词；越界返回 None。"""

    if turn < 0 or turn >= len(conversation):
        return None
    return str(conversation[turn])


def format_dialogue_line(template: str, *, me: str, peer: str) -> str:
    """填充 {me}/{peer}；缺失占位符时原样返回。"""

    try:
        return template.format(me=me, peer=peer)
    except (KeyError, ValueError):
        return template


def is_dialogue_director(me_id: str, peer_id: str) -> bool:
    """较小 character_id 担任对白导演，负责选定剧本。"""

    return me_id <= peer_id


def peer_directory() -> Path:
    """返回本机 presence 文件目录（跨角色共享）。"""

    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "DesktopPetPeers"
    # macOS / Linux：缓存目录，不污染用户文档
    return Path.home() / "Library" / "Caches" / "DesktopPetPeers"


def _safe_filename(character_id: str) -> str:
    cleaned = _SAFE_ID.sub("_", (character_id or "pet").strip()) or "pet"
    return f"{cleaned}.json"


def presence_path(character_id: str, directory: Path | None = None) -> Path:
    """某个角色的 presence 文件路径。"""

    return (directory or peer_directory()) / _safe_filename(character_id)


def write_presence(
    presence: PeerPresence,
    *,
    directory: Path | None = None,
) -> Path:
    """原子写入当前角色 presence，供其他进程读取。"""

    root = directory or peer_directory()
    root.mkdir(parents=True, exist_ok=True)
    target = presence_path(presence.character_id, root)
    temporary = target.with_suffix(".json.tmp")
    payload = asdict(presence)
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def clear_presence(character_id: str, *, directory: Path | None = None) -> None:
    """退出时删除自己的 presence，避免被当成在线。"""

    path = presence_path(character_id, directory)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _parse_presence(data: dict[str, Any]) -> PeerPresence | None:
    try:
        character_id = str(data.get("character_id", "")).strip()
        if not character_id:
            return None
        return PeerPresence(
            character_id=character_id,
            display_name=str(data.get("display_name") or character_id),
            x=float(data.get("x", 0)),
            y=float(data.get("y", 0)),
            width=max(1, int(data.get("width", 1))),
            height=max(1, int(data.get("height", 1))),
            facing=1 if int(data.get("facing", -1)) >= 0 else -1,
            busy=bool(data.get("busy", False)),
            ts=float(data.get("ts", 0)),
            approaching_id=str(data.get("approaching_id") or "").strip(),
            meeting_id=str(data.get("meeting_id") or "").strip(),
            chat_id=int(data.get("chat_id", -1) or -1),
            chat_started_at=float(data.get("chat_started_at", 0) or 0),
            sync_action=str(data.get("sync_action") or "").strip(),
            sync_action_at=float(data.get("sync_action_at", 0) or 0),
        )
    except (TypeError, ValueError):
        return None


def read_presence(
    character_id: str,
    *,
    directory: Path | None = None,
    max_age_s: float = 1.5,
    now: float | None = None,
) -> PeerPresence | None:
    """读取指定角色 presence；过期或不存在则返回 None。"""

    path = presence_path(character_id, directory)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    presence = _parse_presence(raw)
    if presence is None:
        return None
    # 文件里存的是 time.time()；用墙钟判断新鲜度
    wall = time.time() if now is None else now
    if wall - presence.ts > max_age_s:
        return None
    return presence


def list_peers(
    *,
    exclude_id: str,
    directory: Path | None = None,
    max_age_s: float = 1.5,
    now: float | None = None,
) -> list[PeerPresence]:
    """列出除自己以外仍在线的其他角色。"""

    root = directory or peer_directory()
    if not root.exists():
        return []
    wall = time.time() if now is None else now
    peers: list[PeerPresence] = []
    for path in sorted(root.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        presence = _parse_presence(raw)
        if presence is None:
            continue
        if presence.character_id == exclude_id:
            continue
        if wall - presence.ts > max_age_s:
            continue
        peers.append(presence)
    return peers


def horizontal_gap(a: PeerPresence, b: PeerPresence) -> float:
    """两只角色外接矩形在水平方向上的间隙（重叠为 0）。"""

    left = max(a.x, b.x)
    right = min(a.x + a.width, b.x + b.width)
    if right >= left:
        return 0.0
    return left - right


def vertical_center_delta(a: PeerPresence, b: PeerPresence) -> float:
    """两只角色中心点的垂直距离。"""

    return abs(a.center_y - b.center_y)


def stand_beside_target(
    me: PeerPresence,
    peer: PeerPresence,
    *,
    side_gap: float | None = None,
    cuddle: bool = False,
) -> tuple[float, float, bool]:
    """计算站到对方身边的目标位置，并返回是否站在对方左侧。

    窗口四周有透明留白，需要适度重叠窗口，人物看起来才像并肩。
    站哪一侧跟当前相对位置走：本来在左就站左，避免总被赶到同一边。
    cuddle 参数保留兼容，不再额外贴紧。
    """

    del cuddle  # 拥抱与并肩同一距离，不再莫名贴近
    if abs(me.center_x - peer.center_x) < 12.0:
        stand_left = me.character_id < peer.character_id
    else:
        stand_left = me.center_x <= peer.center_x
    overlap = (
        float(side_gap)
        if side_gap is not None
        else max(48.0, min(me.width, peer.width) * STAND_OVERLAP_RATIO)
    )
    if stand_left:
        target_x = peer.x - me.width + overlap
    else:
        target_x = peer.x + peer.width - overlap
    target_y = peer.center_y - me.height / 2.0
    return target_x, target_y, stand_left


def arrived_beside(
    me: PeerPresence,
    peer: PeerPresence,
    *,
    max_pos_error: float = 10.0,
    side_gap: float | None = None,
) -> bool:
    """是否已走到对方身边（贴紧目标点且高度基本对齐）。"""

    target_x, target_y, _stand_left = stand_beside_target(me, peer, side_gap=side_gap)
    return abs(me.x - target_x) <= max_pos_error and abs(me.y - target_y) <= max_pos_error


def centers_near(
    a: PeerPresence,
    b: PeerPresence,
    *,
    max_gap_px: float = 4.0,
    max_vertical_px: float = 22.0,
) -> bool:
    """判断两只角色是否已贴到可互动的身侧距离（很近才算）。"""

    if vertical_center_delta(a, b) > max_vertical_px:
        return False
    gap = horizontal_gap(a, b)
    # 完全叠在同一竖线（水平大面积重叠）不算到位，还要先挪到身侧
    overlap = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
    min_width = min(a.width, b.width)
    if overlap > min_width * 0.55:
        return False
    # 允许轻微重叠（gap=0）或极小间隙
    return gap <= max_gap_px


def within_approach_range(
    a: PeerPresence,
    b: PeerPresence,
    *,
    max_center_dist_px: float = 1400.0,
) -> bool:
    """判断是否值得朝对方走过去（允许较大高度差，斜向走近）。"""

    dx = a.center_x - b.center_x
    dy = a.center_y - b.center_y
    return (dx * dx + dy * dy) ** 0.5 <= max_center_dist_px


def facing_toward(self_center_x: float, peer_center_x: float) -> int:
    """面向对方：对方在右则朝右（+1），否则朝左（-1）。"""

    if abs(peer_center_x - self_center_x) < 1.0:
        return 1
    return 1 if peer_center_x > self_center_x else -1


def facing_for_meetup(me: PeerPresence, peer: PeerPresence) -> int:
    """碰面动作朝向：始终面朝对方中心；几乎重合时按站位决定。"""

    if abs(me.center_x - peer.center_x) >= 12.0:
        return facing_toward(me.center_x, peer.center_x)
    # 几乎同一竖线：站在左边就朝右，站在右边就朝左
    return 1 if me.x <= peer.x else -1
