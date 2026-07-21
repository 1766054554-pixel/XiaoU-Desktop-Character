"""
本模块测试桌面角色纯逻辑行为模型的扩展状态、四项情绪选择与屏幕边界处理。

测试输入为固定配置、伪随机源和坐标边界，输出为可重复断言的状态及位置。
测试不创建真实窗口、不读写用户文件，也不访问网络。
"""

from xiaou_desktop.behavior import BehaviorModel, PetMood, PetState
from xiaou_desktop.config import PetSettings


class ChoiceRandom:
    """按指定索引返回候选状态，并让持续时间固定为下界。"""

    def __init__(self, index: int) -> None:
        self.index = index

    def choices(self, population, weights, k):
        return [population[self.index]]

    @staticmethod
    def randint(minimum: int, _maximum: int) -> int:
        return minimum


class CaptureRandom(ChoiceRandom):
    """记录一次候选集合，便于验证不同发行版本的自主动作边界。"""

    def __init__(self) -> None:
        super().__init__(0)
        self.population = ()

    def choices(self, population, weights, k):
        self.population = tuple(population)
        return super().choices(population, weights, k)


def test_walk_can_end_in_idle_sit_or_selfie() -> None:
    settings = PetSettings(action_min_ms=2000, action_max_ms=2000)
    states = []
    for index in range(3):
        model = BehaviorModel(settings, ChoiceRandom(index))
        states.append(model.next_autonomous_state(PetState.WALK).state)

    assert states == [PetState.IDLE, PetState.SIT, PetState.SELFIE]


def test_paused_life_choices_never_include_walk() -> None:
    settings = PetSettings()
    states = []
    for index in range(4):
        model = BehaviorModel(settings, ChoiceRandom(index))
        decision = model.next_autonomous_state(PetState.IDLE, allow_walk=False)
        states.append(decision.state)

    assert states == [PetState.IDLE, PetState.SIT, PetState.SELFIE, PetState.SLEEP]


def test_advance_horizontal_reverses_at_both_edges() -> None:
    assert BehaviorModel.advance_horizontal(2, -1, 4, 0, 100) == (0, 1)
    assert BehaviorModel.advance_horizontal(98, 1, 4, 0, 100) == (100, -1)


def test_advance_horizontal_keeps_direction_inside_bounds() -> None:
    assert BehaviorModel.advance_horizontal(50, 1, 3, 0, 100) == (53, 1)
    assert BehaviorModel.advance_horizontal(50, -1, 3, 0, 100) == (47, -1)


def test_mood_reacts_to_affection_repeated_pokes_and_sleep() -> None:
    """友好互动、连续戳击和睡眠应分别改变对应的状态数值。"""

    mood = PetMood(affinity=50, energy=50, boredom=50)
    mood.receive_affection()
    assert (mood.affinity, mood.energy, mood.boredom) == (55, 49, 32)

    mood.receive_poke(repeated=True)
    assert (mood.affinity, mood.energy, mood.boredom) == (53, 47, 24)

    mood.pass_time(PetState.SLEEP)
    assert (mood.affinity, mood.energy, mood.boredom) == (53, 59, 19)


def test_hunger_triggers_hungry_state_and_food_reduces_it() -> None:
    """高饥饿度应自动表达饥饿，吃汉堡后应明显恢复。"""

    settings = PetSettings(action_min_ms=2000, action_max_ms=2000)
    mood = PetMood(hunger=80)
    model = BehaviorModel(settings, ChoiceRandom(0))

    decision = model.next_autonomous_state(PetState.IDLE, mood=mood)
    assert decision.state is PetState.HUNGRY

    mood.receive_food(48)
    assert mood.hunger == 32
    assert mood.energy == 79


def test_low_energy_and_high_boredom_choose_matching_states() -> None:
    """困倦和无聊阈值应优先于普通随机生活状态。"""

    settings = PetSettings()
    model = BehaviorModel(settings, ChoiceRandom(0))

    tired = model.next_autonomous_state(
        PetState.IDLE,
        mood=PetMood(energy=18, hunger=20),
    )
    bored = model.next_autonomous_state(
        PetState.IDLE,
        mood=PetMood(energy=70, boredom=80, hunger=20),
    )

    assert tired.state is PetState.SLEEPY
    assert bored.state is PetState.BORED


def test_autonomous_actions_exclude_kiss_but_keep_casual_poses() -> None:
    """公开角色可随机伸懒腰或不好意思，但不得自主播放亲亲。"""

    random_source = CaptureRandom()
    model = BehaviorModel(PetSettings(), random_source)

    model.next_autonomous_state(
        PetState.IDLE,
        mood=PetMood(affinity=100, energy=75, boredom=10, hunger=25),
    )

    assert PetState.KISS not in random_source.population
    assert PetState.HUG in random_source.population
    assert PetState.SHY_FRONT in random_source.population
