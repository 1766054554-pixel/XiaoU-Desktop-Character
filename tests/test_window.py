"""
本模块验证桌面角色窗口的连续帧控制、扩展状态、表情符号、轮廓遮罩、DPI 渲染缓存、分区互动、换装和自拍成片。

测试在 Qt 的离屏平台中创建真实 PetWindow，但不显示到用户桌面、不写配置文件，
也不启动系统托盘。重点检查透明区域不会形成完整矩形点击区、重复绘制能够复用缓存，
以及坐下过渡可正向停在末帧并反向回到站立帧。
"""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONEPIC_USE_DEMO_ASSETS", "1")

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar

from xiaou_desktop.behavior import PetState, StateDecision
from xiaou_desktop.config import PetSettings
from xiaou_desktop.emotion_effects import emotion_effect_name
from xiaou_desktop.window import (
    SPEECH_LINES,
    STATE_SPEECH_LINES,
    PetWindow,
)


def _create_window() -> tuple[QApplication, PetWindow]:
    """创建或复用离屏 Qt 应用，并返回采用默认设置的角色窗口。"""

    app = QApplication.instance() or QApplication([])
    window = PetWindow(PetSettings())
    window.show()
    app.processEvents()
    return app, window


def test_window_uses_character_mask_and_reuses_render_cache() -> None:
    app, window = _create_window()
    initial_render_count = len(window._render_cache)
    initial_mask_count = len(window._mask_cache)

    window._refresh_pixmap()

    assert not window.mask().isEmpty()
    assert window.mask().boundingRect().width() < window.width()
    assert len(window._render_cache) == initial_render_count
    assert len(window._mask_cache) == initial_mask_count
    window.close()
    window.deleteLater()
    app.processEvents()


def test_macos_tool_windows_stay_visible_when_app_loses_focus() -> None:
    """macOS 点击桌面或其他应用时不应自动隐藏人物与独立气泡。"""

    app, window = _create_window()
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    if sys.platform == "darwin":
        attribute = Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow
        assert window.testAttribute(attribute)
        assert window.photo_bubble.testAttribute(attribute)
        assert window.speech_bubble.testAttribute(attribute)
    window.close()
    window.deleteLater()
    app.processEvents()


def test_sit_animation_holds_then_reverses_to_standing_frame() -> None:
    app, window = _create_window()
    window.set_state(PetState.SIT)

    for _ in range(len(window._pixmaps[PetState.SIT])):
        window._animation_tick()

    assert window._frame_index == len(window._pixmaps[PetState.SIT]) - 1
    assert not window.animation_timer.isActive()

    window._reverse_transition_to_idle()
    for _ in range(len(window._pixmaps[PetState.SIT]) - 1):
        window._animation_tick()

    assert window._frame_index == 0
    assert not window.animation_timer.isActive()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_walk_pauses_briefly_when_turning_at_screen_edge() -> None:
    app, window = _create_window()
    window.set_state(PetState.WALK)
    window.direction = -1
    window._frame_index = 3
    window.move(0, 0)
    window._screen_geometry = lambda: QRect(0, 0, 1000, 1000)

    window._movement_tick()

    assert window.direction == 1
    assert window._turn_paused
    assert window.turn_timer.isActive()
    assert not window.animation_timer.isActive()

    window._finish_turn()

    assert not window._turn_paused
    assert window.animation_timer.isActive()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_pixel_walk_keeps_sprite_baseline_stable() -> None:
    """像素走路帧已自带身体起伏，窗口层不应再叠加垂直抖动。"""

    app, window = _create_window()
    window.set_state(PetState.WALK)
    offsets = [window.label.y()]

    for _ in range(3):
        window._animation_tick()
        offsets.append(window.label.y())

    assert offsets == [0, 0, 0, 0]
    window.close()
    window.deleteLater()
    app.processEvents()


