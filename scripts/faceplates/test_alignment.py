"""The cage check accepts boxes that sit on openings and rejects boxes that do not."""

import numpy as np

from cutouts import cage_alignment, detect_cages, edge_alignment, overlay_alignment, passes, passes_edges, passes_overlay


def _panel(width=400, height=80) -> np.ndarray:
    image = np.full((height, width, 3), 180, np.uint8)
    return image


def _jack(image: np.ndarray, x: int, y: int, w: int = 18, h: int = 28) -> None:
    image[y : y + h, x : x + w] = (30, 30, 30)
    image[y : y + 4, x : x + w] = (210, 210, 210)
    image[y + h - 4 : y + h, x : x + w] = (210, 210, 210)


def _box(x: int, y: int, w: int, h: int, width: int, height: int, name: str) -> dict:
    return {"name": name, "x": x / width, "y": y / height, "w": w / width, "h": h / height}


def test_boxes_on_jacks_pass():
    width, height = 400, 80
    image = _panel(width, height)
    ports = []
    for index in range(8):
        x = 40 + index * 28
        _jack(image, x, 26)
        ports.append(_box(x, 26, 18, 28, width, height, f"Gi1/0/{index + 1}"))
    score = cage_alignment(ports, detect_cages(image))
    assert passes(score)
    assert passes_overlay(overlay_alignment(image, ports))
    assert passes_edges(edge_alignment(image, ports))


def test_boxes_shifted_off_the_jacks_fail():
    width, height = 400, 80
    image = _panel(width, height)
    ports = []
    for index in range(8):
        x = 40 + index * 28
        _jack(image, x, 26)
        ports.append(_box(x + 14, 4, 18, 28, width, height, f"Gi1/0/{index + 1}"))
    score = cage_alignment(ports, detect_cages(image))
    assert not passes(score)
    assert not passes_overlay(overlay_alignment(image, ports))


def test_flat_led_row_is_not_a_cage():
    width, height = 400, 80
    image = _panel(width, height)
    ports = []
    for index in range(8):
        x = 40 + index * 28
        image[30 : 48, x : x + 18] = (120, 120, 120)
        ports.append(_box(x, 30, 18, 18, width, height, f"Eth{index}"))
    score = cage_alignment(ports, detect_cages(image))
    assert not passes(score)
    assert not passes_overlay(overlay_alignment(image, ports))
