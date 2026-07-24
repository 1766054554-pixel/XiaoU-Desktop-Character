"""
本模块测试本机多角色 presence 通道的读写、过期与靠近判定。
"""

from __future__ import annotations

import time

from xiaou_desktop.peer import (
    DEFAULT_PEER_CONVERSATIONS,
    DIALOGUE_TURN_S,
    PeerPresence,
    arrived_beside,
    centers_near,
    clear_presence,
    dialogue_line_for_turn,
    dialogue_turn_index,
    facing_for_meetup,
    facing_toward,
    format_dialogue_line,
    horizontal_gap,
    is_dialogue_director,
    list_peers,
    read_presence,
    stand_beside_target,
    within_approach_range,
    write_presence,
)


def _presence(
    character_id: str,
    *,
    x: float,
    y: float = 100,
    width: int = 120,
    height: int = 150,
    ts: float | None = None,
    busy: bool = False,
) -> PeerPresence:
    return PeerPresence(
        character_id=character_id,
        display_name=character_id,
        x=x,
        y=y,
        width=width,
        height=height,
        facing=-1,
        busy=busy,
        ts=time.time() if ts is None else ts,
    )


def test_write_and_read_presence(tmp_path) -> None:
    me = _presence("eggdk", x=40)
    write_presence(me, directory=tmp_path)
    loaded = read_presence("eggdk", directory=tmp_path, now=time.time())
    assert loaded is not None
    assert loaded.character_id == "eggdk"
    assert loaded.x == 40


def test_stale_presence_is_offline(tmp_path) -> None:
    stale = _presence("xiaou", x=10, ts=time.time() - 5)
    write_presence(stale, directory=tmp_path)
    assert read_presence("xiaou", directory=tmp_path, max_age_s=1.5, now=time.time()) is None


def test_list_peers_excludes_self(tmp_path) -> None:
    write_presence(_presence("eggdk", x=0), directory=tmp_path)
    write_presence(_presence("xiaou", x=200), directory=tmp_path)
    peers = list_peers(exclude_id="eggdk", directory=tmp_path, now=time.time())
    assert [peer.character_id for peer in peers] == ["xiaou"]


def test_centers_near_requires_side_and_height() -> None:
    left = _presence("a", x=0, y=100, width=100)
    right = _presence("b", x=110, y=100, width=100)
    assert horizontal_gap(left, right) == 10
    assert centers_near(left, right, max_gap_px=24, max_vertical_px=28)

    far = _presence("b", x=200, y=100, width=100)
    assert not centers_near(left, far, max_gap_px=24)

    # 同一竖线大重叠：还没挪到身侧，不算到位
    stacked = _presence("b", x=10, y=100, width=100)
    assert not centers_near(left, stacked, max_gap_px=24)

    # 高度差太大也不算
    high = _presence("b", x=110, y=200, width=100)
    assert not centers_near(left, high, max_gap_px=24, max_vertical_px=28)


def test_stand_beside_aligns_height_and_splits_stack() -> None:
    me = _presence("eggdk", x=50, y=40, width=100, height=150)
    peer = _presence("xiaou", x=50, y=200, width=120, height=150)
    tx, ty, stand_left = stand_beside_target(me, peer)
    assert stand_left is True  # 几乎重叠时按 id
    assert abs(ty - (peer.center_y - me.height / 2)) < 0.1
    # 稍远并肩：约 48% 身位重叠
    expected_overlap = max(48.0, min(me.width, peer.width) * 0.48)
    assert abs(tx - (peer.x - me.width + expected_overlap)) < 0.1

    # 已在身侧且高度对齐
    beside = _presence("eggdk", x=tx, y=ty, width=100, height=150)
    assert arrived_beside(beside, peer)


def test_stand_beside_keeps_current_side() -> None:
    """本来在左/右就站哪边，不要总被赶到固定一侧。"""

    left = _presence("xiaou", x=0, width=100)
    right = _presence("eggdk", x=200, width=100)
    _tx, _ty, stand_left = stand_beside_target(left, right)
    assert stand_left is True
    _tx2, _ty2, stand_left2 = stand_beside_target(right, left)
    assert stand_left2 is False


def test_presence_keeps_approach_and_meeting_ids(tmp_path) -> None:
    me = PeerPresence(
        character_id="eggdk",
        display_name="鸡蛋壳",
        x=10,
        y=20,
        width=100,
        height=150,
        facing=1,
        busy=False,
        ts=time.time(),
        approaching_id="xiaou",
        meeting_id="",
        chat_id=2,
        chat_started_at=123.0,
        sync_action="peer_meet",
        sync_action_at=124.0,
    )
    write_presence(me, directory=tmp_path)
    loaded = read_presence("eggdk", directory=tmp_path, now=time.time())
    assert loaded is not None
    assert loaded.approaching_id == "xiaou"
    assert loaded.meeting_id == ""
    assert loaded.chat_id == 2
    assert loaded.chat_started_at == 123.0
    assert loaded.sync_action == "peer_meet"
    assert loaded.sync_action_at == 124.0


def test_dialogue_turn_is_shared_script() -> None:
    assert is_dialogue_director("eggdk", "xiaou")
    assert not is_dialogue_director("xiaou", "eggdk")
    started = 1000.0
    assert dialogue_turn_index(started, now=999.0) == -1
    assert dialogue_turn_index(started, now=1000.0) == 0
    assert dialogue_turn_index(started, now=1000.0 + DIALOGUE_TURN_S) == 1
    convo = DEFAULT_PEER_CONVERSATIONS[0]
    assert dialogue_line_for_turn(convo, 0) is not None
    assert dialogue_line_for_turn(convo, 99) is None
    spoken = format_dialogue_line("{peer}，过来。", me="鸡蛋壳", peer="小u")
    assert spoken == "小u，过来。"


def test_within_approach_range_allows_vertical_gap() -> None:
    left = _presence("a", x=0, y=0, width=100)
    high = _presence("b", x=80, y=400, width=100)
    assert within_approach_range(left, high, max_center_dist_px=1400)
    assert not within_approach_range(left, high, max_center_dist_px=100)


def test_facing_for_meetup() -> None:
    left = _presence("a", x=0, width=100)
    right = _presence("b", x=200, width=100)
    assert facing_toward(left.center_x, right.center_x) == 1
    assert facing_toward(right.center_x, left.center_x) == -1
    assert facing_for_meetup(left, right) == 1
    assert facing_for_meetup(right, left) == -1


def test_clear_presence(tmp_path) -> None:
    write_presence(_presence("eggdk", x=1), directory=tmp_path)
    clear_presence("eggdk", directory=tmp_path)
    assert read_presence("eggdk", directory=tmp_path, now=time.time()) is None
