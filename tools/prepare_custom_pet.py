"""
本模块把已确认人物的本地 3x2 像素图集整理成完整的私有桌面角色素材。

职责范围：
- 按固定格序拆分表情、生活、道具、正面互动与换装图集；
- 使用最近邻缩放把站姿、坐姿和睡姿放入统一 560x500 透明画布；
- 保留用户已确认的 12 帧慢速走路，不重新插帧或修改步态；
- 生成全部行为状态、18 套换装选项、托盘图标和私有素材清单；
- 只写入被 Git 忽略的 user_assets/pet，不复制真人原图到公开 assets。

Agent 快速定位：
- 图集格序由 SHEET_LAYOUTS 定义；
- 不同姿态的目标高度由 TARGET_HEIGHTS 定义；
- 私有素材清单组装位于 prepare_custom_pet()；
- 命令行入口位于 main()。

输入为 user_assets/source_sheets 下已经去除绿色背景的 RGBA PNG，输出为
user_assets/pet 下的透明 PNG 与 manifest.json。模块不访问网络、不修改原图，
并在执行前验证标准人物和走路两个人工确认门禁。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from xiaou_desktop.workflow import require_custom_pet_approved


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "user_assets" / "source_sheets"
DEFAULT_OUTPUT = PROJECT_ROOT / "user_assets" / "pet"
CANVAS_SIZE = (560, 500)
PADDING = 30
STANDING_HEIGHT = 420
VISIBLE_ALPHA_THRESHOLD = 64
WALK_MOTION_FACTORS = (0.8, 0.8, 1.0, 1.0, 1.2, 1.2) * 2


@dataclass(frozen=True)
class SheetLayout:
    """描述一个 3x2 图集文件及其从左到右、从上到下的格名。"""

    filename: str
    names: tuple[str, str, str, str, str, str]


SHEET_LAYOUTS = (
    SheetLayout(
        "expressions-sheet-alpha.png",
        ("pout", "laugh", "enjoy", "friendly_gesture", "surprised", "sad"),
    ),
    SheetLayout(
        "life-states-sheet-alpha.png",
        ("bored", "hungry", "angry", "thinking", "sleepy", "sleep_pose"),
    ),
    SheetLayout(
        "prop-actions-sheet-alpha.png",
        ("cake", "phone_giggle", "sit_pose", "wake", "drag_pose", "selfie_pose"),
    ),
    SheetLayout(
        "extra-interactions-sheet-alpha.png",
        ("wink", "work", "corgi_pet", "corgi_play", "wave", "idle_pose"),
    ),
    SheetLayout(
        "front-facing-specials-sheet-alpha.png",
        ("starry", "burger", "camera", "emperor", "stretch", "bashful_front"),
    ),
    SheetLayout(
        "photo-outfits-sheet-alpha.png",
        tuple(f"photo_outfit_{index:02d}" for index in range(1, 7)),
    ),
    SheetLayout(
        "designer-outfits-sheet-alpha.png",
        tuple(f"designer_outfit_{index:02d}" for index in range(1, 7)),
    ),
    SheetLayout(
        "fancy-cute-trendy-actions-sheet-alpha.png",
        tuple(f"fancy_outfit_{index:02d}" for index in range(1, 7)),
    ),
)

TARGET_HEIGHTS = {
    "sleep_pose": 230,
    "sit_pose": 440,
    "wake": 380,
    "cake": 380,
    "phone_giggle": 440,
    "drag_pose": 350,
    "work": 440,
    "corgi_pet": 440,
    "corgi_play": 340,
    "emperor": 440,
    "fancy_outfit_04": 365,
}


def alpha_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    """返回有效人物边界，拒绝完全透明的图集单元格。"""

    bbox = image.getchannel("A").point(
        lambda value: 255 if value >= VISIBLE_ALPHA_THRESHOLD else 0
    ).getbbox()
    if bbox is None:
        raise ValueError("图集单元格不包含可见像素")
    return bbox


def split_grid(sheet: Image.Image) -> list[Image.Image]:
    """把 1536x1024 或同结构图集按三列两行等分为六格。"""

    x_bounds = [round(index * sheet.width / 3) for index in range(4)]
    y_bounds = [round(index * sheet.height / 2) for index in range(3)]
    return [
        sheet.crop((x_bounds[column], y_bounds[row], x_bounds[column + 1], y_bounds[row + 1]))
        for row in range(2)
        for column in range(3)
    ]


def remove_narrow_edge_fragments(image: Image.Image) -> Image.Image:
    """清除相邻单元格越界到左右边缘的细小残片，避免误判人物尺寸。"""

    alpha = image.getchannel("A")
    occupied = [
        x
        for x in range(image.width)
        if alpha.crop((x, 0, x + 1, image.height))
        .point(lambda value: 255 if value >= VISIBLE_ALPHA_THRESHOLD else 0)
        .getbbox()
    ]
    if not occupied:
        return image
    spans: list[tuple[int, int]] = []
    start = previous = occupied[0]
    for x in occupied[1:]:
        if x > previous + 1:
            spans.append((start, previous + 1))
            start = x
        previous = x
    spans.append((start, previous + 1))

    cleaned = image.copy()
    maximum_fragment_width = round(image.width * 0.12)
    for left, right in spans:
        touches_edge = left == 0 or right == image.width
        if touches_edge and right - left <= maximum_fragment_width and len(spans) > 1:
            cleaned.paste((0, 0, 0, 0), (left, 0, right, image.height))
    return cleaned


def normalize_sprite(image: Image.Image, target_height: int = STANDING_HEIGHT) -> Image.Image:
    """使用最近邻缩放并把完整姿态按脚底基线放入统一透明画布。"""

    cropped = image.crop(alpha_bbox(image))
    max_width = CANVAS_SIZE[0] - PADDING * 2
    max_height = CANVAS_SIZE[1] - PADDING * 2
    scale = min(
        target_height / cropped.height,
        max_width / cropped.width,
        max_height / cropped.height,
    )
    size = (
        max(1, round(cropped.width * scale)),
        max(1, round(cropped.height * scale)),
    )
    resized = cropped.resize(size, Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    x = (CANVAS_SIZE[0] - resized.width) // 2
    y = CANVAS_SIZE[1] - PADDING - resized.height
    canvas.alpha_composite(resized, (x, y))
    return canvas


def shifted_frame(image: Image.Image, x_offset: int, y_offset: int) -> Image.Image:
    """在透明画布内平移已规范姿态，用于克制的待机与互动循环。"""

    frame = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    frame.alpha_composite(image, (x_offset, y_offset))
    return frame


def save_frames(
    output_root: Path,
    directory: str,
    prefix: str,
    frames: list[Image.Image],
) -> list[str]:
    """保存一组透明帧并返回相对于私有素材根目录的路径。"""

    paths: list[str] = []
    for index, frame in enumerate(frames, start=1):
        relative = f"{directory}/{prefix}_{index:02d}.png"
        destination = output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame.save(destination, "PNG", optimize=True)
        paths.append(relative)
    return paths


def load_sheet_poses(source_root: Path) -> tuple[dict[str, Image.Image], list[str]]:
    """读取全部透明图集并返回按名字索引的六格姿态与来源列表。"""

    poses: dict[str, Image.Image] = {}
    sources: list[str] = []
    for layout in SHEET_LAYOUTS:
        path = source_root / layout.filename
        if not path.is_file():
            raise FileNotFoundError(f"找不到透明图集：{path}")
        with Image.open(path) as source:
            cells = [
                remove_narrow_edge_fragments(cell)
                for cell in split_grid(source.convert("RGBA"))
            ]
        if len(cells) != len(layout.names):
            raise ValueError(f"图集 {path.name} 格数不正确")
        for name, cell in zip(layout.names, cells, strict=True):
            alpha_bbox(cell)
            poses[name] = cell
        sources.append(path.relative_to(PROJECT_ROOT).as_posix())

    twirl_path = source_root / "outfit-sheet-rejected-except-twirl-alpha.png"
    if not twirl_path.is_file():
        raise FileNotFoundError(f"找不到水手裙转圈图集：{twirl_path}")
    with Image.open(twirl_path) as source:
        poses["outfit_twirl"] = split_grid(source.convert("RGBA"))[1]
    alpha_bbox(poses["outfit_twirl"])
    sources.append(twirl_path.relative_to(PROJECT_ROOT).as_posix())
    return poses, sources


def load_confirmed_walk(output_root: Path) -> list[str]:
    """验证并返回现有 12 帧慢速走路，禁止在本工具中重做步态。"""

    paths = sorted((output_root / "walk").glob("walk_*.png"))
    if len(paths) != 12:
        raise ValueError(f"已确认走路应有 12 帧，实际找到 {len(paths)} 帧")
    for path in paths:
        with Image.open(path) as frame:
            if frame.mode != "RGBA" or frame.size != CANVAS_SIZE:
                raise ValueError(f"走路帧规格不正确：{path}")
            alpha_bbox(frame)
    return [path.relative_to(output_root).as_posix() for path in paths]


def prepare_custom_pet(source_root: Path, output_root: Path) -> dict[str, object]:
    """在两次人工确认通过后生成完整私有桌面角色素材与清单。"""

    require_custom_pet_approved(PROJECT_ROOT / "user_assets" / "workflow.json")
    poses, sources = load_sheet_poses(source_root)
    walk_paths = load_confirmed_walk(output_root)
    normalized = {
        name: normalize_sprite(cell, TARGET_HEIGHTS.get(name, STANDING_HEIGHT))
        for name, cell in poses.items()
    }

    state_paths: dict[str, str] = {}
    for name, frame in normalized.items():
        directory = "outfits" if "outfit" in name else "states"
        state_paths[name] = save_frames(output_root, directory, name, [frame])[0]

    idle = normalized["idle_pose"]
    animations: dict[str, list[str]] = {
        "idle": save_frames(
            output_root,
            "idle",
            "idle",
            [
                shifted_frame(idle, 0, 0),
                shifted_frame(idle, 0, 1),
                shifted_frame(idle, 0, 2),
                shifted_frame(idle, 0, 2),
                shifted_frame(idle, 0, 1),
                shifted_frame(idle, 0, 0),
            ],
        ),
        "walk": walk_paths,
        "sit": save_frames(
            output_root,
            "sit",
            "sit",
            [idle, normalized["sit_pose"]],
        ),
        "sleep": save_frames(
            output_root,
            "sleep",
            "sleep",
            [normalized["sit_pose"], normalized["sleep_pose"]],
        ),
        "drag": save_frames(
            output_root,
            "interact",
            "drag",
            [
                shifted_frame(normalized["drag_pose"], -2, 7),
                shifted_frame(normalized["drag_pose"], 0, 11),
                shifted_frame(normalized["drag_pose"], 2, 7),
            ],
        ),
        "selfie": save_frames(
            output_root,
            "interact",
            "selfie",
            [
                shifted_frame(normalized["selfie_pose"], 0, 0),
                shifted_frame(normalized["selfie_pose"], -1, 1),
                shifted_frame(normalized["selfie_pose"], 1, 2),
                shifted_frame(normalized["selfie_pose"], 0, 0),
            ],
        ),
    }

    single_state_sources = {
        "wave": "wave",
        "happy": "laugh",
        "shy": "bashful_front",
        "surprised": "surprised",
        "annoyed": "angry",
        "sleepy": "sleepy",
        "curious": "thinking",
        "pout": "pout",
        "laugh": "laugh",
        "enjoy": "enjoy",
        "kiss": "friendly_gesture",
        "sad": "sad",
        "bored": "bored",
        "hungry": "hungry",
        "thinking": "thinking",
        "wake": "wake",
        "cake": "cake",
        "phone_giggle": "phone_giggle",
        "wink": "wink",
        "work": "work",
        "corgi_pet": "corgi_pet",
        "corgi_play": "corgi_play",
        "starry": "starry",
        "burger": "burger",
        "camera": "camera",
        "emperor": "emperor",
        "hug": "stretch",
        "shy_front": "bashful_front",
    }
    for state, pose_name in single_state_sources.items():
        animations[state] = [state_paths[pose_name]]

    corgi_sequence = [state_paths["corgi_pet"], state_paths["corgi_play"]]
    animations["corgi_pet"] = corgi_sequence
    animations["corgi_play"] = corgi_sequence

    outfit_names = [
        *(f"photo_outfit_{index:02d}" for index in range(1, 7)),
        *(f"designer_outfit_{index:02d}" for index in range(1, 7)),
        *(f"fancy_outfit_{index:02d}" for index in range(1, 7)),
    ]
    animations["outfit_twirl"] = [state_paths["outfit_twirl"]]
    animations["outfit_options"] = [state_paths[name] for name in outfit_names]

    icon_path = output_root / "icon.png"
    icon = idle.copy()
    icon.thumbnail((128, 128), Image.Resampling.NEAREST)
    icon_canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    icon_canvas.alpha_composite(icon, ((128 - icon.width) // 2, (128 - icon.height) // 2))
    icon_canvas.save(icon_path, "PNG", optimize=True)

    manifest: dict[str, object] = {
        "sources": [*sources, "user_assets/source_sheets/walk-sheet-v3-alpha.png"],
        "canvas_size": list(CANVAS_SIZE),
        "target_standing_height": STANDING_HEIGHT,
        "pixel_art": True,
        "resampling": "nearest",
        "walk_frame_interval_ms": 150,
        "walk_motion_factors": list(WALK_MOTION_FACTORS),
        "animations": animations,
        "icon": "icon.png",
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    """解析本地透明图集目录和私有素材输出目录。"""

    parser = argparse.ArgumentParser(description="生成完整的本地像素桌面角色素材")
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    """执行私有素材生成并输出状态与换装数量。"""

    args = parse_args()
    manifest = prepare_custom_pet(args.source.resolve(), args.output.resolve())
    animations = manifest["animations"]
    frame_count = sum(len(paths) for paths in animations.values())
    outfit_count = len(animations["outfit_options"])
    print(f"已生成 {frame_count} 个私有帧，包含 {outfit_count} 套换装选项。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
