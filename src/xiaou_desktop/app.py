"""
本模块管理桌面角色应用生命周期、系统托盘菜单和退出时的位置保存。

职责范围：
- 创建或复用 QApplication；
- 在创建应用前启用适合不同显示器缩放比例的高 DPI 舍入策略；
- 创建小u人物窗口和 QSystemTrayIcon；
- 连接显示、隐藏、暂停跑动、互动和退出动作；
- 退出前将窗口位置和用户选择的尺寸写入设置文件；
- 为自动验证提供定时退出的 smoke-test 参数。

Agent 快速定位：
- 生命周期封装位于 DesktopPetApplication；
- 托盘菜单构建位于 _create_tray()；
- 持久化与退出位于 quit()；
- 外部调用入口位于 run()。

输入为可选的无界面冒烟测试时长，输出为 Qt 事件循环退出码。
副作用包括创建桌面窗口、托盘图标和用户设置文件；不修改项目默认配置或原始素材。
"""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .branding import load_branding
from .config import PetSettings, load_settings, save_settings
from .resources import resource_path
from .window import PetWindow


def _macos_accessory_activation_policy() -> None:
    """让应用以 Accessory 策略运行，对白弹出时不抢走当前输入焦点。"""

    if sys.platform != "darwin":
        return
    try:
        objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        message_address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        if message_address is None:
            return
        send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            message_address
        )
        send_int = ctypes.CFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_long,
        )(message_address)
        ns_app_class = ctypes.c_void_p(objc.objc_getClass(b"NSApplication"))
        shared = send(ns_app_class, ctypes.c_void_p(objc.sel_registerName(b"sharedApplication")))
        if not shared:
            return
        # NSApplicationActivationPolicyAccessory = 1
        send_int(
            shared,
            ctypes.c_void_p(objc.sel_registerName(b"setActivationPolicy:")),
            1,
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return


class DesktopPetApplication:
    """封装窗口、托盘与持久化状态的桌面角色应用。"""

    def __init__(self, settings: PetSettings | None = None) -> None:
        if QApplication.instance() is None:
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
        self.branding = load_branding()
        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        self.qt_app.setApplicationName(self.branding.display_name)
        self.qt_app.setApplicationDisplayName(self.branding.display_name)
        self.qt_app.setQuitOnLastWindowClosed(False)
        _macos_accessory_activation_policy()
        self.settings = settings or load_settings()
        self.window = PetWindow(self.settings)
        self.window.quit_requested.connect(self.quit)
        self.tray = self._create_tray()

    def _create_tray(self) -> QSystemTrayIcon:
        """创建系统托盘图标及其操作菜单。"""

        name = self.branding.display_name
        icon_path = "assets/icons/pet.png"
        try:
            from .resources import resource_path as _rp

            custom_icon = _rp("user_assets/pet/icon.png")
            icon_path = str(custom_icon)
        except FileNotFoundError:
            icon_path = str(resource_path("assets/icons/pet.png"))
        icon = QIcon(icon_path)
        tray = QSystemTrayIcon(icon, self.qt_app)
        tray.setToolTip(name)
        menu = QMenu()

        show_action = QAction(f"显示{name}", menu)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)

        interact_action = QAction(
            str(self.branding.menu.get("greet", f"和{name}打招呼")),
            menu,
        )
        interact_action.triggered.connect(self.window.trigger_interaction)
        menu.addAction(interact_action)

        selfie_action = QAction("自拍一下", menu)
        selfie_action.triggered.connect(self.window.trigger_selfie)
        menu.addAction(selfie_action)

        pause_action = QAction("暂停/恢复跑动", menu)
        pause_action.triggered.connect(
            lambda: self.window.set_paused(not self.window.paused)
        )
        menu.addAction(pause_action)

        hide_action = QAction(f"隐藏{name}", menu)
        hide_action.triggered.connect(self.window.hide)
        menu.addAction(hide_action)
        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        self.tray_menu = menu
        tray.activated.connect(self._tray_activated)
        return tray

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """单击或双击托盘图标时显示角色。"""

        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def show_window(self) -> None:
        """显示角色并将其提升到前台。"""

        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def start(self, smoke_test_ms: int | None = None) -> int:
        """显示应用并进入事件循环；可选定时退出用于自动验证。"""

        self.window.place_at_start()
        self.show_window()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        if smoke_test_ms is not None:
            QTimer.singleShot(max(1, smoke_test_ms), self.quit)
        return self.qt_app.exec()

    def quit(self) -> None:
        """保存窗口位置、隐藏托盘并退出应用。"""

        self.settings.start_x = self.window.x()
        self.settings.start_y = self.window.y()
        try:
            save_settings(self.settings)
        finally:
            self.tray.hide()
            self.window.close()
            self.qt_app.quit()


def run(smoke_test_ms: int | None = None) -> int:
    """创建并运行桌面角色应用。"""

    return DesktopPetApplication().start(smoke_test_ms=smoke_test_ms)
