"""Validate the public XiaoU sprite pack and the private customization helpers."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from tools.prepare_custom_pet import (
    PADDING,
    normalize_sprite,
    remove_narrow_edge_fragments,
    split_grid,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "assets" / "pet" / "manifest.json"


def test_custom_grid_split_and_nearest_normalization_keep_six_complete_cells() -> None:
    sheet = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    for row in range(2):
        for column in range(3):
            left = column * 100 + 30
            top = row * 100 + 20
            for x in range(left, left + 40):
                for y in range(top, top + 60):
                    sheet.putpixel((x, y), (40 + column * 30, 80, 120, 255))

    cells = split_grid(sheet)
    normalized = [normalize_sprite(cell) for cell in cells]

    assert len(cells) == 6
    assert all(frame.size == (560, 500) for frame in normalized)
    assert all(frame.getchannel("A").getextrema()[0] == 0 for frame in normalized)
    assert all(frame.getchannel("A").getbbox() is not None for frame in normalized)
    assert all(frame.getchannel("A").getbbox()[1] >= PADDING for frame in normalized)


def test_custom_sheet_removes_small_neighbor_fragment_at_cell_edge() -> None:
    cell = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    for x in range(100, 300):
        for y in range(50, 470):
            cell.putpixel((x, y), (40, 60, 80, 255))
    for x in range(504, 512):
        for y in range(350, 430):
            cell.putpixel((x, y), (40, 60, 80, 255))

    cleaned = remove_narrow_edge_fragments(cell)
    assert cleaned.getchannel("A").getbbox() == (100, 50, 300, 470)


def test_public_manifest_covers_every_runtime_action() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    animations = manifest["animations"]

    assert manifest["sources"] == []
    assert manifest["canvas_size"] == [560, 500]
    assert manifest["pixel_art"] is True
    assert len(animations["walk"]) == 12
    assert len(animations["idle"]) == 6
    assert len(animations["drag"]) == 3
    assert len(animations["selfie"]) == 4
    assert len(animations["outfit_options"]) == 18
    assert {"outfit_twirl", "corgi_pet", "corgi_play"} <= set(animations)


def test_every_public_sprite_is_rgba_visible_and_inside_the_canvas() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_size = tuple(manifest["canvas_size"])
    checked: set[str] = set()

    for paths in manifest["animations"].values():
        for relative in paths:
            if relative in checked:
                continue
            checked.add(relative)
            path = MANIFEST_PATH.parent / relative
            with Image.open(path) as image:
                assert image.mode == "RGBA"
                assert image.size == expected_size
                alpha = image.getchannel("A")
                assert alpha.getextrema()[0] == 0
                bbox = alpha.getbbox()
                assert bbox is not None
                assert bbox[0] > 0 and bbox[1] > 0
                assert bbox[2] < image.width and bbox[3] < image.height

    assert len(checked) >= 70