def test_walk_uses_subpixel_phase_synced_speed(monkeypatch) -> None:
    """水平移动应亚像素累计，落脚阶段减速而不冻结，随后平滑加速。"""

    app, window = _create_window()
    window.set_state(PetState.WALK)
    window.direction = 1
    window.move(100, 0)
    window._movement_x = 100.0
    window._last_movement_at = 10.0
    window._screen_geometry = lambda: QRect(0, 0, 1000, 1000)
    current_time = [10.016]
    monkeypatch.setattr(
        "xiaou_desktop.window.time.monotonic",
        lambda: current_time[0],
    )

    window._frame_index = 0
    window._movement_tick()
    assert round(window._movement_x, 2) == 100.8
    assert window.x() == 101

    current_time[0] = 10.032
    window._frame_index = 3
    window._movement_tick()
    assert window._movement_speed_pixels_per_second() == 62.5
    assert round(window._movement_x, 2) == 101.8
    assert window.x() == 102
    window.close()
    window.deleteLater()
    app.processEvents()


def test_walk_motion_curve_avoids_freeze_and_balances_both_steps() -> None:
    """移动曲线不应停顿后猛跳，且左右两个半步必须使用相同节奏。"""

    app, window = _create_window()

    assert min(window._walk_motion_factors) > 0.0
    assert max(window._walk_motion_factors) / min(window._walk_motion_factors) < 4
    assert window._walk_motion_factors[:6] == window._walk_motion_factors[6:]
    assert sum(window._walk_motion_factors) / 12 == 1.0

    window.close()
    window.deleteLater()
    app.processEvents()


def test_drag_state_uses_dedicated_suspended_animation() -> None:
    """拖拽状态应加载三帧悬空素材，而不是回退到待机站立。"""

    app, window = _create_window()
    window.set_state(PetState.DRAG)

    display_state, _pixmap = window._current_source()
    assert display_state is PetState.DRAG
    assert len(window._pixmaps[PetState.DRAG]) == 3
    assert window.animation_timer.isActive()
    assert window.mask().boundingRect() == window.rect()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_mouse_press_opens_full_region_before_macos_starts_dragging() -> None:
    """按下瞬间就应移除旧轮廓，避免 macOS 缓存后裁掉拖拽姿态。"""

    app, window = _create_window()
    assert window.mask().boundingRect() != window.rect()
    event = Mock()
    event.button.return_value = Qt.MouseButton.LeftButton
    event.position.return_value = QPointF(30, 40)
    event.globalPosition.return_value = QPointF(window.x() + 30, window.y() + 40)

    window.mousePressEvent(event)

    assert window.mask().boundingRect() == window.rect()
    assert window._press_pending
    window.close()
    window.deleteLater()
    app.processEvents()


def test_interaction_states_have_reusable_emotion_symbols() -> None:
    """互动表情应使用独立符号层，换角色素材后仍然能够显示。"""

    expected = {
        PetState.HAPPY: "sparkle",
        PetState.SHY: "heart",
        PetState.SURPRISED: "exclamation",
        PetState.ANNOYED: "anger",
        PetState.SLEEPY: "sleep",
        PetState.CURIOUS: "question",
        PetState.SELFIE: "flash",
    }
    assert {state: emotion_effect_name(state) for state in expected} == expected
    assert emotion_effect_name(PetState.IDLE) is None
    assert emotion_effect_name(PetState.DRAG) is None


def test_emotion_symbol_timer_follows_current_state() -> None:
    """进入表情状态时符号应动画，恢复待机后必须停止计时器。"""

    app, window = _create_window()
    window.set_state(PetState.SURPRISED)
    assert window.effect_timer.isActive()
    assert not window.label.pixmap().isNull()

    window.set_state(PetState.IDLE)
    assert not window.effect_timer.isActive()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_inactivity_progresses_from_sit_to_sleep() -> None:
    """超过睡眠阈值后仍应先完整坐下，再播放坐姿入睡序列。"""

    settings = PetSettings(inactive_sit_ms=10000, inactive_sleep_ms=20000)
    app = QApplication.instance() or QApplication([])
    window = PetWindow(settings)
    window._last_user_interaction = time.monotonic() - 21
    window.set_state(PetState.IDLE)

    window._state_timeout()
    assert window.state is PetState.SIT
    assert window._sleep_after_sit

    window._state_timeout()
    assert window.state is PetState.SLEEP
    assert not window._sleep_after_sit
    window.close()
    window.deleteLater()
    app.processEvents()


