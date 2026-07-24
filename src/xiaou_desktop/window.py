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
from .branding import Branding, load_branding
from .config import PetSettings
from .emotion_effects import draw_emotion_effect, emotion_effect_name
from .peer import (
    DEFAULT_PEER_CONVERSATIONS,
    DIALOGUE_TURN_S,
    PEER_INTERRUPT_COOLDOWN_S,
    PEER_REAPPROACH_CHANCE,
    PEER_REAPPROACH_COOLDOWN_S,
    SOLO_MURMUR_MIN_GAP_S,
    SYNC_ACTION_HOLD_S,
    PeerPresence,
    arrived_beside,
    clear_presence,
    centers_near,
    dialogue_line_for_turn,
    dialogue_turn_index,
    facing_for_meetup,
    facing_toward,
    format_dialogue_line,
    is_dialogue_director,
    list_peers,
    stand_beside_target,
    within_approach_range,
    write_presence,
)
from .resources import resource_path
from .workflow import WorkflowError, character_is_approved, load_workflow


DEFAULT_WALK_MOTION_FACTORS = (0.45, 0.7, 1.2, 1.65, 0.45, 0.7, 1.2, 1.65)

ONE_SHOT_STATES = {
    PetState.SIT,
    PetState.SLEEP,
    PetState.SELFIE,
    PetState.OUTFIT,
    PetState.PEER_MEET,
}

