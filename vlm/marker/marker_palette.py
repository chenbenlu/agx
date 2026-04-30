from __future__ import annotations

from dataclasses import dataclass
import hashlib

from detection_utils import canonicalize_class_id


@dataclass(frozen=True)
class RgbaColor:
    r: float
    g: float
    b: float
    a: float = 1.0


PALETTE: tuple[RgbaColor, ...] = (
    RgbaColor(0.121, 0.466, 0.705),
    RgbaColor(1.000, 0.498, 0.054),
    RgbaColor(0.172, 0.627, 0.172),
    RgbaColor(0.839, 0.153, 0.157),
    RgbaColor(0.580, 0.404, 0.741),
    RgbaColor(0.549, 0.337, 0.294),
    RgbaColor(0.890, 0.467, 0.761),
    RgbaColor(0.498, 0.498, 0.498),
    RgbaColor(0.737, 0.741, 0.133),
    RgbaColor(0.090, 0.745, 0.811),
    RgbaColor(0.000, 0.620, 0.451),
    RgbaColor(0.835, 0.369, 0.000),
    RgbaColor(0.800, 0.475, 0.655),
    RgbaColor(0.350, 0.700, 0.900),
    RgbaColor(0.941, 0.894, 0.259),
    RgbaColor(0.000, 0.447, 0.698),
)


def stable_palette_index(class_id: str) -> int:
    key = canonicalize_class_id(class_id) or "unknown"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % len(PALETTE)


class ColorRegistry:
    def __init__(self) -> None:
        self._assignments: dict[str, int] = {}
        self._used_indices: set[int] = set()

    def color_for(self, class_id: str) -> RgbaColor:
        key = canonicalize_class_id(class_id) or "unknown"
        if key in self._assignments:
            return PALETTE[self._assignments[key]]

        start = stable_palette_index(key)
        for offset in range(len(PALETTE)):
            index = (start + offset) % len(PALETTE)
            if index not in self._used_indices:
                self._assignments[key] = index
                self._used_indices.add(index)
                return PALETTE[index]

        index = start
        self._assignments[key] = index
        return PALETTE[index]
