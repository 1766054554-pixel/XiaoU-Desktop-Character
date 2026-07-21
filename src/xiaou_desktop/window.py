"""
本模块实现桌面角色的透明窗口、连续动画、鼠标交互和自主移动。

职责范围：
- 创建无边框、透明、可选始终置顶的 QWidget；
- 在 macOS 应用失去焦点时仍保持人物与气泡可见；
- 播放循环或单次 PNG 序列，并支持拖拽、坐下、坐姿入睡和反向起身；
- 处理左右翻转、边缘转身停顿、亚像素时间驱动移动和同步身体起伏；
- 用窗口遮罩让人物外透明区域穿透鼠标点击；
- 缓存不同 DPI 下的缩放帧，并在窗口跨显示器后按新比例重新栅格化；
- 支持左键拖动、双击互动、无互动分级休息、丰富互动菜单和随机换装；
- 支持头部摸动、脸部/身体/相机分区点击、悬停注视、左键动作面板和拖拽后表情；
- 定时显示只在本机绘制的随机对白气泡，并在人物移动时同步跟随；
- 支持自然日常对白以及与动作情境匹配的气泡文字；
- 自动触发嘟嘴、大笑、享受、难过、无聊、饥饿、思考、困倦、手机和 Wink；
- 通过与角色素材解耦的矢量图层增强闪光、爱心、惊讶、生气、困倦、疑惑、自拍、换装和拖拽反馈；
- 优先从用户私有素材目录显示自拍成片气泡，按当前屏幕 DPI 保持清晰度，并贴近人物真实轮廓定位；
- 标准角色确认后加载本地角色供现场验收；走路确认仍作为打包门禁；
- 维护默契、精力、无聊度与饥饿度的会话内状态；
- 使用 QTimer 驱动状态切换及水平移动，并限制窗口不脱离当前屏幕。

Agent 快速定位：
- 窗口初始化和计时器设置位于 PetWindow.__init__()；
- 状态显示入口位于 set_state()，高 DPI 重绘位于 _refresh_pixmap()；
- 自动移动位于 _movement_tick()；
- 鼠标事件位于 mousePressEvent() 等 Qt 事件方法；
- 退出由 quit_requested 信号交给应用生命周期模块处理。

输入为 PetSettings、素材清单和可选的用户自拍照片资源，输出为可交互的 Qt 窗口。
本模块不写配置文件、不启动独立线程、不访问网络；位置持久化由 app.py 在退出时完成。
`user_assets/` 默认不进入 Git；只有用户主动放入的自拍图片才会在本机显示。
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import ctypes
from collections import OrderedDict, deque
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCloseEvent,
    QContextMenuEvent,
    QCursor,
    QHideEvent,
    QMouseEvent,
    QMoveEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPixmap,
    QRegion,
    QScreen,
    QShowEvent,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QWidget,
    QWidgetAction,
)

from .behavior import BehaviorModel, PetMood, PetState, StateDecision
from .config import PetSettings
from .emotion_effects import draw_emotion_effect, emotion_effect_name
from .resources import resource_path
from .workflow import WorkflowError, character_is_approved, load_workflow


DEFAULT_WALK_MOTION_FACTORS = (0.45, 0.7, 1.2, 1.65, 0.45, 0.7, 1.2, 1.65)

ONE_SHOT_STATES = {
    PetState.SIT,
    PetState.SLEEP,
    PetState.SELFIE,
    PetState.OUTFIT,
}

BOBBING_STATES = {
    PetState.IDLE,
    PetState.HAPPY,
    PetState.SHY,
    PetState.SURPRISED,
    PetState.ANNOYED,
    PetState.SLEEPY,
    PetState.CURIOUS,
    PetState.POUT,
    PetState.LAUGH,
    PetState.ENJOY,
    PetState.KISS,
    PetState.SAD,
    PetState.BORED,
    PetState.HUNGRY,
    PetState.THINKING,
    PetState.WAKE,
    PetState.WINK,
    PetState.STARRY,
    PetState.HUG,
    PetState.SHY_FRONT,
}

STATE_LABELS = {
    PetState.IDLE: "安静待机",
    PetState.WALK: "散步中",
    PetState.SIT: "坐下来",
    PetState.SLEEP: "乖乖睡觉",
    PetState.WAVE: "挥手问好",
    PetState.HAPPY: "开心",
    PetState.SHY: "有点不好意思",
    PetState.SURPRISED: "有点惊讶",
    PetState.ANNOYED: "正在生气",
    PetState.SLEEPY: "困困的",
    PetState.CURIOUS: "好奇",
    PetState.SELFIE: "自拍中",
    PetState.DRAG: "被抓住啦",
    PetState.POUT: "嘟嘴",
    PetState.LAUGH: "大笑",
    PetState.ENJOY: "闭眼享受",
    PetState.KISS: "互动",
    PetState.SAD: "有点难过",
    PetState.BORED: "无聊等待",
    PetState.HUNGRY: "肚子饿了",
    PetState.THINKING: "陷入思考",
    PetState.WAKE: "刚刚醒来",
    PetState.CAKE: "吃蛋糕",
    PetState.PHONE_GIGGLE: "玩手机傻笑",
    PetState.WINK: "Wink",
    PetState.WORK: "电脑摸鱼",
    PetState.CORGI_PET: "陪柯基玩",
    PetState.CORGI_PLAY: "陪柯基玩",
    PetState.STARRY: "星星眼",
    PetState.BURGER: "吃汉堡",
    PetState.CAMERA: "拍照中",
    PetState.EMPEROR: "小皇帝模式",
    PetState.HUG: "伸懒腰",
    PetState.SHY_FRONT: "有点不好意思",
    PetState.OUTFIT: "换装中",
}

SPEECH_LINES = (
    "今天吃什么好呢？",
    "小u要工作工作...",
    "摸鱼ing",
    "和小哈一起玩耶",
    "今天也要开开心心！",
    "休息一下再继续吧～",
    "小u正在发呆...",
    "外面天气怎么样呀",
    "记得喝水哦",
    "小u巡逻中！",
    "发现一件有趣的事",
    "今天也要元气满满",
    "先伸个懒腰～",
    "忙完记得休息一下",
    "小哈今天也很乖",
    "来看看小u的新衣服！",
)

STATE_SPEECH_LINES = {
    PetState.WAVE: ("hiii，大家好呀", "嗨嗨，今天过得怎么样？"),
    PetState.HAPPY: ("今天心情真不错！", "开心的一天开始啦"),
    PetState.POUT: ("哼，让小u安静一下", "暂时不想说话啦"),
    PetState.LAUGH: ("哈哈哈太好玩了", "笑得停不下来啦"),
    PetState.ENJOY: ("休息一下真舒服～", "慢下来放松一会儿"),
    PetState.WINK: ("wink～今天也要开心", "小u悄悄眨个眼"),
    PetState.STARRY: ("哇，亮晶晶的！", "发现了闪闪发光的东西"),
    PetState.HUG: ("伸个大大的懒腰", "活动一下肩膀"),
    PetState.SHY_FRONT: ("突然有点不好意思", "先安静一小会儿"),
    PetState.SURPRISED: ("呀！吓小u一跳", "诶？发生什么啦"),
    PetState.SAD: ("今天有一点低落", "休息一下就会好起来"),
    PetState.BORED: ("有点无聊，找点事做吧", "已经发呆好久啦"),
    PetState.HUNGRY: ("小u饿饿啦", "今天吃什么好呢？"),
    PetState.ANNOYED: ("哼！小u生气啦", "先让小u冷静一下"),
    PetState.THINKING: ("小脑瓜正在转呀转", "嗯...让我想想"),
    PetState.SLEEPY: ("眼睛要睁不开啦", "小u困困..."),
    PetState.SLEEP: ("晚安，明天见", "小u乖乖睡觉啦"),
    PetState.WAKE: ("早呀！小u醒啦", "睡饱啦，元气满满！"),
    PetState.CAKE: ("蛋糕好好吃，满足～", "下午茶时间到！"),
    PetState.BURGER: ("嗷呜！大口吃汉堡", "吃饱饱才有力气"),
    PetState.PHONE_GIGGLE: ("嘿嘿看到好玩的啦", "刷到一件有趣的事"),
    PetState.WORK: ("小u要工作工作...", "摸鱼ing，嘘～"),
    PetState.CORGI_PLAY: ("和小哈一起玩耶", "小哈的小爪爪好可爱！"),
    PetState.CAMERA: ("看镜头，笑一个～", "咔嚓！记录一下"),
    PetState.SELFIE: ("拍张照片吧", "咔嚓！动作完成"),
    PetState.EMPEROR: ("今天也要气场全开", "小u正在认真坐镇"),
    PetState.OUTFIT: ("来看看小u的新衣服！", "今天穿这套怎么样？"),
}


class SpeechBubble(QLabel):
    """绘制四角透明的浅粉圆角对白气泡。"""

    def paintEvent(self, event: QPaintEvent) -> None:
        """先绘制圆角底与细边框，再交给 QLabel 绘制文字。"""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(231, 169, 191, 245), 1.0))
        painter.setBrush(QColor(255, 249, 251, 248))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)
        painter.end()
        super().paintEvent(event)


def _configure_macos_window_for_all_spaces(widget: QWidget) -> bool:
    """让 Cocoa 顶层窗口跨桌面空间常驻，并在应用失焦时保持显示。"""

    if sys.platform != "darwin" or QApplication.platformName() != "cocoa":
        return False
    try:
        objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        message_address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        if message_address is None:
            return False
        send_object = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(message_address)
        send_integer = ctypes.CFUNCTYPE(
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(message_address)
        set_integer = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
        )(message_address)
        set_bool = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_bool,
        )(message_address)
        selector = lambda name: ctypes.c_void_p(objc.sel_registerName(name))
        native_view = ctypes.c_void_p(int(widget.winId()))
        native_window = send_object(native_view, selector(b"window"))
        if not native_window:
            return False
        behavior_selector = selector(b"collectionBehavior")
        current_behavior = send_integer(native_window, behavior_selector)
        # CanJoinAllSpaces | Stationary | FullScreenAuxiliary
        behavior = (current_behavior & ~(1 << 1)) | (1 << 0) | (1 << 4) | (1 << 8)
        set_integer(
            native_window,
            selector(b"setCollectionBehavior:"),
            behavior,
        )
        set_bool(native_window, selector(b"setHidesOnDeactivate:"), False)
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


class PetWindow(QWidget):
    """显示并控制单个桌面角色的透明顶层窗口。"""

    quit_requested = Signal()
    pause_changed = Signal(bool)

    def __init__(self, settings: PetSettings) -> None:
        super().__init__()
        self.settings = settings
        self.behavior = BehaviorModel(settings)
        self.mood = PetMood()
        self.state = PetState.IDLE
        self.direction = -1
        self._movement_x = float(self.x())
        self._last_movement_at = time.monotonic()
        self.paused = False
        self.dragging = False
        self._press_pending = False
        self._press_local = QPoint()
        self._press_global = QPoint()
        self._drag_offset = QPoint()
        self._hover_zone = ""
        self._stroke_points: deque[tuple[float, QPoint]] = deque()
        self._last_stroke_reaction = 0.0
        self._bob_phase = False
        self._effect_phase = 0
        self._frame_index = 0
        self._animation_direction = 1
        self._animation_finished: Callable[[], None] | None = None
        self._turn_paused = False
        self._last_user_interaction = time.monotonic()
        self._last_mood_update_at = time.monotonic()
        self._sleep_after_sit = False
        self._active_context_menu: QMenu | None = None
        self._screen_change_connected = False
        self._connected_screen: QScreen | None = None
        (
            self._custom_speech_lines,
            self._custom_state_speech,
            self._custom_menu_actions,
        ) = self._load_interaction_pack()
        self._pixmaps = self._load_pixmaps()
        self._selfie_photo = self._load_selfie_photo()
        self._render_cache: OrderedDict[tuple[object, ...], QPixmap] = OrderedDict()
        self._mask_cache: OrderedDict[tuple[object, ...], QRegion] = OrderedDict()

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if sys.platform == "darwin":
            self.setAttribute(
                Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow,
                True,
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle("小u")
        self.setMouseTracking(True)

        source = self._pixmaps[PetState.IDLE][0]
        width = round(settings.display_height * source.width() / source.height())
        self.setFixedSize(width + 12, settings.display_height + 14)
        self.label = QLabel(self)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setGeometry(6, 0, width, settings.display_height + 8)

        self.photo_bubble = QLabel()
        self.photo_bubble.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        if sys.platform == "darwin":
            self.photo_bubble.setAttribute(
                Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow,
                True,
            )
        self.photo_bubble.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            True,
        )
        self.photo_bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_bubble.setStyleSheet("background: transparent;")

        self.speech_bubble = SpeechBubble()
        self.speech_bubble.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        if sys.platform == "darwin":
            self.speech_bubble.setAttribute(
                Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow,
                True,
            )
        self.speech_bubble.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            True,
        )
        self.speech_bubble.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        self.speech_bubble.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self.speech_bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speech_bubble.setContentsMargins(11, 8, 11, 8)
        self.speech_bubble.setStyleSheet(
            "QLabel { background: transparent; color: #28354a; "
            "border: none; font-size: 13px; }"
        )

        self.movement_timer = QTimer(self)
        self.movement_timer.setInterval(settings.movement_interval_ms)
        self.movement_timer.timeout.connect(self._movement_tick)
        self.movement_timer.start()

        self.state_timer = QTimer(self)
        self.state_timer.setSingleShot(True)
        self.state_timer.timeout.connect(self._state_timeout)

        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._animation_tick)

        self.turn_timer = QTimer(self)
        self.turn_timer.setSingleShot(True)
        self.turn_timer.timeout.connect(self._finish_turn)

        self.interaction_timer = QTimer(self)
        self.interaction_timer.setSingleShot(True)
        self.interaction_timer.timeout.connect(self._finish_interaction)

        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self._trigger_hover_curiosity)

        self.photo_timer = QTimer(self)
        self.photo_timer.setSingleShot(True)
        self.photo_timer.timeout.connect(self.photo_bubble.hide)

        self.speech_timer = QTimer(self)
        self.speech_timer.setSingleShot(True)
        self.speech_timer.timeout.connect(self._show_random_speech)

        self.speech_hide_timer = QTimer(self)
        self.speech_hide_timer.setSingleShot(True)
        self.speech_hide_timer.timeout.connect(self.speech_bubble.hide)

        self.effect_timer = QTimer(self)
        self.effect_timer.setInterval(90)
        self.effect_timer.timeout.connect(self._effect_tick)

        self.bob_timer = QTimer(self)
        self.bob_timer.setInterval(280)
        self.bob_timer.timeout.connect(self._bob_tick)
        self.bob_timer.start()

        self.set_state(PetState.IDLE)
        self._schedule(self.behavior.initial_idle())
        self._schedule_next_speech(initial=True)

    def _load_interaction_pack(
        self,
    ) -> tuple[
        tuple[str, ...],
        dict[PetState, tuple[str, ...]],
        tuple[tuple[str, PetState, int], ...],
    ]:
        """Load an optional local action and dialogue pack with strict limits."""

        try:
            pack_path = resource_path("user_assets/interaction_pack.json")
        except FileNotFoundError:
            return (), {}, ()
        data = json.loads(pack_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("本地互动包必须是 JSON 对象")

        def clean_lines(value: object) -> tuple[str, ...]:
            if not isinstance(value, list):
                return ()
            return tuple(
                line.strip()
                for line in value[:80]
                if isinstance(line, str) and 0 < len(line.strip()) <= 60
            )

        state_by_name = {state.value: state for state in PetState}
        state_speech: dict[PetState, tuple[str, ...]] = {}
        raw_state_speech = data.get("state_speech", {})
        if isinstance(raw_state_speech, dict):
            for name, raw_lines in raw_state_speech.items():
                state = state_by_name.get(str(name))
                lines = clean_lines(raw_lines)
                if state is not None and lines:
                    state_speech[state] = lines

        menu_actions: list[tuple[str, PetState, int]] = []
        raw_actions = data.get("menu_actions", [])
        if isinstance(raw_actions, list):
            for raw_action in raw_actions[:16]:
                if not isinstance(raw_action, dict):
                    continue
                label = str(raw_action.get("label", "")).strip()
                state = state_by_name.get(str(raw_action.get("state", "")))
                if not label or len(label) > 20 or state is None:
                    continue
                duration_ms = min(8000, max(500, int(raw_action.get("duration_ms", 2200))))
                menu_actions.append((label, state, duration_ms))

        return clean_lines(data.get("speech_lines", [])), state_speech, tuple(menu_actions)

    def _load_pixmaps(self) -> dict[PetState, list[QPixmap]]:
        """根据素材清单加载各状态帧序列并验证完整性。"""

        manifest_path = resource_path("assets/pet/manifest.json")
        if os.environ.get("ONEPIC_USE_DEMO_ASSETS") == "1":
            return self._load_manifest_pixmaps(manifest_path)
        try:
            custom_manifest = resource_path("user_assets/pet/manifest.json")
        except FileNotFoundError:
            pass
        else:
            if not character_is_approved(load_workflow()):
                raise WorkflowError(
                    "检测到私有角色素材，但标准人物尚未确认；拒绝静默回退到演示角色。"
                )
            manifest_path = custom_manifest
        return self._load_manifest_pixmaps(manifest_path)

    def _load_manifest_pixmaps(
        self,
        manifest_path: Path,
    ) -> dict[PetState, list[QPixmap]]:
        """从指定清单加载帧；测试可借此固定使用公开演示素材。"""

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        animations: dict[str, list[str]] = manifest["animations"]
        self._pixel_art = bool(manifest.get("pixel_art", False))
        self._walk_frame_interval_ms = int(
            manifest.get("walk_frame_interval_ms", self.settings.walk_frame_interval_ms)
        )
        motion_factors = manifest.get(
            "walk_motion_factors",
            DEFAULT_WALK_MOTION_FACTORS,
        )
        if len(motion_factors) != len(animations["walk"]):
            raise ValueError("走路位移曲线必须与走路动画帧数一致")
        self._walk_motion_factors = tuple(float(value) for value in motion_factors)

        def paths_for(name: str, fallback: str) -> list[str]:
            """优先使用新状态素材，公开演示清单缺少时回退到相近旧状态。"""

            return animations.get(name, animations[fallback])

        mapping = {
            PetState.IDLE: animations["idle"],
            PetState.WALK: animations["walk"],
            PetState.SIT: animations["sit"],
            PetState.SLEEP: animations["sleep"],
            PetState.WAVE: animations["wave"],
            PetState.HAPPY: animations["happy"],
            PetState.SHY: animations["shy"],
            PetState.SURPRISED: animations["surprised"],
            PetState.ANNOYED: animations["annoyed"],
            PetState.SLEEPY: animations["sleepy"],
            PetState.CURIOUS: animations["curious"],
            PetState.SELFIE: animations["selfie"],
            PetState.DRAG: animations["drag"],
            PetState.POUT: paths_for("pout", "shy"),
            PetState.LAUGH: paths_for("laugh", "happy"),
            PetState.ENJOY: paths_for("enjoy", "happy"),
            PetState.KISS: paths_for("kiss", "shy"),
            PetState.SAD: paths_for("sad", "shy"),
            PetState.BORED: paths_for("bored", "curious"),
            PetState.HUNGRY: paths_for("hungry", "curious"),
            PetState.THINKING: paths_for("thinking", "curious"),
            PetState.WAKE: paths_for("wake", "idle"),
            PetState.CAKE: paths_for("cake", "happy"),
            PetState.PHONE_GIGGLE: paths_for("phone_giggle", "happy"),
            PetState.WINK: paths_for("wink", "happy"),
            PetState.WORK: paths_for("work", "curious"),
            PetState.CORGI_PET: paths_for("corgi_pet", "happy"),
            PetState.CORGI_PLAY: paths_for("corgi_play", "happy"),
            PetState.STARRY: paths_for("starry", "happy"),
            PetState.BURGER: paths_for("burger", "happy"),
            PetState.CAMERA: paths_for("camera", "selfie"),
            PetState.EMPEROR: paths_for("emperor", "annoyed"),
            PetState.HUG: paths_for("hug", "shy"),
            PetState.SHY_FRONT: paths_for("shy_front", "shy"),
        }

        def load_frames(relative_paths: list[str]) -> list[QPixmap]:
            """加载一组清单相对路径并验证图片可读取。"""

            frames: list[QPixmap] = []
            for relative in relative_paths:
                path = manifest_path.parent / relative
                if not path.is_file():
                    raise FileNotFoundError(f"缺少角色素材：{path}")
                pixmap = QPixmap(str(path))
                if pixmap.isNull():
                    raise ValueError(f"无法加载角色素材：{path}")
                frames.append(pixmap)
            if not frames:
                raise ValueError("角色状态没有可用素材帧")
            return frames

        pixmaps: dict[PetState, list[QPixmap]] = {}
        for state, relative_paths in mapping.items():
            try:
                pixmaps[state] = load_frames(relative_paths)
            except ValueError as exc:
                raise ValueError(f"状态 {state.value} 没有可用素材帧") from exc

        self._outfit_twirl_frames = load_frames(
            animations.get("outfit_twirl", animations["idle"][:1])
        )
        self._outfit_options = load_frames(
            animations.get("outfit_options", animations["idle"])
        )
        pixmaps[PetState.OUTFIT] = [
            *self._outfit_twirl_frames,
            self._outfit_options[0],
        ]
        return pixmaps

    def _load_selfie_photo(self) -> QPixmap:
        """只加载用户提供的原始自拍照片，不用生成帧冒充原图。"""

        for relative in (
            "user_assets/selfie.png",
            "user_assets/selfie.jpg",
            "user_assets/selfie.jpeg",
            "user_assets/image.png",
        ):
            try:
                path = resource_path(relative)
            except FileNotFoundError:
                continue
            photo = QPixmap(str(path))
            if not photo.isNull():
                return photo
        return QPixmap()

    def place_at_start(self) -> None:
        """按已保存位置或主屏幕右下角放置窗口。"""

        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        if self.settings.start_x is None or self.settings.start_y is None:
            x = area.right() - self.width() - 24
            y = area.bottom() - self.height() - 12
        else:
            x = self.settings.start_x
            y = self.settings.start_y
        self.move(self._constrained_position(QPoint(x, y)))

    def set_state(self, state: PetState) -> None:
        """切换行为状态、重置帧序号并刷新当前图片。"""

        self.state = state
        self._frame_index = 0
        self._animation_direction = 1
        self._animation_finished = None
        self._turn_paused = False
        self._movement_x = float(self.x())
        self._last_movement_at = time.monotonic()
        self.turn_timer.stop()
        display_state = state
        frame_count = len(self._pixmaps[display_state])
        if frame_count > 1:
            self.animation_timer.start(self._frame_interval(display_state, 0))
        else:
            self.animation_timer.stop()
        if display_state is PetState.WALK:
            self._apply_frame_offset(display_state)
        else:
            self.label.move(6, 0)
        self._effect_phase = 0
        if emotion_effect_name(display_state) is None:
            self.effect_timer.stop()
        else:
            self.effect_timer.start()
        self._refresh_pixmap()

    def _frame_interval(self, state: PetState, frame_index: int) -> int:
        """返回指定动画帧的停留时间，使眨眼、过渡与行走节奏彼此独立。"""

        if state is PetState.IDLE:
            durations = (820, 360, 100, 120, 140, 720)
            return durations[frame_index % len(durations)]
        if state is PetState.WALK:
            return self._walk_frame_interval_ms
        if state is PetState.SIT:
            return 160
        if state is PetState.SLEEP:
            return 180
        if state is PetState.DRAG:
            return 180
        if state in (PetState.CORGI_PET, PetState.CORGI_PLAY):
            return 620
        if state is PetState.OUTFIT:
            return 520
        return 380

    @staticmethod
    def _remember_cache_item(cache, key, value) -> None:
        """写入小型最近使用缓存，并限制长期运行时的内存占用。"""

        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > 96:
            cache.popitem(last=False)

    def _current_source(self) -> tuple[PetState, QPixmap]:
        """返回当前显示状态及方向处理后的原始帧。"""

        display_state = self.state
        frames = self._pixmaps[display_state]
        pixmap = frames[min(self._frame_index, len(frames) - 1)]
        if self.direction < 0 and display_state is PetState.WALK:
            pixmap = pixmap.transformed(QTransform().scale(-1, 1))
        return display_state, pixmap

    def _refresh_pixmap(self) -> None:
        """从缓存取得或按当前屏幕设备像素比栅格化当前动画帧。"""

        display_state, pixmap = self._current_source()
        ratio = max(1.0, self.devicePixelRatioF())
        direction_key = self.direction if display_state is PetState.WALK else 0
        cache_key = (
            display_state,
            self._frame_index,
            direction_key,
            round(ratio, 3),
            self.label.width(),
            self.label.height(),
        )
        scaled = self._render_cache.get(cache_key)
        if scaled is None:
            target = QSize(
                max(1, round(self.label.width() * ratio)),
                max(1, round(self.label.height() * ratio)),
            )
            transformation = (
                Qt.TransformationMode.FastTransformation
                if self._pixel_art
                else Qt.TransformationMode.SmoothTransformation
            )
            scaled = pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                transformation,
            )
            scaled.setDevicePixelRatio(ratio)
            self._remember_cache_item(self._render_cache, cache_key, scaled)
        composed = draw_emotion_effect(
            scaled,
            display_state,
            self._effect_phase,
        )
        self.label.setPixmap(composed)
        effect_key = self._effect_phase if emotion_effect_name(display_state) else -1
        self._refresh_window_mask(display_state, composed, direction_key, effect_key)

    def _refresh_window_mask(
        self,
        display_state: PetState,
        pixmap: QPixmap,
        direction_key: int,
        effect_key: int,
    ) -> None:
        """按当前人物轮廓设置窗口遮罩，使透明留白不拦截桌面点击。"""

        if display_state is PetState.DRAG:
            # macOS 在按住鼠标时可能沿用旧轮廓；显式矩形区域可避免裁切。
            self.setMask(QRegion(self.rect()))
            return

        cache_key = (
            display_state,
            self._frame_index,
            direction_key,
            effect_key,
            self.label.width(),
            self.label.height(),
        )
        region = self._mask_cache.get(cache_key)
        if region is None:
            transformation = (
                Qt.TransformationMode.FastTransformation
                if self._pixel_art
                else Qt.TransformationMode.SmoothTransformation
            )
            logical = pixmap.scaled(
                self.label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                transformation,
            )
            offset_x = (self.label.width() - logical.width()) // 2
            offset_y = (self.label.height() - logical.height()) // 2
            region = QRegion(logical.mask()).translated(offset_x, offset_y)
            self._remember_cache_item(self._mask_cache, cache_key, region)
        self.setMask(region.translated(self.label.x(), self.label.y()))

    def _schedule_next_speech(self, *, initial: bool = False) -> None:
        """按自然的随机间隔安排下一句本地对白。"""

        if not self.settings.speech_enabled:
            self.speech_timer.stop()
            return
        minimum, maximum = (12000, 26000) if initial else (25000, 70000)
        self.speech_timer.start(random.randint(minimum, maximum))

    def _show_random_speech(self) -> None:
        """在人物附近短暂显示一句随机对白，然后继续下一轮。"""

        self._show_speech(SPEECH_LINES + self._custom_speech_lines)
        self._schedule_next_speech()

    def _show_speech(self, lines: tuple[str, ...]) -> None:
        """显示给定语句中的随机一句，并复用同一个圆角气泡。"""

        if (
            not self.settings.speech_enabled
            or not self.isVisible()
            or self.dragging
            or not lines
        ):
            return
        self.speech_bubble.setText(random.choice(lines))
        self.speech_bubble.adjustSize()
        self._position_speech_bubble()
        self.speech_bubble.show()
        _configure_macos_window_for_all_spaces(self.speech_bubble)
        self.speech_bubble.raise_()
        self.speech_hide_timer.start(4300)

    def _show_state_speech(self, state: PetState) -> None:
        """为用户触发的动作显示与当前情境相符的随机对白。"""

        lines = STATE_SPEECH_LINES.get(state, ()) + self._custom_state_speech.get(state, ())
        if lines:
            self._show_speech(lines)

    def trigger_speech(self) -> None:
        """从动作面板立即触发一句随机日常对白。"""

        self._record_user_interaction()
        self._show_random_speech()

    def set_speech_enabled(self, enabled: bool) -> None:
        """开启或关闭全部自动及动作对白，并记住用户选择。"""

        self.settings.speech_enabled = bool(enabled)
        if self.settings.speech_enabled:
            self._schedule_next_speech(initial=True)
        else:
            self.speech_timer.stop()
            self.speech_hide_timer.stop()
            self.speech_bubble.hide()

    def _position_speech_bubble(self) -> None:
        """让对白跟随人物头顶，并在靠近屏幕边缘时移到身侧。"""

        if not self.speech_bubble.isVisible() and not self.speech_bubble.text():
            return
        area = self._screen_geometry()
        visible_bounds = self.mask().boundingRect()
        if visible_bounds.isEmpty():
            visible_bounds = self.rect()
        character_left = self.x() + visible_bounds.left()
        character_right = self.x() + visible_bounds.right() + 1
        character_top = self.y() + visible_bounds.top()
        x = (character_left + character_right - self.speech_bubble.width()) // 2
        y = character_top - self.speech_bubble.height() - 9
        if area is not None:
            x = min(max(x, area.left()), area.right() - self.speech_bubble.width() + 1)
            if y < area.top():
                x = min(
                    max(character_right + 8, area.left()),
                    area.right() - self.speech_bubble.width() + 1,
                )
                y = max(area.top(), character_top)
        self.speech_bubble.move(x, y)

    def _effect_tick(self) -> None:
        """推进表情符号的轻微漂浮动画并刷新合成帧。"""

        if emotion_effect_name(self.state) is None:
            self.effect_timer.stop()
            return
        self._effect_phase = (self._effect_phase + 1) % 12
        self._refresh_pixmap()

    def _animation_tick(self) -> None:
        """推进循环或单次连续帧，并在反向过渡结束后执行回调。"""

        display_state = self.state
        frames = self._pixmaps[display_state]
        if len(frames) <= 1:
            return
        if self._animation_direction < 0:
            self._frame_index = max(0, self._frame_index - 1)
            if self._frame_index == 0:
                self.animation_timer.stop()
                callback = self._animation_finished
                self._animation_finished = None
                if callback is not None:
                    QTimer.singleShot(0, callback)
        elif display_state in ONE_SHOT_STATES:
            self._frame_index = min(self._frame_index + 1, len(frames) - 1)
            if self._frame_index == len(frames) - 1:
                self.animation_timer.stop()
        else:
            self._frame_index = (self._frame_index + 1) % len(frames)
        self._apply_frame_offset(display_state)
        self._refresh_pixmap()
        if self.animation_timer.isActive():
            self.animation_timer.setInterval(
                self._frame_interval(display_state, self._frame_index)
            )

    def _apply_frame_offset(self, display_state: PetState) -> None:
        """按跑步落脚、压缩和腾空阶段同步水平回弹与身体起伏。"""

        if display_state is PetState.WALK:
            if self._pixel_art:
                self.label.move(6, 0)
                return
            x_offsets = (6, 6, 6, 6, 6, 6, 6, 6)
            y_offsets = (3, 5, 2, 0, 3, 5, 2, 0)
            phase = self._frame_index % len(y_offsets)
            self.label.move(x_offsets[phase], y_offsets[phase])

    def _movement_speed_pixels_per_second(self) -> float:
        """按旧配置的平均速度计算恒定水平速度。"""

        return (
            self.settings.movement_step
            * 1000.0
            / self.settings.movement_interval_ms
        )

    def showEvent(self, event: QShowEvent) -> None:
        """窗口首次显示时连接跨屏信号并按当前 DPI 绘制。"""

        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_change_connected:
            handle.screenChanged.connect(self._on_screen_changed)
            self._screen_change_connected = True
        self._on_screen_changed(handle.screen() if handle else None)
        self._macos_all_spaces_enabled = _configure_macos_window_for_all_spaces(self)

    def moveEvent(self, event: QMoveEvent) -> None:
        """人物移动或被拖拽时同步更新对白位置。"""

        super().moveEvent(event)
        if hasattr(self, "speech_bubble") and self.speech_bubble.isVisible():
            self._position_speech_bubble()

    def hideEvent(self, event: QHideEvent) -> None:
        """隐藏角色时一并收起独立气泡窗口。"""

        self.photo_bubble.hide()
        self.speech_bubble.hide()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """退出时关闭独立气泡窗口，避免残留在桌面。"""

        self.photo_bubble.close()
        self.speech_bubble.close()
        super().closeEvent(event)

    def _on_screen_changed(self, screen: QScreen | None) -> None:
        """切换目标屏幕后重连 DPI 信号并延迟刷新素材。"""

        if self._connected_screen is not None:
            try:
                self._connected_screen.logicalDotsPerInchChanged.disconnect(
                    self._on_dpi_changed
                )
            except (RuntimeError, TypeError):
                pass
        self._connected_screen = screen
        if screen is not None:
            screen.logicalDotsPerInchChanged.connect(self._on_dpi_changed)
        self._render_cache.clear()
        QTimer.singleShot(0, self._refresh_pixmap)

    def _on_dpi_changed(self, _dpi: float) -> None:
        """显示器缩放发生变化时刷新当前帧。"""

        self._render_cache.clear()
        QTimer.singleShot(0, self._refresh_pixmap)

    def _schedule(self, decision: StateDecision) -> None:
        """应用状态决策并安排下一次状态切换。"""

        self.set_state(decision.state)
        if not self.dragging:
            self.state_timer.start(decision.duration_ms)

    def _state_timeout(self) -> None:
        """处理自主状态到期，并按无互动时长逐级进入坐下与睡眠。"""

        if self.dragging:
            return
        self._update_mood_if_due()
        inactive_ms = self._inactive_ms()
        if self._sleep_after_sit and self.state is PetState.SIT:
            self._sleep_after_sit = False
            self._schedule(self._decision(PetState.SLEEP, 8000))
            return
        if inactive_ms >= self.settings.inactive_sleep_ms:
            if self.state is PetState.SLEEP:
                self.state_timer.start(10000)
                return
            if self.state is PetState.SIT:
                self._schedule(self._decision(PetState.SLEEP, 10000))
                return
            self._schedule_sleep_via_sit()
            return
        if inactive_ms >= self.settings.inactive_sit_ms:
            if self.state is PetState.SIT:
                remaining = self.settings.inactive_sleep_ms - inactive_ms
                self.state_timer.start(max(500, min(5000, remaining)))
                return
            self._schedule(
                self._decision(
                    PetState.SIT,
                    min(5000, self.settings.inactive_sleep_ms - inactive_ms),
                )
            )
            return
        if self.state in (PetState.SIT, PetState.SLEEP):
            self._reverse_transition_to_idle()
            return
        decision = self.behavior.next_autonomous_state(
            self.state,
            allow_walk=not self.paused,
            mood=self.mood,
        )
        if decision.state is PetState.SLEEP:
            self._schedule_sleep_via_sit()
        else:
            self._schedule(decision)

    def _update_mood_if_due(self) -> None:
        """限制自然情绪变化频率，避免进度条数秒内连续跳动。"""

        now = time.monotonic()
        elapsed_ms = (now - self._last_mood_update_at) * 1000
        if elapsed_ms < self.settings.mood_update_interval_ms:
            return
        self._last_mood_update_at = now
        self.mood.pass_time(self.state)

    @staticmethod
    def _decision(state: PetState, duration_ms: int) -> StateDecision:
        """创建窗口内部过渡使用的确定时长状态决策。"""

        return StateDecision(state, max(500, duration_ms))

    def _inactive_ms(self) -> int:
        """返回距离最近一次鼠标或菜单互动的毫秒数。"""

        return max(0, round((time.monotonic() - self._last_user_interaction) * 1000))

    def _record_user_interaction(self) -> None:
        """重置无互动计时，并取消尚未开始的自动入睡意图。"""

        self._last_user_interaction = time.monotonic()
        self._sleep_after_sit = False

    def _schedule_sleep_via_sit(self) -> None:
        """先完整坐下，再从坐姿播放入睡序列。"""

        self._sleep_after_sit = True
        self._schedule(self._decision(PetState.SIT, 1400))

    def _reverse_transition_to_idle(self) -> None:
        """倒放坐下或睡眠序列，完成自然起身后再进入待机。"""

        frames = self._pixmaps[self.state]
        self._frame_index = len(frames) - 1
        self._animation_direction = -1
        self._animation_finished = self._finish_reverse_transition
        self._refresh_pixmap()
        self.animation_timer.start(self._frame_interval(self.state, self._frame_index))

    def _finish_reverse_transition(self) -> None:
        """睡醒后先回到坐姿，再倒放坐下序列恢复站立待机。"""

        if self.dragging:
            return
        if self.state is PetState.SLEEP:
            self.state = PetState.SIT
            self._frame_index = len(self._pixmaps[PetState.SIT]) - 1
            self._animation_direction = -1
            self._animation_finished = self._finish_reverse_transition
            self._refresh_pixmap()
            self.animation_timer.start(
                self._frame_interval(PetState.SIT, self._frame_index)
            )
            return
        self._schedule(self.behavior.initial_idle())

    def _screen_geometry(self):
        """返回窗口中心所在屏幕的可用区域。"""

        center = self.frameGeometry().center()
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _constrained_position(self, position: QPoint) -> QPoint:
        """将目标位置限制在当前或主屏幕可用区域内。"""

        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        if screen is None:
            return position
        area = screen.availableGeometry()
        x = min(max(position.x(), area.left()), area.right() - self.width() + 1)
        y = min(max(position.y(), area.top()), area.bottom() - self.height() + 1)
        return QPoint(x, y)

    def _movement_tick(self) -> None:
        """按实际经过时间亚像素累计移动，并在屏幕边缘转向。"""

        now = time.monotonic()
        elapsed = min(0.1, max(0.0, now - self._last_movement_at))
        self._last_movement_at = now
        if (
            self.paused
            or self.dragging
            or self._turn_paused
            or self.state is not PetState.WALK
        ):
            self._movement_x = float(self.x())
            return
        area = self._screen_geometry()
        if area is None:
            return
        if abs(self._movement_x - self.x()) > 1.5:
            self._movement_x = float(self.x())
        maximum = area.right() - self.width() + 1
        direction = 1 if self.direction >= 0 else -1
        phase_factor = self._walk_motion_factors[
            self._frame_index % len(self._walk_motion_factors)
        ]
        self._movement_x += direction * (
            self._movement_speed_pixels_per_second()
            * phase_factor
            * elapsed
        )
        if self._movement_x <= area.left():
            self._movement_x = float(area.left())
            direction = 1
        elif self._movement_x >= maximum:
            self._movement_x = float(maximum)
            direction = -1
        if direction != self.direction:
            self.direction = direction
            self._frame_index = 0
            self._turn_paused = True
            self.animation_timer.stop()
            self._refresh_pixmap()
            self.turn_timer.start(self.settings.turn_pause_ms)
        self.move(round(self._movement_x), self.y())

    def _finish_turn(self) -> None:
        """结束屏幕边缘的短暂停顿，并从第一帧恢复行走。"""

        self._turn_paused = False
        self._movement_x = float(self.x())
        self._last_movement_at = time.monotonic()
        if self.state is PetState.WALK and not self.paused and not self.dragging:
            self.animation_timer.start(
                self._frame_interval(PetState.WALK, self._frame_index)
            )

    def _bob_tick(self) -> None:
        """通过标签轻微上下移动营造呼吸和行走起伏。"""

        if self.state is PetState.WALK:
            return
        if self.state not in BOBBING_STATES:
            self.label.move(6, 0)
            self._refresh_pixmap()
            return
        self._bob_phase = not self._bob_phase
        self.label.move(6, 2 if self._bob_phase else 0)
        self._refresh_pixmap()

    def set_paused(self, paused: bool) -> None:
        """暂停或恢复跑动；暂停期间仍继续坐下、睡眠和自拍等生活状态。"""

        self._record_user_interaction()
        self.paused = paused
        self.pause_changed.emit(paused)
        if paused and self.state is PetState.WALK:
            self.state_timer.stop()
            decision = self.behavior.next_autonomous_state(
                PetState.IDLE,
                allow_walk=False,
                mood=self.mood,
            )
            if decision.state is PetState.SLEEP:
                self._schedule_sleep_via_sit()
            else:
                self._schedule(decision)
        elif not paused and not self.dragging and not self.state_timer.isActive():
            self._schedule(self.behavior.initial_idle())

    def set_display_height(self, display_height: int) -> None:
        """应用右键菜单尺寸预设，保持窗口底部中心位置并立即重绘。"""

        self._record_user_interaction()
        old_center_x = self.x() + self.width() // 2
        old_bottom = self.y() + self.height()
        self.settings.display_height = max(120, min(600, int(display_height)))
        source = self._pixmaps[PetState.IDLE][0]
        width = round(
            self.settings.display_height * source.width() / source.height()
        )
        self.setFixedSize(width + 12, self.settings.display_height + 14)
        self.label.setGeometry(6, 0, width, self.settings.display_height + 8)
        self._render_cache.clear()
        self._mask_cache.clear()
        target = QPoint(
            old_center_x - self.width() // 2,
            old_bottom - self.height(),
        )
        self.move(self._constrained_position(target))
        self._refresh_pixmap()

    def return_to_primary_screen(self) -> None:
        """将角色重新放到主屏幕右下角。"""

        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 12)

    def trigger_interaction(self) -> None:
        """结合四项情绪数值触发合适的表情或友好反馈。"""

        if self.dragging:
            return
        self._record_user_interaction()
        if self.mood.hunger >= 75:
            state = PetState.HUNGRY
        elif self.mood.energy < 30:
            state = PetState.SLEEPY
        elif self.mood.boredom > 70:
            state = random.choice(
                (PetState.BORED, PetState.PHONE_GIGGLE, PetState.CORGI_PLAY)
            )
        elif self.mood.affinity >= 70:
            state = random.choice((PetState.HUG, PetState.STARRY, PetState.LAUGH))
        else:
            state = random.choice(
                (PetState.WAVE, PetState.WINK, PetState.HAPPY, PetState.ENJOY)
            )
        self._show_emotion(state, 1800, with_speech=True)

    def _show_emotion(
        self,
        state: PetState,
        duration_ms: int = 1600,
        *,
        with_speech: bool = False,
    ) -> None:
        """显示一次短暂互动表情，并在计时结束后恢复自主生活。"""

        self.state_timer.stop()
        self.set_state(state)
        self.interaction_timer.start(max(500, duration_ms))
        if with_speech:
            self._show_state_speech(state)

    def trigger_selfie(self) -> None:
        """显式播放一次举起相机、闪光和查看照片的自拍序列。"""

        if self.dragging:
            return
        self._record_user_interaction()
        self._show_emotion(PetState.SELFIE, 2600, with_speech=True)

    def trigger_state(self, state: PetState, duration_ms: int = 2200) -> None:
        """从菜单显式播放一个表情、日常或道具状态。"""

        if self.dragging:
            return
        self._record_user_interaction()
        self._show_emotion(state, duration_ms, with_speech=True)

    def trigger_food(self, state: PetState) -> None:
        """播放蛋糕或汉堡状态并立即降低饥饿度。"""

        if state not in (PetState.CAKE, PetState.BURGER):
            raise ValueError("食物互动只接受蛋糕或汉堡状态")
        self.mood.receive_food(32 if state is PetState.CAKE else 48)
        self.trigger_state(state, 3000)

    def trigger_corgi(self) -> None:
        """连续播放摸柯基和接小爪陪玩的两段动作，并降低无聊度。"""

        self.mood.receive_play()
        self.trigger_state(PetState.CORGI_PLAY, 3400)

    def trigger_outfit_change(self) -> None:
        """先播放水手裙转圈，再随机展示一套临时造型后恢复主服装。"""

        if self.dragging:
            return
        self._record_user_interaction()
        chosen = random.choice(self._outfit_options)
        self._pixmaps[PetState.OUTFIT] = [*self._outfit_twirl_frames, chosen]
        self._render_cache.clear()
        self._mask_cache.clear()
        self._show_emotion(PetState.OUTFIT, 4800)
        self._show_state_speech(PetState.OUTFIT)

    def trigger_sleep(self) -> None:
        """从菜单请求乖乖睡觉，并保持先坐下再入睡的过渡。"""

        if self.dragging:
            return
        self._record_user_interaction()
        self._schedule_sleep_via_sit()
        self._show_state_speech(PetState.SLEEP)

    def _interaction_zone(self, point: QPoint) -> str:
        """按窗口内相对位置划分头顶、脸部、身体和相机互动区域。"""

        x = (point.x() - self.label.x()) / max(1, self.label.width())
        y = (point.y() - self.label.y()) / max(1, self.label.height())
        if y < 0.24:
            return "head"
        if y < 0.46:
            return "face"
        if 0.42 <= y <= 0.82 and x < 0.43:
            return "camera"
        return "body"

    def _handle_click(self, point: QPoint) -> None:
        """根据点击区域更新情绪并选择对应反馈。"""

        zone = self._interaction_zone(point)
        self._record_user_interaction()
        if self.state is PetState.SLEEP:
            self._show_emotion(PetState.WAKE, 1800)
            return
        if zone == "camera":
            self.trigger_selfie()
            return
        if zone == "head":
            self.mood.receive_affection()
            state = (
                PetState.SHY_FRONT
                if self.mood.affinity >= 70
                else PetState.ENJOY
            )
            self._show_emotion(state, 1700)
            return
        if zone == "face":
            self.mood.receive_poke(False)
            self._show_emotion(
                random.choice((PetState.POUT, PetState.SURPRISED)),
                1300,
            )
            return
        self._show_action_menu(QCursor.pos())

    def _track_passive_motion(self, point: QPoint) -> None:
        """跟踪无按键悬停；停留触发好奇，头部往返移动判定为摸头。"""

        zone = self._interaction_zone(point)
        self._hover_zone = zone
        if self.state is PetState.IDLE and not self.interaction_timer.isActive():
            self.hover_timer.start(700)
        if zone != "head":
            self._stroke_points.clear()
            return

        now = time.monotonic()
        self._stroke_points.append((now, point))
        while self._stroke_points and now - self._stroke_points[0][0] > 1.2:
            self._stroke_points.popleft()
        distance = sum(
            (current[1] - previous[1]).manhattanLength()
            for previous, current in zip(
                self._stroke_points,
                list(self._stroke_points)[1:],
            )
        )
        if distance >= 70 and now - self._last_stroke_reaction >= 2.0:
            self._last_stroke_reaction = now
            self._stroke_points.clear()
            self.mood.receive_affection()
            self._record_user_interaction()
            state = (
                PetState.SHY_FRONT
                if self.mood.affinity >= 70
                else PetState.ENJOY
            )
            self._show_emotion(state, 1600)

    def _trigger_hover_curiosity(self) -> None:
        """鼠标在角色附近稳定停留时显示好奇注视。"""

        if (
            self._hover_zone
            and self.state is PetState.IDLE
            and not self.dragging
            and not self._press_pending
            and not self.interaction_timer.isActive()
        ):
            self._record_user_interaction()
            self._show_emotion(PetState.THINKING, 1300)

    def _show_photo_bubble(self) -> None:
        """在角色旁显示独立自拍成片，并在数秒后自动隐藏。"""

        if self._selfie_photo.isNull():
            return
        ratio = max(1.0, self.devicePixelRatioF())
        photo = self._scaled_selfie_photo(ratio)
        logical_size = QSize(
            max(1, round(photo.width() / ratio)),
            max(1, round(photo.height() / ratio)),
        )
        self.photo_bubble.setPixmap(photo)
        self.photo_bubble.setFixedSize(logical_size)
        area = self._screen_geometry()
        visible_bounds = self.mask().boundingRect()
        if visible_bounds.isEmpty():
            character_left = self.x()
            character_right = self.x() + self.width()
        else:
            character_left = self.x() + visible_bounds.left()
            character_right = self.x() + visible_bounds.right() + 1
        gap = 8
        x = character_left - self.photo_bubble.width() - gap
        if area is not None and x < area.left():
            x = character_right + gap
        y = self.y() + max(0, (self.height() - self.photo_bubble.height()) // 2)
        self.photo_bubble.move(x, y)
        self.photo_bubble.show()
        _configure_macos_window_for_all_spaces(self.photo_bubble)
        self.photo_timer.start(3800)

    def _scaled_selfie_photo(self, ratio: float) -> QPixmap:
        """按设备像素比生成照片缩略图，避免高 DPI 屏幕二次放大导致模糊。"""

        if self._selfie_photo.isNull():
            return QPixmap()
        ratio = max(1.0, ratio)
        photo = self._selfie_photo.scaled(
            max(1, round(150 * ratio)),
            max(1, round(210 * ratio)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        photo.setDevicePixelRatio(ratio)
        return photo

    def _finish_interaction(self) -> None:
        """结束互动并恢复自主待机。"""

        if not self.dragging:
            self._schedule(self.behavior.initial_idle())

    def _add_status_panel(self, menu: QMenu) -> None:
        """在动作菜单顶部加入当前状态和四色心情进度条。"""

        panel = QWidget(menu)
        panel.setObjectName("moodPanel")
        layout = QGridLayout(panel)
        layout.setContentsMargins(12, 10, 12, 9)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(5)

        title = QLabel(
            f"小u现在：{STATE_LABELS.get(self.state, self.state.value)}",
            panel,
        )
        title.setObjectName("moodTitle")
        layout.addWidget(title, 0, 0, 1, 3)

        mood_rows = (
            ("默契", self.mood.affinity, "#df5b86"),
            ("精力", self.mood.energy, "#4387c7"),
            ("无聊", self.mood.boredom, "#d69a31"),
            ("饥饿", self.mood.hunger, "#6c9d56"),
        )
        for row, (label, value, color) in enumerate(mood_rows, start=1):
            name = QLabel(label, panel)
            name.setObjectName("moodName")
            bar = QProgressBar(panel)
            bar.setRange(0, 100)
            bar.setValue(value)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setMinimumWidth(118)
            bar.setStyleSheet(
                "QProgressBar { background: #ece8eb; border: none; border-radius: 4px; }"
                f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
            )
            amount = QLabel(f"{value}", panel)
            amount.setObjectName("moodValue")
            layout.addWidget(name, row, 0)
            layout.addWidget(bar, row, 1)
            layout.addWidget(amount, row, 2)

        status_action = QWidgetAction(menu)
        status_action.setDefaultWidget(panel)
        menu.addAction(status_action)
        menu.addSeparator()

    def _show_action_menu(self, global_position: QPoint) -> None:
        """在鼠标附近非阻塞显示状态与动作面板，并保持菜单对象存活。"""

        if self._active_context_menu is not None:
            self._active_context_menu.close()
        menu = self._build_context_menu()
        self._active_context_menu = menu
        menu.aboutToHide.connect(lambda: setattr(self, "_active_context_menu", None))
        menu.popup(global_position)

    def _build_context_menu(self) -> QMenu:
        """构建角色窗口的右键菜单。"""

        menu = QMenu(self)
        menu.setMinimumWidth(246)
        menu.setStyleSheet(
            "QMenu { background: #fff9fb; color: #303746; border: 1px solid #e8afc2; "
            "border-radius: 8px; padding: 6px; }"
            "QMenu::item { padding: 7px 26px 7px 11px; margin: 1px 2px; "
            "border-radius: 6px; }"
            "QMenu::item:selected { background: #f9dce7; color: #1f3552; }"
            "QMenu::item:disabled { color: #8c7e85; }"
            "QMenu::separator { height: 1px; background: #eadde2; margin: 6px 8px; }"
            "QWidget#moodPanel { background: #fff9fb; }"
            "QLabel#moodTitle { color: #1f3552; font-weight: 700; padding-bottom: 3px; }"
            "QLabel#moodName { color: #665a62; font-size: 11px; }"
            "QLabel#moodValue { color: #665a62; font-size: 10px; min-width: 22px; }"
        )
        self._add_status_panel(menu)
        pause_action = QAction("恢复跑动" if self.paused else "暂停跑动", self)
        pause_action.triggered.connect(lambda: self.set_paused(not self.paused))
        menu.addAction(pause_action)
        interact_action = QAction("和小u打招呼", self)
        interact_action.triggered.connect(self.trigger_interaction)
        menu.addAction(interact_action)
        speech_action = QAction("听小u说句话", self)
        speech_action.triggered.connect(self.trigger_speech)
        speech_action.setEnabled(self.settings.speech_enabled)
        menu.addAction(speech_action)
        speech_toggle_action = QAction(
            "关闭小u说话" if self.settings.speech_enabled else "开启小u说话",
            self,
        )
        speech_toggle_action.triggered.connect(
            lambda: self.set_speech_enabled(not self.settings.speech_enabled)
        )
        menu.addAction(speech_toggle_action)

        def add_state_action(
            target_menu: QMenu,
            label: str,
            state: PetState,
            duration_ms: int = 2200,
        ) -> None:
            """向指定子菜单加入绑定固定桌面角色状态的操作。"""

            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, value=state, duration=duration_ms: self.trigger_state(
                    value,
                    duration,
                )
            )
            target_menu.addAction(action)

        expression_menu = menu.addMenu("表情与互动")
        expression_actions = [
            ("嘟嘴", PetState.POUT),
            ("大笑", PetState.LAUGH),
            ("闭眼享受", PetState.ENJOY),
            ("Wink", PetState.WINK),
            ("星星眼捧脸", PetState.STARRY),
            ("难过", PetState.SAD),
            ("无聊等待", PetState.BORED),
            ("惊讶", PetState.SURPRISED),
            ("生气凶人", PetState.ANNOYED),
            ("陷入思考", PetState.THINKING),
            ("困倦", PetState.SLEEPY),
        ]
        for label, state in expression_actions:
            add_state_action(expression_menu, label, state)
        for label, state, duration_ms in self._custom_menu_actions:
            add_state_action(expression_menu, label, state, duration_ms)
        sleep_action = QAction("乖乖睡觉", self)
        sleep_action.triggered.connect(self.trigger_sleep)
        expression_menu.addAction(sleep_action)

        food_menu = menu.addMenu("吃东西")
        cake_action = QAction("吃蛋糕满足", self)
        cake_action.triggered.connect(
            lambda _checked=False: self.trigger_food(PetState.CAKE)
        )
        food_menu.addAction(cake_action)
        burger_action = QAction("大口吃汉堡", self)
        burger_action.triggered.connect(
            lambda _checked=False: self.trigger_food(PetState.BURGER)
        )
        food_menu.addAction(burger_action)

        daily_menu = menu.addMenu("日常和道具")
        add_state_action(daily_menu, "玩手机傻笑", PetState.PHONE_GIGGLE, 3000)
        add_state_action(daily_menu, "坐椅子电脑摸鱼", PetState.WORK, 3600)
        play_corgi_action = QAction("陪柯基玩", self)
        play_corgi_action.triggered.connect(self.trigger_corgi)
        daily_menu.addAction(play_corgi_action)
        add_state_action(daily_menu, "拿相机拍照", PetState.CAMERA, 2600)
        add_state_action(daily_menu, "小皇帝", PetState.EMPEROR, 3000)
        add_state_action(daily_menu, "醒来", PetState.WAKE, 1800)
        selfie_action = QAction("自拍", self)
        selfie_action.triggered.connect(self.trigger_selfie)
        daily_menu.addAction(selfie_action)

        outfit_action = QAction("随机换装", self)
        outfit_action.triggered.connect(self.trigger_outfit_change)
        menu.addAction(outfit_action)
        size_menu = menu.addMenu("小u大小")
        for label, height in (
            ("迷你（120）", 120),
            ("桌面（150）", 150),
            ("舒适（180）", 180),
            ("大号（220）", 220),
        ):
            size_action = QAction(label, self)
            size_action.setCheckable(True)
            size_action.setChecked(self.settings.display_height == height)
            size_action.triggered.connect(
                lambda _checked=False, value=height: self.set_display_height(value)
            )
            size_menu.addAction(size_action)
        return_action = QAction("回到主屏幕", self)
        return_action.triggered.connect(self.return_to_primary_screen)
        menu.addAction(return_action)
        hide_action = QAction("隐藏", self)
        hide_action.triggered.connect(self.hide)
        menu.addAction(hide_action)
        menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """在鼠标位置显示窗口菜单。"""

        self._record_user_interaction()
        self._show_action_menu(event.globalPos())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """记录左键按下；只有移动超过系统阈值后才真正进入拖拽。"""

        if event.button() == Qt.MouseButton.LeftButton:
            self._record_user_interaction()
            self._press_pending = True
            self.dragging = False
            # macOS 会在按下时缓存窗口轮廓，必须在移动阈值之前放开遮罩。
            self.setMask(QRegion(self.rect()))
            self.state_timer.stop()
            self.interaction_timer.stop()
            self.hover_timer.stop()
            self._press_local = event.position().toPoint()
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """拖动期间根据全局鼠标位置移动并限制窗口。"""

        if event.buttons() & Qt.MouseButton.LeftButton:
            current_global = event.globalPosition().toPoint()
            if (
                self._press_pending
                and (current_global - self._press_global).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                self._press_pending = False
                self.dragging = True
                self.mood.receive_drag()
                self.set_state(PetState.DRAG)
            if not self.dragging:
                event.accept()
                return
            target = event.globalPosition().toPoint() - self._drag_offset
            self.move(self._constrained_position(target))
            event.accept()
            return
        self._track_passive_motion(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """左键释放时结束拖动并恢复待机。"""

        if event.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                self.dragging = False
                self._press_pending = False
                self._show_emotion(PetState.SURPRISED, 1100, with_speech=True)
            elif self._press_pending:
                self._press_pending = False
                self._refresh_pixmap()
                self._handle_click(self._press_local)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标离开角色时取消尚未触发的悬停和摸头轨迹。"""

        self._hover_zone = ""
        self._stroke_points.clear()
        self.hover_timer.stop()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """双击左键时触发互动反馈。"""

        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self._press_pending = False
            self.mood.receive_affection()
            self._record_user_interaction()
            self._show_emotion(PetState.LAUGH, 1800, with_speech=True)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
