"""Shared look for previews, the dimension sheet and USDZ: part colours and a Japanese font."""
import importlib.util
from pathlib import Path

# 8 clearly different colours so neighbouring parts never share one (repeats only after 8 parts)
PART_COLORS = [
    (0.95, 0.55, 0.15),  # orange
    (0.20, 0.50, 0.85),  # blue
    (0.30, 0.68, 0.32),  # green
    (0.80, 0.25, 0.25),  # red
    (0.55, 0.35, 0.75),  # purple
    (0.10, 0.65, 0.65),  # teal
    (0.85, 0.75, 0.15),  # yellow
    (0.60, 0.40, 0.25),  # brown
]
CONTEXT_COLOR = (0.55, 0.60, 0.68)

JP_FONTS = ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans CJK JP", "Noto Sans JP",
            "IPAexGothic", "Yu Gothic"]


def part_color(i):
    return PART_COLORS[i % len(PART_COLORS)]


def jp_font():
    """Name of an installed Japanese font for matplotlib, or None (callers fall back to English).

    Uses the IPAex Gothic font bundled with the `japanize-matplotlib` package when the system has
    none, without importing that package (it needs distutils, gone in Python 3.12).
    """
    from matplotlib import font_manager
    have = {f.name for f in font_manager.fontManager.ttflist}
    for f in JP_FONTS:
        if f in have:
            return f
    spec = importlib.util.find_spec("japanize_matplotlib")
    if spec and spec.submodule_search_locations:
        ttf = Path(list(spec.submodule_search_locations)[0]) / "fonts" / "ipaexg.ttf"
        if ttf.exists():
            font_manager.fontManager.addfont(str(ttf))
            return font_manager.FontProperties(fname=str(ttf)).get_name()
    return None
