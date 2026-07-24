"""
本模块提供桌面角色的纯逻辑行为状态机，不直接创建窗口或访问文件。

职责范围：
- 定义待机、走路、休息、饮食、表情、道具互动、柯基互动与换装状态；
- 维护默契、精力、无聊度和饥饿度四个轻量状态数值；
- 根据跑动开关和当前情绪选择下一生活状态及持续时间；
- 计算到达屏幕边界后的新位置和行走方向。

Agent 快速定位：
- 状态枚举位于 PetState；
- 自主状态选择位于 BehaviorModel.next_autonomous_state()；
- 水平边界计算位于 BehaviorModel.advance_horizontal()。

输入为当前状态、配置时长、坐标和边界，输出为新的状态、时长、坐标或方向。
模块只依赖 Python 标准库，不执行文件写入、网络请求或 GUI 操作，便于单元测试。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from .config import PetSettings


class PetState(str, Enum):
    """桌面角色可显示的行为状态。"""

    IDLE = "idle"
    WALK = "walk"
    SIT = "sit"
    SLEEP = "sleep"
    WAVE = "wave"
    HAPPY = "happy"
    SHY = "shy"
    SURPRISED = "surprised"
    ANNOYED = "annoyed"
    SLEEPY = "sleepy"
    CURIOUS = "curious"
    SELFIE = "selfie"
    DRAG = "drag"
    POUT = "pout"
    LAUGH = "laugh"
    ENJOY = "enjoy"
    KISS = "kiss"
    SAD = "sad"
    BORED = "bored"
    HUNGRY = "hungry"
    THINKING = "thinking"
    WAKE = "wake"
    CAKE = "cake"
    PHONE_GIGGLE = "phone_giggle"
    WINK = "wink"
    WORK = "work"
    CORGI_PET = "corgi_pet"
    CORGI_PLAY = "corgi_play"
    STARRY = "starry"
    BURGER = "burger"
    CAMERA = "camera"
    EMPEROR = "emperor"
    HUG = "hug"
    SHY_FRONT = "shy_front"
    OUTFIT = "outfit"
    # 侧面站姿：看向对方 / 日常侧身待机（素材可选）
    SIDE_STAND = "side_stand"
    # 双人互动：看见对方 / 碰面互动（素材可选；缺失时回退到相近表情）
    PEER_NOTICE = "peer_notice"
    PEER_MEET = "peer_meet"


@dataclass(frozen=True)
class StateDecision:
    """一次自主状态选择的结果。"""

    state: PetState
    duration_ms: int


@dataclass
class PetMood:
    """保存并约束角色的默契、精力、无聊度和饥饿度。"""

    affinity: int = 50
    energy: int = 75
    boredom: int = 10
    hunger: int = 25

    def _clamp(self) -> None:
        """把四个情绪数值限制在 0 到 100。"""

        self.affinity = min(100, max(0, self.affinity))
        self.energy = min(100, max(0, self.energy))
        self.boredom = min(100, max(0, self.boredom))
        self.hunger = min(100, max(0, self.hunger))

    def receive_affection(self) -> None:
        """记录摸头或友好点击带来的默契反馈。"""

        self.affinity += 5
        self.energy -= 1
        self.boredom -= 18
        self.hunger += 1
        self._clamp()

    def receive_poke(self, repeated: bool) -> None:
        """记录身体戳击；连续戳击会轻微降低默契。"""

        self.affinity -= 2 if repeated else 0
        self.energy -= 2
        self.boredom -= 8
        self.hunger += 1
        self._clamp()

    def receive_drag(self) -> None:
        """记录一次拖拽带来的精力消耗和解闷效果。"""

        self.energy -= 3
        self.boredom -= 12
        self.hunger += 2
        self._clamp()

    def receive_food(self, amount: int = 38) -> None:
        """记录吃东西带来的饱腹、精力和满足感。"""

        self.hunger -= amount
        self.energy += 4
        self.boredom -= 8
        self._clamp()

    def receive_play(self) -> None:
        """记录陪柯基或主动互动带来的解闷效果。"""

        self.affinity += 2
        self.energy -= 3
        self.boredom -= 24
        self.hunger += 2
        self._clamp()

    def pass_time(self, state: PetState) -> None:
        """在自主状态到期时更新精力和无聊度。"""

        if state is PetState.SLEEP:
            self.energy += 12
            self.boredom -= 5
            self.hunger += 4
        elif state is PetState.SIT:
            self.energy += 3
            self.boredom += 2
            self.hunger += 2
        elif state in (PetState.CAKE, PetState.BURGER):
            self.receive_food()
            return
        elif state in (
            PetState.PHONE_GIGGLE,
            PetState.CORGI_PET,
            PetState.CORGI_PLAY,
            PetState.LAUGH,
            PetState.ENJOY,
        ):
            self.energy -= 2
            self.boredom -= 12
            self.hunger += 2
        elif state is PetState.WORK:
            self.energy -= 4
            self.boredom += 5
            self.hunger += 3
        else:
            self.energy -= 1
            self.boredom += 4
            self.hunger += 3
        self._clamp()


class BehaviorModel:
    """封装可注入随机源的桌面角色行为决策。"""

    def __init__(
        self,
        settings: PetSettings,
        random_source: random.Random | None = None,
    ) -> None:
        self.settings = settings
        self.random = random_source or random.Random()

    def initial_idle(self) -> StateDecision:
        """返回初始待机状态和随机持续时间。"""

        return StateDecision(
            PetState.IDLE,
            self.random.randint(
                self.settings.idle_min_ms,
                self.settings.idle_max_ms,
            ),
        )

    def next_autonomous_state(
        self,
        current: PetState,
        allow_walk: bool = True,
        mood: PetMood | None = None,
    ) -> StateDecision:
        """按当前状态、跑动开关和情绪选择下一生活状态及持续时间。"""

        if current is PetState.WALK:
            if mood is not None:
                state = self.random.choices(
                    (PetState.IDLE, PetState.SIT, PetState.SELFIE, PetState.WINK),
                    weights=(0.36, 0.28, 0.18, 0.18),
                    k=1,
                )[0]
                return self._action_decision(state)
            state = self.random.choices(
                (PetState.IDLE, PetState.SIT, PetState.SELFIE),
                weights=(0.42, 0.33, 0.25),
                k=1,
            )[0]
            return self._action_decision(state)
        if current is not PetState.IDLE:
            return self.initial_idle()
        if mood is not None:
            if mood.hunger >= 75:
                return self._action_decision(PetState.HUNGRY)
            if mood.energy <= 22:
                return self._action_decision(PetState.SLEEPY)
            if mood.hunger >= 55:
                state = self.random.choices(
                    (PetState.HUNGRY, PetState.CAKE, PetState.BURGER),
                    weights=(0.42, 0.30, 0.28),
                    k=1,
                )[0]
                return self._action_decision(state)
            if mood.boredom >= 72:
                state = self.random.choices(
                    (
                        PetState.BORED,
                        PetState.PHONE_GIGGLE,
                        PetState.WORK,
                        PetState.CORGI_PLAY,
                    ),
                    weights=(0.38, 0.24, 0.16, 0.22),
                    k=1,
                )[0]
                return self._action_decision(state)

            states = [
                PetState.WALK,
                PetState.SIT,
                PetState.SELFIE,
                PetState.WINK,
                PetState.ENJOY,
                PetState.THINKING,
                PetState.STARRY,
                PetState.HUG,
                PetState.PHONE_GIGGLE,
                PetState.CAKE,
                PetState.CORGI_PET,
                PetState.CAMERA,
                PetState.EMPEROR,
            ]
            weights = [
                0.24,
                0.13,
                0.07,
                0.08,
                0.08,
                0.08,
                0.07,
                0.07,
                0.09,
                0.05,
                0.05,
                0.04,
                0.03,
            ]
            states.append(PetState.SHY_FRONT)
            weights.append(0.04)
            # 侧面站姿：有素材时看向一侧；无素材会回退 idle
            states.append(PetState.SIDE_STAND)
            weights.append(0.12)
            if not allow_walk:
                states.pop(0)
                weights.pop(0)
                states.append(PetState.SLEEP)
                weights.append(0.12)
            if mood.affinity >= 70:
                states.extend((PetState.LAUGH, PetState.SHY_FRONT))
                weights.extend((0.11, 0.10))
            elif mood.affinity <= 35:
                states.extend((PetState.POUT, PetState.SAD))
                weights.extend((0.13, 0.11))
            state = self.random.choices(states, weights=weights, k=1)[0]
            return self._action_decision(state)
        if allow_walk:
            states = (PetState.WALK, PetState.SIT, PetState.SELFIE)
            weights = (0.56, 0.27, 0.17)
        else:
            states = (PetState.IDLE, PetState.SIT, PetState.SELFIE, PetState.SLEEP)
            weights = (0.32, 0.30, 0.23, 0.15)
        state = self.random.choices(states, weights=weights, k=1)[0]
        return self._action_decision(state)

    def _action_decision(self, state: PetState) -> StateDecision:
        """为选中的生活状态附加统一范围内的随机持续时间。"""

        return StateDecision(
            state,
            self.random.randint(
                self.settings.action_min_ms,
                self.settings.action_max_ms,
            ),
        )

    @staticmethod
    def advance_horizontal(
        x: int,
        direction: int,
        step: int,
        minimum: int,
        maximum: int,
    ) -> tuple[int, int]:
        """移动一步并在边界处夹紧位置、反转方向。"""

        normalized_direction = 1 if direction >= 0 else -1
        next_x = x + normalized_direction * step
        if next_x <= minimum:
            return minimum, 1
        if next_x >= maximum:
            return maximum, -1
        return next_x, normalized_direction