BOBBING_STATES = {
    PetState.IDLE,
    PetState.SIDE_STAND,
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
    PetState.SIDE_STAND: "侧身站着",
    PetState.PEER_NOTICE: "看见对方了",
    PetState.PEER_MEET: "和对方互动",
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

# 发现其他桌宠靠近时的默认对白（定制角色可用 branding.peer_* 覆盖）
PEER_SPEECH_LINES = (
    "诶，你也在这儿呀。",
    "桌面突然就不孤单了。",
    "今天也一起摸两分钟鱼吧。",
    "心心库存还有，需要随时说。",
    "并排站着也好看。",
    "工作再拼，也记得看我一眼。",
    "有你在，气氛都不一样了。",
    "偷懒被抓到的话，就说是我带的。",
)
PEER_NOTICE_SPEECH = (
    "咦，是你！",
    "发现熟悉的身影了。",
    "诶，那边那位……",
    "我看见你了。",
)
PEER_APPROACH_SPEECH = (
    "我过去找你啦。",
    "我也往你这边走。",
    "朝你走过来咯。",
    "来会合吧。",
)
# 被对方找来时的回应（双向奔赴，不要「别跑/别动」）
PEER_REPLY_SPEECH = (
    "嗯，我也过来了。",
    "看见你了，来。",
    "好，我这边也走。",
    "来啦。",
    "正好，我正想找你。",
)
# 在一起/对话中被拖开或拆散时的反应（不要立刻改口说「我过来」）
PEER_INTERRUPT_SPEECH = (
    "诶？",
    "先这样吧。",
    "……好吧。",
    "被拉开了。",
)
PEER_SEPARATED_SPEECH = (
    "诶，你去哪儿？",
    "那我先在这儿。",
    "好，先各自待着。",
    "嗯……下次再挨着。",
)
PEER_MISS_SPEECH = (
    "好像还没有其他桌宠在线诶。",
    "对方还没上线，我再等等。",
    "桌面上暂时只有我自己。",
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
    PetState.PEER_NOTICE: ("咦，是你！", "发现你了。"),
    PetState.PEER_MEET: ("来，挨着我。", "今天也要好好的。"),
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
    """绘制四角透明的圆角对白气泡，颜色可由品牌配置覆盖。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.border_color = QColor(231, 169, 191, 245)
        self.fill_color = QColor(255, 249, 251, 248)

    def set_palette_colors(
        self,
        border: tuple[int, int, int, int],
        fill: tuple[int, int, int, int],
    ) -> None:
        """设置气泡边框与填充色。"""

        self.border_color = QColor(*border)
        self.fill_color = QColor(*fill)

    def paintEvent(self, event: QPaintEvent) -> None:
        """先绘制圆角底与细边框，再交给 QLabel 绘制文字。"""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(self.border_color, 1.0))
        painter.setBrush(self.fill_color)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)
        painter.end()
        super().paintEvent(event)


def _macos_objc_bridge() -> tuple | None:
    """返回 macOS Cocoa 消息发送辅助函数；非 Cocoa 环境返回 None。"""

    if sys.platform != "darwin" or QApplication.platformName() != "cocoa":
        return None
    try:
        objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        message_address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        if message_address is None:
            return None
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
        send_child = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_long,
        )(message_address)
        remove_child = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(message_address)

        def selector(name: bytes) -> ctypes.c_void_p:
            return ctypes.c_void_p(objc.sel_registerName(name))

        def native_window_for(widget: QWidget) -> ctypes.c_void_p | None:
            if widget is None:
                return None
            # 确保已有原生窗口句柄（气泡首次 show 前可能还没有）
            widget.winId()
            view = ctypes.c_void_p(int(widget.winId()))
            window = send_object(view, selector(b"window"))
            return window or None

        return (
            selector,
            send_object,
            send_integer,
            set_integer,
            set_bool,
            send_child,
            remove_child,
            native_window_for,
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _configure_macos_space_behavior(
    widget: QWidget,
    *,
    join_all_spaces: bool = True,
) -> bool:
    """配置 Cocoa 窗口是否跟随全部桌面空间；默认跟随全部。"""

    bridge = _macos_objc_bridge()
    if bridge is None:
        return False
    try:
        (
            selector,
            _send_object,
            send_integer,
            set_integer,
            set_bool,
            _send_child,
            _remove_child,
            native_window_for,
        ) = bridge
        native_window = native_window_for(widget)
        if not native_window:
            return False
        current_behavior = send_integer(
            native_window,
            selector(b"collectionBehavior"),
        )
        # CanJoinAllSpaces=1<<0, MoveToActiveSpace=1<<1, Managed=1<<2,
        # Stationary=1<<4, FullScreenAuxiliary=1<<8
        can_join = 1 << 0
        move_active = 1 << 1
        managed = 1 << 2
        stationary = 1 << 4
        fullscreen_aux = 1 << 8
        cleared = current_behavior & ~(can_join | move_active | stationary)
        if join_all_spaces:
            # 全部桌面空间都显示
            behavior = cleared | can_join | stationary | fullscreen_aux
        else:
            # 只留在当前桌面：不要 CanJoinAllSpaces，也不要 MoveToActiveSpace
            # （后者会在切桌面时把窗口拽到前台桌面，气泡就「跑去别的屏」了）
            behavior = cleared | managed | fullscreen_aux
        set_integer(
            native_window,
            selector(b"setCollectionBehavior:"),
            behavior,
        )
        set_bool(native_window, selector(b"setHidesOnDeactivate:"), False)
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _attach_macos_child_window(parent: QWidget, child: QWidget) -> bool:
    """把气泡 NSWindow 挂到角色窗口下，切桌面时一起留在同一空间。"""

    bridge = _macos_objc_bridge()
    if bridge is None:
        return False
    try:
        (
            selector,
            _send_object,
            _send_integer,
            _set_integer,
            _set_bool,
            send_child,
            _remove_child,
            native_window_for,
        ) = bridge
        parent_window = native_window_for(parent)
        child_window = native_window_for(child)
        if not parent_window or not child_window:
            return False
        if int(parent_window.value or 0) == int(child_window.value or 0):
            return False
        # NSWindowAbove = 1
        send_child(
            parent_window,
            selector(b"addChildWindow:ordered:"),
            child_window,
            1,
        )
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _detach_macos_child_window(parent: QWidget, child: QWidget) -> bool:
    """隐藏气泡时解除 Cocoa 子窗口关系，避免残留附着。"""

    bridge = _macos_objc_bridge()
    if bridge is None:
        return False
    try:
        (
            selector,
            _send_object,
            _send_integer,
            _set_integer,
            _set_bool,
            _send_child,
            remove_child,
            native_window_for,
        ) = bridge
        parent_window = native_window_for(parent)
        child_window = native_window_for(child)
        if not parent_window or not child_window:
            return False
        remove_child(
            parent_window,
            selector(b"removeChildWindow:"),
            child_window,
        )
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


# 兼容旧调用名
def _configure_macos_window_for_all_spaces(widget: QWidget) -> bool:
    return _configure_macos_space_behavior(widget, join_all_spaces=True)


class PetWindow(QWidget):
    """显示并控制单个桌面角色的透明顶层窗口。"""

    quit_requested = Signal()
    pause_changed = Signal(bool)

    def __init__(self, settings: PetSettings) -> None:
        super().__init__()
        self.settings = settings
        self.branding: Branding = load_branding()
        # 定制角色默认更慢一点的生活节奏（覆盖旧版用户设置里偏快的值）
        if self.branding.is_custom:
            self.settings.idle_min_ms = max(self.settings.idle_min_ms, 2400)
            self.settings.idle_max_ms = max(self.settings.idle_max_ms, 5200)
            self.settings.action_min_ms = max(self.settings.action_min_ms, 4200)
            self.settings.action_max_ms = max(self.settings.action_max_ms, 7800)
            self.settings.walk_frame_interval_ms = max(
                self.settings.walk_frame_interval_ms,
                150,
            )
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
        self._sequence_queue: deque[tuple[PetState, int]] = deque()
        self._state_labels = dict(STATE_LABELS)
        self._state_labels.update(
            {
                PetState(key): label
                for key, label in self.branding.labels.items()
                if key in PetState._value2member_map_
            }
        )
        self._speech_lines = (
            self.branding.speech_lines if self.branding.speech_lines else SPEECH_LINES
        )
        self._peer_speech_lines = (
            self.branding.peer_speech if self.branding.peer_speech else PEER_SPEECH_LINES
        )
        self._peer_notice_speech = (
            self.branding.peer_notice_speech
            if self.branding.peer_notice_speech
            else PEER_NOTICE_SPEECH
        )
        self._peer_approach_speech = (
            self.branding.peer_approach_speech
            if self.branding.peer_approach_speech
            else PEER_APPROACH_SPEECH
        )
        self._peer_reply_speech = PEER_REPLY_SPEECH
        self._peer_miss_speech = (
            self.branding.peer_miss_speech
            if self.branding.peer_miss_speech
            else PEER_MISS_SPEECH
        )
        self._state_speech_lines = dict(STATE_SPEECH_LINES)
        for key, lines in self.branding.state_speech.items():
            if key in PetState._value2member_map_:
                self._state_speech_lines[PetState(key)] = lines
        self._last_stroke_reaction = 0.0
        self._bob_phase = False
        self._effect_phase = 0
        self._frame_index = 0
        self._animation_direction = 1
        self._animation_finished: Callable[[], None] | None = None
        self._turn_paused = False
        self._last_user_interaction = time.monotonic()
        self._last_mood_update_at = time.monotonic()
        self._last_peer_interaction_at = 0.0
        self._peer_busy_until = 0.0
        self._peer_approach_id: str | None = None
        self._peer_approach_until = 0.0
        self._peer_meeting_id: str | None = None
        self._peer_hangout_until = 0.0
        self._peer_next_action_at = 0.0
        self._peer_speech_turn = -1
        self._peer_chat_id = -1
        self._peer_chat_started_at = 0.0
        self._peer_next_chat_at = 0.0
        self._peer_last_solo_at = 0.0
        self._peer_interrupt_until = 0.0
        self._peer_reapproach = False
        self._peer_ease_to: tuple[float, float] | None = None
        self._sync_action = ""
        self._sync_action_at = 0.0
        self._sync_action_until = 0.0
        self._peer_conversations = DEFAULT_PEER_CONVERSATIONS
        self._has_peer_notice_art = False
        self._has_peer_meet_art = False
        self._has_side_stand_art = False
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

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if sys.platform == "darwin":
            self.setAttribute(
                Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow,
                True,
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle(self.branding.display_name)
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
            | Qt.WindowType.WindowDoesNotAcceptFocus
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
        self.photo_bubble.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.photo_bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_bubble.setStyleSheet("background: transparent;")

        self.speech_bubble = SpeechBubble()
        self.speech_bubble.set_palette_colors(
            self.branding.theme.speech_border,
            self.branding.theme.speech_fill,
        )
        self.speech_bubble.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
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
        self.speech_bubble.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speech_bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speech_bubble.setContentsMargins(11, 8, 11, 8)
        self.speech_bubble.setStyleSheet(
            "QLabel { background: transparent; color: "
            f"{self.branding.theme.speech_text}; "
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
        self.photo_timer.timeout.connect(self._hide_photo_bubble)

        self.speech_timer = QTimer(self)
        self.speech_timer.setSingleShot(True)
        self.speech_timer.timeout.connect(self._show_random_speech)

        self.speech_hide_timer = QTimer(self)
        self.speech_hide_timer.setSingleShot(True)
        self.speech_hide_timer.timeout.connect(self._hide_speech_bubble)

        self.peer_timer = QTimer(self)
        self.peer_timer.setInterval(320)
        self.peer_timer.timeout.connect(self._peer_tick)
        self.peer_timer.start()

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
        self._has_peer_notice_art = "peer_notice" in animations
        self._has_peer_meet_art = "peer_meet" in animations
        self._has_side_stand_art = "side_stand" in animations
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
            PetState.SIDE_STAND: paths_for("side_stand", "idle"),
            # 定制可在 manifest 加 peer_notice / peer_meet；没有则回退现有表情
            PetState.PEER_NOTICE: paths_for("peer_notice", "surprised"),
            PetState.PEER_MEET: paths_for(
                "peer_meet",
                "hug" if "hug" in animations else "shy",
            ),
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
            durations = (1200, 520, 160, 180, 200, 1100)
            return durations[frame_index % len(durations)]
        if state is PetState.WALK:
            return max(160, self._walk_frame_interval_ms)
        if state is PetState.SIT:
            return 260
        if state is PetState.SLEEP:
            return 280
        if state is PetState.DRAG:
            return 260
        if state in (PetState.CORGI_PET, PetState.CORGI_PLAY):
            return 900
        if state is PetState.OUTFIT:
            frames = self._pixmaps.get(PetState.OUTFIT, [])
            # 前奏帧尽快切过，最后一帧（新衣服）停久一点
            if frame_index < max(0, len(frames) - 1):
                return 80 if self.branding.is_custom else 280
            return 1000
        if state is PetState.WORK:
            return 720
        if state is PetState.PEER_NOTICE:
            return 1600
        if state is PetState.PEER_MEET:
            # 抱抱停久一点，再切飞吻
            return 2800 if frame_index == 0 else 3000
        if state is PetState.SIDE_STAND:
            return 1200
        return 560

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
        if display_state is PetState.WALK:
            # 演示小u素材默认朝右；鸡蛋壳走路帧朝向相反，按角色分别镜像
            face_left_when_moving_left = not self.branding.is_custom
            moving_left = self.direction < 0
            if moving_left == face_left_when_moving_left:
                pixmap = pixmap.transformed(QTransform().scale(-1, 1))
        elif display_state in (
            PetState.PEER_NOTICE,
            PetState.PEER_MEET,
            PetState.SIDE_STAND,
            PetState.WAVE,
            PetState.HAPPY,
            PetState.WINK,
            PetState.ENJOY,
            PetState.LAUGH,
            PetState.THINKING,
            PetState.HUG,
            PetState.KISS,
        ):
            # 互动/侧面/碰面小动作素材统一按「朝右」入库；面向左侧时镜像
            if self.direction < 0:
                pixmap = pixmap.transformed(QTransform().scale(-1, 1))
        return display_state, pixmap

    def _refresh_pixmap(self) -> None:
        """从缓存取得或按当前屏幕设备像素比栅格化当前动画帧。"""

        display_state, pixmap = self._current_source()
        ratio = max(1.0, self.devicePixelRatioF())
        direction_key = (
            self.direction
            if display_state
            in (
                PetState.WALK,
                PetState.PEER_NOTICE,
                PetState.PEER_MEET,
                PetState.SIDE_STAND,
                PetState.WAVE,
                PetState.HAPPY,
                PetState.WINK,
                PetState.ENJOY,
                PetState.LAUGH,
                PetState.THINKING,
                PetState.HUG,
                PetState.KISS,
            )
            else 0
        )
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

        if self._peer_meeting_id or self._peer_approach_id:
            self._schedule_next_speech()
            return
        self._show_speech(self._speech_lines + self._custom_speech_lines)
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
        # 不 raise / 不激活，避免打断用户正在输入的其他应用
        self.speech_bubble.setVisible(True)
        self._bind_overlay_space(self.speech_bubble)
        # Cocoa 有时在 show 后才生成 NSWindow，再补钉一次
        QTimer.singleShot(0, lambda: self._bind_overlay_space(self.speech_bubble))
        QTimer.singleShot(40, lambda: self._bind_overlay_space(self.speech_bubble))
        linger_ms = 4800 if self._peer_meeting_id else 4300
        self.speech_hide_timer.start(linger_ms)

    def _show_state_speech(self, state: PetState) -> None:
        """为用户触发的动作显示与当前情境相符的随机对白。"""

        lines = self._state_speech_lines.get(state, ()) + self._custom_state_speech.get(state, ())
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
            self._hide_speech_bubble()

    def set_join_all_spaces(self, enabled: bool) -> None:
        """切换是否出现在全部桌面空间；关闭后只留在当前桌面。"""

        self._record_user_interaction()
        self.settings.join_all_spaces = bool(enabled)
        # 切换时先收起气泡，避免旧窗口行为残留在其他桌面
        self._hide_speech_bubble()
        self._hide_photo_bubble()
        self._apply_macos_space_preference()
        QTimer.singleShot(0, self._apply_macos_space_preference)

    def set_peer_interaction_enabled(self, enabled: bool) -> None:
        """开启或关闭与其他桌宠的靠近互动。"""

        self._record_user_interaction()
        self.settings.peer_interaction_enabled = bool(enabled)

    def _self_presence(self, *, busy: bool | None = None) -> PeerPresence:
        """生成本角色当前 presence 快照。"""

        if busy is None:
            # 走近途中不要标 busy，方便双方对向走过来
            if self._peer_approach_id or self._peer_meeting_id:
                now_busy = False
            else:
                now_busy = self._is_peer_busy()
        else:
            now_busy = busy
        return PeerPresence(
            character_id=self.branding.character_id,
            display_name=self.branding.display_name,
            x=float(self.x()),
            y=float(self.y()),
            width=int(self.width()),
            height=int(self.height()),
            facing=1 if self.direction >= 0 else -1,
            busy=now_busy,
            ts=time.time(),
            approaching_id=self._peer_approach_id or "",
            meeting_id=self._peer_meeting_id or "",
            chat_id=self._peer_chat_id,
            chat_started_at=self._peer_chat_started_at,
            sync_action=self._sync_action,
            sync_action_at=self._sync_action_at,
        )

    def _is_peer_busy(self) -> bool:
        """拖拽、睡觉、互动中等状态下不主动发起碰面。"""

        if self.dragging or not self.isVisible():
            return True
        if time.monotonic() < self._peer_busy_until:
            return True
        if self.state in {
            PetState.SLEEP,
            PetState.SLEEPY,
            PetState.DRAG,
            PetState.OUTFIT,
            PetState.SELFIE,
        }:
            return True
        return False

    def _publish_presence(self) -> None:
        """把当前位置写给其他桌宠进程。"""

        try:
            write_presence(self._self_presence())
        except OSError:
            pass

    def _face_peer(self, peer: PeerPresence) -> None:
        """把朝向锁到面朝对方，并立刻刷新镜像。"""

        me = self._self_presence(busy=False)
        desired = facing_for_meetup(me, peer)
        if desired != self.direction:
            self.direction = desired
            self._frame_index = 0
        self._refresh_pixmap()

    def _peer_tick(self) -> None:
        """定期广播 presence，并处理走近 / 碰面。"""

        self._publish_presence()
        if self._peer_meeting_id:
            self._continue_peer_hangout()
            return
        if self._peer_approach_id:
            self._continue_peer_approach()
            return
        peers = list_peers(exclude_id=self.branding.character_id)
        if not peers:
            return

        me = self._self_presence(busy=False)
        cooling = time.monotonic() < self._peer_interrupt_until
        # 1) 对方正走向我 / 正与我碰面 → 立刻知情并回应
        # （即使关了自动互动，也即使刚被拆散冷静中——否则会出现「只有单人反应」）
        for peer in peers:
            if peer.meeting_id == self.branding.character_id:
                if self.dragging:
                    return
                self._peer_interrupt_until = 0.0
                self._peer_reapproach = False
                if arrived_beside(me, peer):
                    self._play_peer_meetup(peer, manual=True)
                else:
                    self._start_peer_approach(peer, manual=False, reciprocal=True)
                return
            if peer.approaching_id == self.branding.character_id:
                if self.dragging:
                    return
                self._peer_interrupt_until = 0.0
                self._peer_reapproach = False
                self._start_peer_approach(peer, manual=False, reciprocal=True)
                return

        # 刚被拆散：冷静一会儿，别立刻又说「我过来」；到期后可随机再去找
        if cooling:
            return
        if self._peer_reapproach:
            self._peer_reapproach = False
            if not self.dragging and self.settings.peer_interaction_enabled:
                nearest = min(
                    peers,
                    key=lambda peer: (
                        abs(peer.center_x - me.center_x)
                        + abs(peer.center_y - me.center_y),
                        peer.character_id,
                    ),
                )
                if not nearest.busy or nearest.approaching_id or nearest.meeting_id:
                    if arrived_beside(me, nearest):
                        self._play_peer_meetup(nearest, manual=False)
                    elif within_approach_range(me, nearest):
                        self._start_peer_approach(nearest, manual=False)
                    return
        if not self.settings.peer_interaction_enabled:
            return
        if self._is_peer_busy():
            return
        # 附近时不要刷互动：碰面后冷却更久
        if time.monotonic() - self._last_peer_interaction_at < 120.0:
            return
        nearest = min(
            peers,
            key=lambda peer: (
                abs(peer.center_x - me.center_x) + abs(peer.center_y - me.center_y),
                peer.character_id,
            ),
        )
        if nearest.busy and not nearest.approaching_id and not nearest.meeting_id:
            return
        if arrived_beside(me, nearest):
            self._play_peer_meetup(nearest, manual=False)
            return
        if within_approach_range(me, nearest):
            self._start_peer_approach(nearest, manual=False)

    def _cancel_peer_approach(self) -> None:
        """取消正在进行的走近。"""

        self._peer_approach_id = None
        self._peer_approach_until = 0.0

    def _start_peer_approach(
        self,
        peer: PeerPresence,
        *,
        manual: bool,
        reciprocal: bool = False,
    ) -> None:
        """面向对方、说一句，然后斜向走过去碰面。"""

        if self.dragging:
            return
        if self._peer_approach_id == peer.character_id:
            return
        if self._peer_meeting_id:
            return
        self._peer_approach_id = peer.character_id
        self._peer_approach_until = time.monotonic() + (34.0 if manual else 24.0)
        if self.paused:
            self.set_paused(False)
        self._face_peer(peer)
        self._publish_presence()
        self.state_timer.stop()
        self.interaction_timer.stop()
        self._sequence_queue.clear()
        # 先「看见对方」，再走路
        self.set_state(PetState.PEER_NOTICE)
        self._face_peer(peer)
        self.state_timer.stop()
        # 主动找过去：打招呼；被找来：也回应一句（双向奔赴）
        if reciprocal:
            reply = self._peer_reply_speech
            if reply:
                self._show_speech(reply)
        else:
            notice = self._peer_notice_speech or self._peer_approach_speech
            if notice:
                self._show_speech(notice)
            if manual and self._peer_approach_speech:
                QTimer.singleShot(
                    1600,
                    lambda: self._show_speech(self._peer_approach_speech),
                )

        def begin_walk() -> None:
            if self._peer_approach_id != peer.character_id or self.dragging:
                return
            self.interaction_timer.stop()
            self.set_state(PetState.WALK)
            self._face_peer(peer)
            self.state_timer.stop()

        # 对方找来时更快起步去接
        QTimer.singleShot(500 if reciprocal else 900, begin_walk)

    def _continue_peer_approach(self) -> None:
        """走近过程中斜向追到对方身边，到位后再互动。"""

        if self.dragging:
            self._cancel_peer_approach()
            return
        if time.monotonic() > self._peer_approach_until:
            self._cancel_peer_approach()
            self._schedule(self.behavior.initial_idle())
            return
        peers = {
            peer.character_id: peer
            for peer in list_peers(exclude_id=self.branding.character_id)
        }
        peer = peers.get(self._peer_approach_id or "")
        if peer is None:
            self._cancel_peer_approach()
            self._show_speech(self._peer_miss_speech)
            self._schedule(self.behavior.initial_idle())
            return
        me = self._self_presence(busy=False)
        # 对方已开始碰面：贴到身边再加入，别隔空演完
        if peer.meeting_id == self.branding.character_id and arrived_beside(me, peer):
            self._cancel_peer_approach()
            self._play_peer_meetup(peer, manual=True)
            return
        if arrived_beside(me, peer):
            self._cancel_peer_approach()
            self._play_peer_meetup(peer, manual=True)
            return
        self._face_peer(peer)
        if self.state is not PetState.WALK and self.state is not PetState.PEER_NOTICE:
            self.set_state(PetState.WALK)
            self._face_peer(peer)
            self.state_timer.stop()

    def _snap_beside_peer(self, peer: PeerPresence) -> None:
        """对齐到并肩站位（固定稍远距离，拥抱也不再贴近）。"""

        me = self._self_presence(busy=False)
        target_x, target_y, _stand_left = stand_beside_target(me, peer)
        pos = self._constrained_position(QPoint(round(target_x), round(target_y)))
        self._movement_x = float(pos.x())
        self.move(pos)

    def _interrupt_peer_session(self, *, as_dragged: bool) -> None:
        """在一起/对话时被拆散：收束状态，说一句分离反应，并冷却一会儿。"""

        had_session = bool(
            self._peer_meeting_id or self._peer_approach_id or self._sync_action
        )
        self._peer_ease_to = None
        self._cancel_peer_approach()
        self._clear_synced_action()
        self._peer_meeting_id = None
        self._peer_hangout_until = 0.0
        self._peer_next_action_at = 0.0
        self._peer_speech_turn = -1
        self._peer_chat_id = -1
        self._peer_chat_started_at = 0.0
        self._peer_next_chat_at = 0.0
        self._last_peer_interaction_at = time.monotonic()
        # 有时拆散后仍想找回去：短冷静；否则完整冷却
        if had_session and random.random() < PEER_REAPPROACH_CHANCE:
            low, high = PEER_REAPPROACH_COOLDOWN_S
            self._peer_interrupt_until = time.monotonic() + random.uniform(low, high)
            self._peer_reapproach = True
        else:
            self._peer_interrupt_until = time.monotonic() + PEER_INTERRUPT_COOLDOWN_S
            self._peer_reapproach = False
        self._peer_busy_until = time.monotonic() + 6.0
        self._publish_presence()
        if had_session and self.settings.speech_enabled and not self.dragging:
            lines = PEER_INTERRUPT_SPEECH if as_dragged else PEER_SEPARATED_SPEECH
            self._show_speech(lines)
        elif had_session and self.settings.speech_enabled and as_dragged:
            # 拖拽中气泡也行，让被拉开的一方有反应
            self._show_speech(PEER_INTERRUPT_SPEECH)

    def _play_peer_meetup(self, peer: PeerPresence, *, manual: bool) -> None:
        """贴到身边后进入 hangout：偶发短对话 + 自己做动作，偶尔抱抱。"""

        if self.dragging:
            return
        if self._peer_meeting_id == peer.character_id:
            self._face_peer(peer)
            return
        self._cancel_peer_approach()
        self._peer_meeting_id = peer.character_id
        self._last_peer_interaction_at = time.monotonic()
        hangout_s = random.uniform(48.0, 72.0) if manual else random.uniform(42.0, 65.0)
        self._peer_hangout_until = time.monotonic() + hangout_s
        self._peer_busy_until = self._peer_hangout_until + 2.0
        self._peer_next_action_at = time.monotonic() + random.uniform(8.0, 14.0)
        self._peer_speech_turn = -1
        self._peer_chat_id = -1
        self._peer_chat_started_at = 0.0
        # 先抱抱/安静一会儿，再开第一段短对话；不要一直聊
        self._peer_next_chat_at = time.monotonic() + random.uniform(6.0, 11.0)
        self._peer_last_solo_at = 0.0
        self._peer_interrupt_until = 0.0
        self._peer_reapproach = False
        self.speech_timer.stop()
        self.state_timer.stop()
        self._snap_beside_peer(peer)
        self._face_peer(peer)
        action = (
            PetState.PEER_MEET
            if getattr(self, "_has_peer_meet_art", False)
            else PetState.HUG
        )
        self._begin_synced_action(peer, action)

    def _continue_peer_hangout(self) -> None:
        """碰面后待在对方身边一会儿：轮流对白、同步动作、侧面站姿。"""

        if self.dragging:
            self._interrupt_peer_session(as_dragged=True)
            return
        if time.monotonic() >= self._peer_hangout_until:
            self._finish_peer_meeting()
            return
        peers = {
            peer.character_id: peer
            for peer in list_peers(exclude_id=self.branding.character_id)
        }
        peer = peers.get(self._peer_meeting_id or "")
        if peer is None:
            self._interrupt_peer_session(as_dragged=False)
            self._schedule(self.behavior.initial_idle())
            return
        me = self._self_presence(busy=False)
        # 被拉开太远：当作中断，不要立刻追上去说「我过来」
        if not within_approach_range(me, peer, max_center_dist_px=520.0):
            self._interrupt_peer_session(as_dragged=False)
            self._schedule(self.behavior.initial_idle())
            return
        # 跟随导演已开的剧本；自己不当场连开新聊
        if not is_dialogue_director(self.branding.character_id, peer.character_id):
            if peer.chat_id >= 0 and peer.chat_started_at > 0:
                self._peer_chat_id = peer.chat_id
                self._peer_chat_started_at = peer.chat_started_at
        self._face_peer(peer)
        self.state_timer.stop()
        self.speech_timer.stop()
        if not self.interaction_timer.isActive() and self.state in (
            PetState.WALK,
            PetState.IDLE,
        ):
            if self.state is PetState.WALK or (
                self.state is PetState.IDLE and getattr(self, "_has_side_stand_art", False)
            ):
                self.set_state(self._hangout_idle_state())
                self._face_peer(peer)
        self._maybe_join_synced_action(peer)
        self._maybe_peer_hangout_action(peer)
        self._maybe_peer_hangout_speech(peer)

    def _hangout_idle_state(self) -> PetState:
        """hangout 安静站姿：有侧面图就侧身看对方。"""

        if getattr(self, "_has_side_stand_art", False):
            return PetState.SIDE_STAND
        return PetState.IDLE

    def _begin_synced_action(self, peer: PeerPresence, action: PetState) -> None:
        """发起同步抱抱：原地演，不再平移贴近或退开。"""

        wall = time.time()
        self._sync_action = action.value
        self._sync_action_at = wall
        self._sync_action_until = wall + SYNC_ACTION_HOLD_S
        self._peer_ease_to = None
        self._face_peer(peer)
        self._publish_presence()
        hold_ms = int(SYNC_ACTION_HOLD_S * 1000)
        self._show_emotion(action, hold_ms, with_speech=False)
        self._face_peer(peer)

    def _maybe_join_synced_action(self, peer: PeerPresence) -> None:
        """对方发起拥抱时一起抱；位置保持不变。"""

        if not peer.sync_action or peer.sync_action_at <= 0:
            if self._sync_action and time.time() < self._sync_action_until + 2.5:
                self._face_peer(peer)
            elif self._sync_action and time.time() >= self._sync_action_until:
                self._end_synced_action(peer)
            return

        shared_until = peer.sync_action_at + SYNC_ACTION_HOLD_S
        if time.time() > shared_until + 0.4:
            return
        already = (
            self._sync_action == peer.sync_action
            and abs(self._sync_action_at - peer.sync_action_at) < 0.05
        )
        self._sync_action = peer.sync_action
        self._sync_action_at = peer.sync_action_at
        self._sync_action_until = shared_until
        self._face_peer(peer)
        if already and self.interaction_timer.isActive():
            remaining = int((shared_until - time.time()) * 1000)
            if remaining > 200:
                self.interaction_timer.start(remaining)
            return
        try:
            action = PetState(peer.sync_action)
        except ValueError:
            action = PetState.PEER_MEET
        remaining_ms = max(700, int((shared_until - time.time()) * 1000))
        self._show_emotion(action, remaining_ms, with_speech=False)
        self._face_peer(peer)
        self._publish_presence()

    def _clear_synced_action(self) -> None:
        """清掉同步动作标记。"""

        self._sync_action = ""
        self._sync_action_at = 0.0
        self._sync_action_until = 0.0

    def _end_synced_action(self, peer: PeerPresence | None = None) -> None:
        """抱抱结束：原地回到 hangout 站姿，不再平移。"""

        self._clear_synced_action()
        if peer is not None:
            idle = self._hangout_idle_state()
            self.set_state(idle)
            self._face_peer(peer)
            self.state_timer.stop()
        self._publish_presence()

    def _maybe_peer_hangout_action(self, peer: PeerPresence) -> None:
        """大多做自己的小动作；偶尔同步抱抱，不要抱太勤。"""

        if self._sync_action and time.time() < self._sync_action_until:
            return
        if self._sync_action and time.time() >= self._sync_action_until:
            self._end_synced_action(peer)
        now = time.monotonic()
        if now < self._peer_next_action_at:
            return
        if self.interaction_timer.isActive() or self.dragging:
            return
        self._peer_next_action_at = now + random.uniform(9.0, 16.0)
        # 大约十分之一概率抱抱，其余自己开心/挥手/侧站
        if (
            is_dialogue_director(self.branding.character_id, peer.character_id)
            and random.random() < 0.12
        ):
            action = (
                PetState.PEER_MEET
                if getattr(self, "_has_peer_meet_art", False)
                else PetState.HUG
            )
            self._begin_synced_action(peer, action)
            self._peer_next_action_at = now + random.uniform(28.0, 42.0)
            return
        soft = [
            self._hangout_idle_state(),
            PetState.WAVE,
            PetState.HAPPY,
            PetState.WINK,
            PetState.ENJOY,
            PetState.LAUGH,
            PetState.THINKING,
        ]
        action = random.choice(soft)
        if action in (PetState.IDLE, PetState.SIDE_STAND):
            self.set_state(action)
            self._face_peer(peer)
            self.state_timer.stop()
            return
        self._show_emotion(action, random.randint(2200, 3200), with_speech=False)
        self._face_peer(peer)

    def _maybe_peer_hangout_speech(self, peer: PeerPresence) -> None:
        """短对话轮换快一点；平时大多安静，偶发自言自语更慢。"""

        if not self.settings.speech_enabled:
            return
        now_mono = time.monotonic()
        # 跟随对方已开的对话
        if not is_dialogue_director(self.branding.character_id, peer.character_id):
            if peer.chat_id >= 0 and peer.chat_started_at > 0:
                if (
                    self._peer_chat_id != peer.chat_id
                    or abs(self._peer_chat_started_at - peer.chat_started_at) > 0.05
                ):
                    self._peer_chat_id = peer.chat_id
                    self._peer_chat_started_at = peer.chat_started_at
                    self._peer_speech_turn = -1

        chat_id = self._peer_chat_id
        started = self._peer_chat_started_at
        if chat_id >= 0 and started > 0 and chat_id < len(self._peer_conversations):
            conversation = self._peer_conversations[chat_id]
            turn = dialogue_turn_index(started)
            if turn >= len(conversation):
                # 这段聊完了，安静一阵子
                self._peer_chat_id = -1
                self._peer_chat_started_at = 0.0
                self._peer_speech_turn = -1
                self._peer_next_chat_at = now_mono + random.uniform(22.0, 38.0)
                self._publish_presence()
                return
            if turn >= 0 and turn != self._peer_speech_turn:
                line = dialogue_line_for_turn(conversation, turn)
                if line is not None:
                    director = is_dialogue_director(
                        self.branding.character_id, peer.character_id
                    )
                    my_turn = (turn % 2 == 0) == director
                    if my_turn and (time.time() - started) % DIALOGUE_TURN_S <= 2.0:
                        if not self.speech_bubble.isVisible():
                            self._peer_speech_turn = turn
                            spoken = format_dialogue_line(
                                line,
                                me=self.branding.display_name,
                                peer=peer.display_name,
                            )
                            self._show_speech((spoken,))
            return

        # 没有进行中的对话：导演偶尔开一小段；否则很慢地自言自语一句
        if is_dialogue_director(self.branding.character_id, peer.character_id):
            if now_mono >= self._peer_next_chat_at and random.random() < 0.55:
                self._peer_chat_id = random.randrange(len(self._peer_conversations))
                self._peer_chat_started_at = time.time() + 0.4
                self._peer_speech_turn = -1
                self._publish_presence()
                return

        if self.speech_bubble.isVisible():
            return
        if now_mono - self._peer_last_solo_at < SOLO_MURMUR_MIN_GAP_S:
            return
        if random.random() > 0.08:
            return
        lines = self._peer_speech_lines
        if not lines:
            return
        self._peer_last_solo_at = now_mono
        self._show_speech(lines)

    def _finish_peer_meeting(self, *, resume: bool = True) -> None:
        """碰面 hangout 结束，恢复可再次走近。"""

        self._peer_meeting_id = None
        self._peer_hangout_until = 0.0
        self._peer_next_action_at = 0.0
        self._peer_speech_turn = -1
        self._peer_chat_id = -1
        self._peer_chat_started_at = 0.0
        self._peer_next_chat_at = 0.0
        self._peer_ease_to = None
        self._clear_synced_action()
        self._last_peer_interaction_at = time.monotonic()
        self._peer_busy_until = time.monotonic() + 8.0
        self._publish_presence()
        if not resume or self.dragging:
            return
        self._schedule(self.behavior.initial_idle())
        if self.settings.speech_enabled:
            self._schedule_next_speech()

    def trigger_peer_meetup(self) -> None:
        """菜单：看见对方后走过去玩一下。"""

        self._record_user_interaction()
        # 手动找人：清掉拆散冷静，让对方也能立刻回应
        self._peer_interrupt_until = 0.0
        self._peer_reapproach = False
        if self._peer_meeting_id:
            return
        if self._peer_approach_id:
            self._show_speech(self._peer_approach_speech or ("在路上了，马上到。",))
            return
        peers = list_peers(exclude_id=self.branding.character_id)
        if not peers:
            self._show_speech(self._peer_miss_speech)
            return
        me = self._self_presence(busy=False)
        nearest = min(
            peers,
            key=lambda peer: abs(peer.center_x - me.center_x)
            + abs(peer.center_y - me.center_y),
        )
        if arrived_beside(me, nearest):
            self._play_peer_meetup(nearest, manual=True)
            return
        if not within_approach_range(me, nearest, max_center_dist_px=2800.0):
            name = nearest.display_name
            self._show_speech((f"{name}好像不在附近，我先在这等你。",))
            return
        self._start_peer_approach(nearest, manual=True)

    def _hide_speech_bubble(self) -> None:
        """收起对白气泡并解除桌面附着。"""

        self.speech_hide_timer.stop()
        if hasattr(self, "speech_bubble"):
            self._unbind_overlay_space(self.speech_bubble)
            self.speech_bubble.hide()

    def _hide_photo_bubble(self) -> None:
        """收起自拍气泡并解除桌面附着。"""

        self.photo_timer.stop()
        if hasattr(self, "photo_bubble"):
            self._unbind_overlay_space(self.photo_bubble)
            self.photo_bubble.hide()

    def _bind_overlay_space(self, overlay: QWidget) -> None:
        """让对白/照片气泡与角色使用同一套桌面空间策略。"""

        if overlay is None or not overlay.isVisible():
            return
        join_all = self.settings.join_all_spaces
        # 只留当前桌面时，关掉 AlwaysShowToolWindow，避免气泡漂到别的 Space
        if sys.platform == "darwin":
            overlay.setAttribute(
                Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow,
                join_all,
            )
        _configure_macos_space_behavior(overlay, join_all_spaces=join_all)
        pet_handle = self.windowHandle()
        overlay_handle = overlay.windowHandle()
        if pet_handle is not None and overlay_handle is not None:
            overlay_handle.setTransientParent(pet_handle)
        # Cocoa 子窗口会跟着父窗口留在同一桌面，不会在当前活跃桌面「另起炉灶」
        _attach_macos_child_window(self, overlay)

    def _unbind_overlay_space(self, overlay: QWidget) -> None:
        """收起气泡时解除 Cocoa 附着。"""

        if overlay is None:
            return
        _detach_macos_child_window(self, overlay)

    def _apply_macos_space_preference(self) -> None:
        """把当前桌面空间偏好应用到角色窗口与气泡。"""

        join_all = self.settings.join_all_spaces
        self._macos_all_spaces_enabled = _configure_macos_space_behavior(
            self,
            join_all_spaces=join_all,
        )
        if hasattr(self, "speech_bubble"):
            self._bind_overlay_space(self.speech_bubble)
        if hasattr(self, "photo_bubble"):
            self._bind_overlay_space(self.photo_bubble)

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
        # hangout 时把气泡往外侧挪，减少两人头顶叠在一起
        if self._peer_meeting_id:
            peers = {
                peer.character_id: peer
                for peer in list_peers(exclude_id=self.branding.character_id)
            }
            peer = peers.get(self._peer_meeting_id)
            if peer is not None:
                shift = max(36, self.speech_bubble.width() // 3)
                if self.x() + self.width() / 2.0 <= peer.center_x:
                    x -= shift
                else:
                    x += shift
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
        self._apply_macos_space_preference()

    def moveEvent(self, event: QMoveEvent) -> None:
        """人物移动或被拖拽时同步更新对白位置。"""

        super().moveEvent(event)
        if hasattr(self, "speech_bubble") and self.speech_bubble.isVisible():
            self._position_speech_bubble()

    def hideEvent(self, event: QHideEvent) -> None:
        """隐藏角色时一并收起独立气泡窗口。"""

        self._hide_photo_bubble()
        self._hide_speech_bubble()
        clear_presence(self.branding.character_id)
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """退出时关闭独立气泡窗口，避免残留在桌面。"""

        self._hide_photo_bubble()
        self._hide_speech_bubble()
        clear_presence(self.branding.character_id)
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
        # hangout 期间不要自主走开 / 坐下
        if self._peer_meeting_id and time.monotonic() < self._peer_hangout_until:
            self.state_timer.stop()
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
        if self.dragging:
            self._peer_ease_to = None
            self._movement_x = float(self.x())
            return
        if (
            self.paused
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
        phase_factor = self._walk_motion_factors[
            self._frame_index % len(self._walk_motion_factors)
        ]
        speed = self._movement_speed_pixels_per_second() * phase_factor * elapsed

        # 走近对方：斜向追到身侧目标点，同时始终面朝对方
        if self._peer_approach_id:
            peers = {
                peer.character_id: peer
                for peer in list_peers(exclude_id=self.branding.character_id)
            }
            peer = peers.get(self._peer_approach_id)
            if peer is not None:
                me = self._self_presence(busy=False)
                target_x, target_y, _stand_left = stand_beside_target(me, peer)
                self.direction = facing_for_meetup(me, peer)
                dx = target_x - self._movement_x
                dy = target_y - float(self.y())
                dist = (dx * dx + dy * dy) ** 0.5
                if dist <= 1.0:
                    self._movement_x = target_x
                    new_y = target_y
                else:
                    step = min(speed * 1.15, dist)
                    self._movement_x += dx / dist * step
                    new_y = float(self.y()) + dy / dist * step
                self._movement_x = min(max(self._movement_x, float(area.left())), float(maximum))
                pos = self._constrained_position(
                    QPoint(round(self._movement_x), round(new_y))
                )
                self._movement_x = float(pos.x())
                self.move(pos)
                return

        direction = 1 if self.direction >= 0 else -1
        self._movement_x += direction * speed
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
        """播放自拍动作，并弹出用户登记的真人自拍照。"""

        if self.dragging:
            return
        self._record_user_interaction()
        self._show_emotion(PetState.SELFIE, 3200, with_speech=True)
        # 稍晚弹出原图，避开动作闪光/切帧的第一下
        QTimer.singleShot(450, self._show_photo_bubble)

    def trigger_state(self, state: PetState, duration_ms: int = 2200) -> None:
        """从菜单显式播放一个表情、日常或道具状态。"""

        if self.dragging:
            return
        self._record_user_interaction()
        self._show_emotion(state, duration_ms, with_speech=True)

    def trigger_food(self, state: PetState) -> None:
        """播放吃东西状态并立即降低饥饿度。"""

        if state not in (PetState.CAKE, PetState.BURGER, PetState.HUNGRY):
            raise ValueError("食物互动只接受蛋糕、汉堡或烤串状态")
        amount = 32 if state is PetState.CAKE else 48
        self.mood.receive_food(amount)
        self.trigger_state(state, 3000)

    def trigger_corgi(self) -> None:
        """连续播放摸柯基和接小爪陪玩的两段动作，并降低无聊度。"""

        self.mood.receive_play()
        self.trigger_state(PetState.CORGI_PLAY, 3400)

    def trigger_outfit_change(self) -> None:
        """快速切到新衣服，并在新造型上停留更久。"""

        if self.dragging:
            return
        self._record_user_interaction()
        chosen = random.choice(self._outfit_options)
        if self.branding.is_custom:
            # 定制角色不要长前奏：最多闪一下，再长时间展示新装
            flash = self._outfit_twirl_frames[:1] if self._outfit_twirl_frames else []
            self._pixmaps[PetState.OUTFIT] = [*flash, chosen]
            hold_ms = 7500
        else:
            self._pixmaps[PetState.OUTFIT] = [*self._outfit_twirl_frames, chosen]
            hold_ms = 4800
        self._render_cache.clear()
        self._mask_cache.clear()
        self._show_emotion(PetState.OUTFIT, hold_ms)
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
        self.photo_bubble.setVisible(True)
        self._bind_overlay_space(self.photo_bubble)
        QTimer.singleShot(0, lambda: self._bind_overlay_space(self.photo_bubble))
        QTimer.singleShot(40, lambda: self._bind_overlay_space(self.photo_bubble))
        self.photo_timer.start(3800)

    def _scaled_selfie_photo(self, ratio: float) -> QPixmap:
        """按设备像素比生成照片缩略图，避免高 DPI 屏幕二次放大导致模糊。"""

        if self._selfie_photo.isNull():
            return QPixmap()
        ratio = max(1.0, ratio)
        photo = self._selfie_photo.scaled(
            max(1, round(220 * ratio)),
            max(1, round(300 * ratio)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        photo.setDevicePixelRatio(ratio)
        return photo

    def _finish_interaction(self) -> None:
        """结束互动；若有连播队列则继续下一段，否则恢复自主待机。"""

        if self.dragging:
            return
        if self._sequence_queue:
            state, duration_ms = self._sequence_queue.popleft()
            self._show_emotion(state, duration_ms, with_speech=True)
            return
        # hangout 中：动作播完就安静站着，不要立刻走开
        if self._peer_meeting_id and time.monotonic() < self._peer_hangout_until:
            peers = {
                peer.character_id: peer
                for peer in list_peers(exclude_id=self.branding.character_id)
            }
            peer = peers.get(self._peer_meeting_id)
            # 同步拥抱未到共享结束点：继续保持姿势
            if self._sync_action and time.time() < self._sync_action_until:
                remaining = int((self._sync_action_until - time.time()) * 1000)
                if remaining > 200:
                    try:
                        action = PetState(self._sync_action)
                    except ValueError:
                        action = PetState.PEER_MEET
                    self.set_state(action)
                    self.interaction_timer.start(remaining)
                    return
            if self._sync_action:
                self._end_synced_action(peer)
                return
            idle = (
                PetState.SIDE_STAND
                if getattr(self, "_has_side_stand_art", False)
                else PetState.IDLE
            )
            self.set_state(idle)
            self.state_timer.stop()
            if peer is not None:
                self._face_peer(peer)
            return
        self._schedule(self.behavior.initial_idle())

    def trigger_sequence(self, steps: list[tuple[PetState, int]]) -> None:
        """按顺序播放多个相近动作，形成连播动图效果。"""

        if self.dragging or not steps:
            return
        self._record_user_interaction()
        first_state, first_duration = steps[0]
        self._sequence_queue = deque(steps[1:])
        self._show_emotion(first_state, first_duration, with_speech=True)

    def _add_status_panel(self, menu: QMenu) -> None:
        """在动作菜单顶部加入当前状态和四色心情进度条。"""

        panel = QWidget(menu)
        panel.setObjectName("moodPanel")
        layout = QGridLayout(panel)
        layout.setContentsMargins(12, 10, 12, 9)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(5)
        theme = self.branding.theme

        title = QLabel(
            f"{self.branding.status_prefix}"
            f"{self._state_labels.get(self.state, self.state.value)}",
            panel,
        )
        title.setObjectName("moodTitle")
        layout.addWidget(title, 0, 0, 1, 3)

        mood_rows = (
            ("默契", self.mood.affinity, theme.affinity),
            ("精力", self.mood.energy, theme.energy),
            ("无聊", self.mood.boredom, theme.boredom),
            ("饥饿", self.mood.hunger, theme.hunger),
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
                f"QProgressBar {{ background: {theme.bar_track}; border: none; border-radius: 4px; }}"
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
        """构建角色窗口的右键菜单；定制角色使用 branding 菜单。"""

        menu = QMenu(self)
        menu.setMinimumWidth(246)
        theme = self.branding.theme
        menu.setStyleSheet(
            f"QMenu {{ background: {theme.menu_bg}; color: #303746; border: 1px solid {theme.menu_border}; "
            "border-radius: 8px; padding: 6px; }"
            "QMenu::item { padding: 7px 26px 7px 11px; margin: 1px 2px; "
            "border-radius: 6px; }"
            f"QMenu::item:selected {{ background: {theme.menu_selected}; color: {theme.title}; }}"
            f"QMenu::item:disabled {{ color: {theme.muted}; }}"
            f"QMenu::separator {{ height: 1px; background: {theme.menu_separator}; margin: 6px 8px; }}"
            f"QWidget#moodPanel {{ background: {theme.menu_bg}; }}"
            f"QLabel#moodTitle {{ color: {theme.title}; font-weight: 700; padding-bottom: 3px; }}"
            f"QLabel#moodName {{ color: {theme.muted}; font-size: 11px; }}"
            f"QLabel#moodValue {{ color: {theme.muted}; font-size: 10px; min-width: 22px; }}"
        )
        self._add_status_panel(menu)
        pause_action = QAction("恢复跑动" if self.paused else "暂停跑动", self)
        pause_action.triggered.connect(lambda: self.set_paused(not self.paused))
        menu.addAction(pause_action)

        menu_cfg = self.branding.menu
        greet_label = str(menu_cfg.get("greet", "和小u打招呼"))
        listen_label = str(menu_cfg.get("listen", "听小u说句话"))
        speech_off = str(menu_cfg.get("speech_off", "关闭小u说话"))
        speech_on = str(menu_cfg.get("speech_on", "开启小u说话"))

        interact_action = QAction(greet_label, self)
        interact_action.triggered.connect(self.trigger_interaction)
        menu.addAction(interact_action)
        speech_action = QAction(listen_label, self)
        speech_action.triggered.connect(self.trigger_speech)
        speech_action.setEnabled(self.settings.speech_enabled)
        menu.addAction(speech_action)
        speech_toggle_action = QAction(
            speech_off if self.settings.speech_enabled else speech_on,
            self,
        )
        speech_toggle_action.triggered.connect(
            lambda: self.set_speech_enabled(not self.settings.speech_enabled)
        )
        menu.addAction(speech_toggle_action)

        peer_toggle = QAction("靠近时和对方互动", self)
        peer_toggle.setCheckable(True)
        peer_toggle.setChecked(self.settings.peer_interaction_enabled)
        peer_toggle.triggered.connect(
            lambda checked=False: self.set_peer_interaction_enabled(checked)
        )
        menu.addAction(peer_toggle)
        peer_meet = QAction("找对方玩一下", self)
        peer_meet.triggered.connect(self.trigger_peer_meetup)
        menu.addAction(peer_meet)

        def add_state_action(
            target_menu: QMenu,
            label: str,
            state: PetState,
            duration_ms: int = 2200,
            *,
            food: bool = False,
        ) -> None:
            action = QAction(label, self)
            if food:
                action.triggered.connect(
                    lambda _checked=False, value=state: self.trigger_food(value)
                )
            else:
                action.triggered.connect(
                    lambda _checked=False, value=state, duration=duration_ms: self.trigger_state(
                        value,
                        duration,
                    )
                )
            target_menu.addAction(action)

        def add_sequence_action(
            target_menu: QMenu,
            label: str,
            steps: list[tuple[PetState, int]],
        ) -> None:
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, value=list(steps): self.trigger_sequence(value)
            )
            target_menu.addAction(action)

        if self.branding.is_custom:
            def add_menu_item(target_menu: QMenu, item: dict) -> None:
                label = str(item.get("label", "")).strip()
                if not label:
                    return
                if item.get("outfit"):
                    action = QAction(label, self)
                    action.triggered.connect(self.trigger_outfit_change)
                    target_menu.addAction(action)
                    return
                if "sequence" in item:
                    steps: list[tuple[PetState, int]] = []
                    for step in item.get("sequence", []):
                        state_name = str(step.get("state", ""))
                        if state_name not in PetState._value2member_map_:
                            continue
                        steps.append(
                            (
                                PetState(state_name),
                                int(step.get("duration_ms", 1000)),
                            )
                        )
                    if steps:
                        add_sequence_action(target_menu, label, steps)
                    return
                state_name = str(item.get("state", ""))
                if state_name not in PetState._value2member_map_:
                    return
                state = PetState(state_name)
                if state is PetState.SELFIE:
                    action = QAction(label, self)
                    action.triggered.connect(self.trigger_selfie)
                    target_menu.addAction(action)
                    return
                add_state_action(
                    target_menu,
                    label,
                    state,
                    int(item.get("duration_ms", 2200)),
                    food=bool(item.get("food")),
                )

            for item in menu_cfg.get("top_actions", []):
                add_menu_item(menu, item)
            for group in menu_cfg.get("groups", []):
                submenu = menu.addMenu(str(group.get("title", "动作")))
                for item in group.get("items", []):
                    add_menu_item(submenu, item)
        else:
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
            add_state_action(food_menu, "吃蛋糕满足", PetState.CAKE, food=True)
            add_state_action(food_menu, "大口吃汉堡", PetState.BURGER, food=True)

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

        size_menu = menu.addMenu(self.branding.size_menu_label)
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
        space_action = QAction("只留在当前桌面", self)
        space_action.setCheckable(True)
        space_action.setChecked(not self.settings.join_all_spaces)
        space_action.triggered.connect(
            lambda checked=False: self.set_join_all_spaces(not checked)
        )
        menu.addAction(space_action)
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
                # 在一起/走近时被拖走：走中断流程，别事后立刻「我过来」
                if self._peer_meeting_id or self._peer_approach_id or self._sync_action:
                    self._interrupt_peer_session(as_dragged=True)
                else:
                    self._cancel_peer_approach()
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