def test_pause_disables_running_but_keeps_ambient_state_timer() -> None:
    """暂停跑动时应进入生活状态并继续计时，而不是冻结在站立帧。"""

    app, window = _create_window()
    window.set_state(PetState.WALK)
    window.behavior.next_autonomous_state = (
        lambda _current, allow_walk, mood=None: StateDecision(PetState.SIT, 2000)
    )

    window.set_paused(True)

    assert window.paused
    assert window.state is PetState.SIT
    assert window.state_timer.isActive()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_display_size_preset_updates_geometry_and_settings() -> None:
    """右键尺寸预设应立即改变窗口和标签尺寸，并写回设置对象。"""

    app, window = _create_window()
    window.set_display_height(280)

    assert window.settings.display_height == 280
    assert window.height() == 294
    assert window.label.height() == 288
    assert not window.mask().isEmpty()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_interaction_zones_map_head_face_body_and_camera() -> None:
    """窗口相对位置应稳定映射为四种点击区域。"""

    app, window = _create_window()
    center_x = window.label.x() + window.label.width() // 2
    assert window._interaction_zone(QPoint(center_x, 20)) == "head"
    assert (
        window._interaction_zone(
            QPoint(center_x, round(window.label.height() * 0.34))
        )
        == "face"
    )
    assert (
        window._interaction_zone(
            QPoint(
                window.label.x() + round(window.label.width() * 0.2),
                round(window.label.height() * 0.62),
            )
        )
        == "camera"
    )
    assert (
        window._interaction_zone(
            QPoint(center_x, round(window.label.height() * 0.7))
        )
        == "body"
    )
    window.close()
    window.deleteLater()
    app.processEvents()


