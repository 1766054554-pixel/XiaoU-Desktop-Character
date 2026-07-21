"""Render a high-resolution catalog of every public XiaoU action and outfit."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "assets" / "pet" / "manifest.json"

LABELS = {
    "idle": "安静待机",
    "walk": "自然走路",
    "sit": "坐下",
    "sleep": "乖乖睡觉",
    "drag": "拖拽",
    "selfie": "自拍",
    "wave": "挥手问好",
    "happy": "开心",
    "shy": "有点不好意思",
    "surprised": "惊讶",
    "annoyed": "生气",
    "sleepy": "困倦",
    "curious": "好奇",
    "pout": "嘟嘴",
    "laugh": "大笑",
    "enjoy": "闭眼享受",
    "kiss": "发送亲亲",
    "sad": "难过",
    "bored": "无聊等待",
    "hungry": "饥饿",
    "thinking": "陷入思考",
    "wake": "醒来",
    "cake": "吃蛋糕",
    "phone_giggle": "玩手机傻笑",
    "wink": "Wink",
    "work": "电脑摸鱼",
    "corgi_pet": "摸摸柯基",
    "corgi_play": "陪柯基玩",
    "starry": "星星眼捧脸",
    "burger": "大口吃汉堡",
    "camera": "拿相机拍照",
    "emperor": "小皇帝",
    "hug": "张开手臂",
    "shy_front": "正面害羞",
    "outfit_twirl": "水手裙转圈",
}

REPRESENTATIVE_INDEX = {
    "walk": 3,
    "sit": -1,
    "sleep": -1,
    "drag": 1,
    "selfie": 0,
    "corgi_pet": 0,
    "corgi_play": -1,
}


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _entries(manifest: dict[str, object]) -> list[tuple[str, str, Path]]:
    animations = manifest["animations"]
    assert isinstance(animations, dict)
    entries: list[tuple[str, str, Path]] = []
    for name, raw_paths in animations.items():
        paths = list(raw_paths)
        if name == "outfit_options":
            for index, relative in enumerate(paths, start=1):
                if index <= 6:
                    label = f"照片灵感造型 {index:02d}"
                elif index <= 12:
                    label = f"高级设计造型 {index - 6:02d}"
                else:
                    label = f"甜酷潮流造型 {index - 12:02d}"
                entries.append((f"outfit_{index:02d}", label, MANIFEST_PATH.parent / relative))
            continue
        selected = paths[REPRESENTATIVE_INDEX.get(name, 0)]
        entries.append((name, LABELS.get(name, name), MANIFEST_PATH.parent / selected))
    return entries


def render(output: Path) -> Path:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = _entries(manifest)
    columns = 6
    cell_width = 620
    cell_height = 600
    margin = 80
    header_height = 210
    footer_height = 90
    rows = math.ceil(len(entries) / columns)
    poster = Image.new(
        "RGB",
        (
            margin * 2 + columns * cell_width,
            margin + header_height + rows * cell_height + footer_height,
        ),
        (247, 249, 252),
    )
    draw = ImageDraw.Draw(poster)
    draw.rounded_rectangle(
        (margin, 46, poster.width - margin, 176),
        radius=28,
        fill=(255, 255, 255),
        outline=(26, 52, 86),
        width=3,
    )
    draw.text(
        (poster.width // 2, 72),
        "小u完整动作与造型合集",
        font=_font(66),
        fill=(19, 39, 67),
        anchor="ma",
    )
    draw.text(
        (poster.width // 2, 151),
        f"{len(entries)} 个动作与造型 · 透明像素素材",
        font=_font(28),
        fill=(207, 75, 104),
        anchor="ma",
    )

    for index, (_name, label, path) in enumerate(entries):
        row, column = divmod(index, columns)
        left = margin + column * cell_width + 18
        top = margin + header_height + row * cell_height + 16
        right = left + cell_width - 36
        bottom = top + cell_height - 32
        draw.rounded_rectangle(
            (left, top, right, bottom),
            radius=20,
            fill=(255, 255, 255),
            outline=(213, 221, 231),
            width=2,
        )
        with Image.open(path) as source:
            sprite = source.convert("RGBA")
        bbox = sprite.getchannel("A").getbbox()
        if bbox is None:
            raise ValueError(f"动作图片完全透明：{path}")
        sprite = sprite.crop(bbox)
        scale = min(430 / sprite.width, 430 / sprite.height)
        resized = sprite.resize(
            (max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale))),
            Image.Resampling.NEAREST,
        )
        image_x = left + (right - left - resized.width) // 2
        image_y = top + 30 + 430 - resized.height
        poster.paste(resized, (image_x, image_y), resized)
        draw.line(
            (left + 28, top + 478, right - 28, top + 478),
            fill=(232, 236, 242),
            width=2,
        )
        draw.text(
            ((left + right) // 2, top + 520),
            label,
            font=_font(31),
            fill=(30, 47, 70),
            anchor="mm",
        )

    draw.text(
        (poster.width // 2, poster.height - 48),
        "XiaoU Desktop Character · Pixel artwork CC BY 4.0",
        font=_font(25),
        fill=(80, 94, 112),
        anchor="mm",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    poster.save(output, "PNG", optimize=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="生成小u完整动作与造型高清合集")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "media" / "xiaou-action-catalog.png",
    )
    args = parser.parse_args()
    print(render(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