def test_head_click_increases_affinity_and_body_click_opens_action_panel() -> None:
    """摸头应触发享受反馈，点击身体应打开可见的状态与动作面板。"""

    app, window = _create_window()
    initial_affinity = window.mood.affinity
    head = QPoint(window.width() // 2, 20)
    body = QPoint(window.width() // 2, round(window.label.height() * 0.7))

    window._handle_click(head)
    assert window.mood.affinity == initial_affinity + 5
    assert window.state is PetState.ENJOY

    opened_at = []
    window._show_action_menu = lambda point: opened_at.append(point)
    window._handle_click(body)
    assert len(opened_at) == 1
    window.close()
    window.deleteLater()
    app.processEvents()


def test_selfie_completion_shows_photo_bubble() -> None:
    """没有用户原图时不得用生成动画末帧冒充自拍照片。"""

    app, window = _create_window()
    window._selfie_photo = type(window._selfie_photo)()
    window.set_state(PetState.SELFIE)
    window._finish_interaction()
    app.processEvents()

    assert not window.photo_bubble.isVisible()
    window.photo_bubble.hide()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_selfie_photo_uses_high_dpi_backing_pixels() -> None:
    """200% 缩放时横竖照片都应使用高分辨率像素并限制逻辑尺寸。"""

    app, window = _create_window()
    window._selfie_photo = window._pixmaps[PetState.SELFIE][-1]
    photo = window._scaled_selfie_photo(2.0)

    assert photo.devicePixelRatio() == 2.0
    assert max(photo.width(), photo.height()) >= 300
    assert round(photo.width() / photo.devicePixelRatio()) <= 150
    assert round(photo.height() / photo.devicePixelRatio()) <= 210
    window.close()
    window.deleteLater()
    app.processEvents()


def test_selfie_photo_is_positioned_near_visible_character() -> None:
    """照片应贴近人物不透明轮廓，而不是贴着含大块留白的窗口边缘。"""

    app, window = _create_window()
    window._selfie_photo = window._pixmaps[PetState.SELFIE][-1]
    window.move(500, 300)
    window._screen_geometry = lambda: QRect(0, 0, 1200, 900)
    window.set_state(PetState.SELFIE)
    window._show_photo_bubble()
    app.processEvents()

    character_left = window.x() + window.mask().boundingRect().left()
    visual_gap = character_left - (
        window.photo_bubble.x() + window.photo_bubble.width()
    )
    assert visual_gap == 8
    window.photo_bubble.hide()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_random_speech_uses_local_lines_and_follows_character(monkeypatch) -> None:
    """对白应从预设语句中随机出现，并在人物移动时同步跟随。"""

    app, window = _create_window()
    monkeypatch.setattr(
        "xiaou_desktop.window.random.choice",
        lambda values: values[0],
    )
    window._show_random_speech()
    app.processEvents()

    assert window.speech_bubble.text() == SPEECH_LINES[0]
    assert window.speech_bubble.isVisible()
    assert window.speech_hide_timer.isActive()
    assert window.speech_timer.isActive()
    assert window.speech_bubble.testAttribute(
        Qt.WidgetAttribute.WA_TranslucentBackground
    )
    bubble_image = window.speech_bubble.grab().toImage()
    assert bubble_image.pixelColor(0, 0).alpha() == 0
    assert bubble_image.pixelColor(5, bubble_image.height() // 2).alpha() > 0
    original_position = window.speech_bubble.pos()

    window.move(window.x() - 40, window.y() - 20)
    app.processEvents()

    assert window.speech_bubble.pos() != original_position
    window.close()
    window.deleteLater()
    app.processEvents()


def test_action_menu_can_trigger_random_and_contextual_speech(monkeypatch) -> None:
    """动作面板应能主动说话，固定动作也应带对应的随机对白。"""

    app, window = _create_window()
    monkeypatch.setattr(
        "xiaou_desktop.window.random.choice",
        lambda values: values[0],
    )
    menu = window._build_context_menu()
    root_labels = [action.text() for action in menu.actions()]
    assert "听小u说句话" in root_labels
    assert "关闭小u说话" in root_labels
    assert "和小u打招呼" in root_labels
    assert "小u大小" in root_labels
    assert all("角色" not in label for label in root_labels)

    window.trigger_state(PetState.WAVE)
    assert window.speech_bubble.text() == "hiii，大家好呀"

    menu.deleteLater()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_speech_toggle_hides_bubble_stops_timer_and_persists_setting() -> None:
    """关闭说话后，自动对白、动作对白和当前气泡都应停止。"""

    app, window = _create_window()
    window._show_speech(("测试对白",))
    assert window.speech_bubble.isVisible()

    window.set_speech_enabled(False)

    assert not window.settings.speech_enabled
    assert not window.speech_timer.isActive()
    assert not window.speech_bubble.isVisible()
    window.trigger_state(PetState.WAVE)
    assert not window.speech_bubble.isVisible()
    assert "开启小u说话" in [
        action.text() for action in window._build_context_menu().actions()
    ]
    window.close()
    window.deleteLater()
    app.processEvents()


def test_passive_mood_progress_updates_at_most_once_per_interval(monkeypatch) -> None:
    """自然情绪进度最多每 30 秒更新一次，主动互动仍可立即变化。"""

    app, window = _create_window()
    clock = [100.0]
    monkeypatch.setattr("xiaou_desktop.window.time.monotonic", lambda: clock[0])
    window._last_mood_update_at = clock[0]
    initial = (window.mood.energy, window.mood.boredom, window.mood.hunger)

    window._update_mood_if_due()
    clock[0] += 29
    window._update_mood_if_due()
    assert (window.mood.energy, window.mood.boredom, window.mood.hunger) == initial

    clock[0] += 1
    window._update_mood_if_due()
    assert (window.mood.energy, window.mood.boredom, window.mood.hunger) != initial
    window.close()
    window.deleteLater()
    app.processEvents()


def test_public_experience_hides_intimate_actions_and_original_photo(
    monkeypatch,
) -> None:
    """公开角色移除亲昵动作入口，自拍不显示原图，随机姿态使用普通对白。"""

    app = QApplication.instance() or QApplication([])
    window = PetWindow(PetSettings())
    window.show()
    app.processEvents()
    monkeypatch.setattr(
        "xiaou_desktop.window.random.choice",
        lambda values: values[0],
    )
    menu = window._build_context_menu()
    labels = []
    for action in menu.actions():
        labels.append(action.text())
        if action.menu() is not None:
            labels.extend(child.text() for child in action.menu().actions())

    assert "表情与互动" in labels
    assert "发送亲亲" not in labels
    assert "张手等抱抱" not in labels
    assert "正面害羞" not in labels
    assert "小皇帝" in labels
    assert "小皇帝等人哄" not in labels
    assert "自拍" in labels
    assert "自拍并显示真人原图" not in labels

    window.mood.affinity = 100
    window.trigger_interaction()
    assert window.state is PetState.HUG
    assert window.speech_bubble.text() == "伸个大大的懒腰"
    window.set_state(PetState.SELFIE)
    window._finish_interaction()
    assert not window.photo_bubble.isVisible()

    public_text = "".join(SPEECH_LINES) + "".join(
        line
        for lines in STATE_SPEECH_LINES.values()
        for line in lines
    )
    assert not any(
        word in public_text
        for word in ("喜欢", "想你", "亲亲", "抱抱", "贴贴", "害羞", "哄")
    )
    menu.deleteLater()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_local_interaction_pack_can_add_custom_actions_and_dialogue(monkeypatch) -> None:
    """本地定制包可以加入专属动作入口和对白，不改变公开默认体验。"""

    app, window = _create_window()
    window._custom_menu_actions = (("发送啵啵", PetState.KISS, 2200),)
    window._custom_state_speech = {PetState.KISS: ("啵啵送达",)}
    monkeypatch.setattr("xiaou_desktop.window.random.choice", lambda values: values[-1])

    menu = window._build_context_menu()
    labels = []
    for action in menu.actions():
        if action.menu() is not None:
            labels.extend(child.text() for child in action.menu().actions())
    assert "发送啵啵" in labels

    window.trigger_state(PetState.KISS)
    assert window.speech_bubble.text() == "啵啵送达"

    menu.deleteLater()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_extended_states_load_with_demo_fallbacks_and_effects() -> None:
    """公开演示素材缺少新图片时也应覆盖全部扩展状态并保留符号层。"""

    app, window = _create_window()

    assert set(window._pixmaps) == set(PetState)
    assert emotion_effect_name(PetState.CAMERA) == "flash"
    assert emotion_effect_name(PetState.OUTFIT) == "flash"

    window.close()
    window.deleteLater()
    app.processEvents()


def test_food_and_outfit_actions_update_mood_and_state() -> None:
    """吃汉堡应降低饥饿度，换装应生成转圈加随机造型的两段状态。"""

    app, window = _create_window()
    window.mood.hunger = 90

    window.trigger_food(PetState.BURGER)
    assert window.state is PetState.BURGER
    assert window.mood.hunger == 42

    window.trigger_outfit_change()
    assert window.state is PetState.OUTFIT
    assert len(window._pixmaps[PetState.OUTFIT]) >= 2
    assert window.interaction_timer.isActive()

    window.close()
    window.deleteLater()
    app.processEvents()


def test_context_menu_exposes_new_interactions_and_hunger() -> None:
    """右键菜单应提供食物、柯基、拍照、摸鱼和换装入口。"""

    app, window = _create_window()
    menu = window._build_context_menu()
    labels = []
    for action in menu.actions():
        labels.append(action.text())
        submenu = action.menu()
        if submenu is not None:
            labels.extend(child.text() for child in submenu.actions())

    assert "吃蛋糕满足" in labels
    assert "大口吃汉堡" in labels
    assert "陪柯基玩" in labels
    assert "拿相机拍照" in labels
    assert "坐椅子电脑摸鱼" in labels
    assert "随机换装" in labels
    assert "摸摸柯基" not in labels
    assert [bar.value() for bar in menu.findChildren(QProgressBar)] == [
        window.mood.affinity,
        window.mood.energy,
        window.mood.boredom,
        window.mood.hunger,
    ]
    assert any("饥饿" in label.text() for label in menu.findChildren(QLabel))

    menu.deleteLater()
    window.close()
    window.deleteLater()
    app.processEvents()
