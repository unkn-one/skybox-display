import contextlib
import math
from typing import Any

from PIL import Image, ImageDraw

from skybox_display.ui.theme import Color


class CachedDraw:
    def __init__(self, width: int, height: int):
        self._layer_cache: dict[tuple, Image.Image] = {}
        self.width = width
        self.height = height

    @contextlib.contextmanager
    def draw(self, draw: ImageDraw.ImageDraw, key: Any) -> Image.Image:
        """Return cached transparent overlay for given key or yield and cache it."""
        layer_draw = None
        layer = self._layer_cache.get(key)
        if layer is None:
            layer = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            self._layer_cache[key] = layer
            layer_draw = ImageDraw.Draw(layer)
        yield layer_draw
        draw._image.paste(layer, layer)

    def reset(self):
        self._layer_cache = {}


def draw_heading_arrow(draw: ImageDraw.ImageDraw, x: float, y: float,
                       heading: float, size: int, color: Color) -> None:
    """Draw a heading arrow pointing in the specified direction.

    Args:
        draw: PIL ImageDraw object
        x, y: Center position of the arrow
        heading: Heading in degrees (0 = North, 90 = East)
        size: Size of the arrow
        color: Arrow color
    """
    # Convert heading to radians (subtract 90 to make 0 degrees point up)
    angle = math.radians(heading - 90)

    # Calculate arrow points
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)

    # Arrow tip
    tip_x = x + size * cos_a
    tip_y = y + size * sin_a

    # Arrow base points
    base_angle1 = angle + math.radians(150)
    base_angle2 = angle + math.radians(210)

    base1_x = x + (size * 0.6) * math.cos(base_angle1)
    base1_y = y + (size * 0.6) * math.sin(base_angle1)

    base2_x = x + (size * 0.6) * math.cos(base_angle2)
    base2_y = y + (size * 0.6) * math.sin(base_angle2)

    # Draw the arrow
    points = [(tip_x, tip_y), (base1_x, base1_y), (base2_x, base2_y)]
    draw.polygon(points, fill=color)


def draw_mini_graph(draw: ImageDraw.ImageDraw, x: int, y: int,
                    width: int, height: int, values: list[float],
                    color: Color, outline: Color,
                    min_val: float | None = None, max_val: float | None = None) -> None:
    """Draw a mini graph of values.

    Args:
        draw: PIL ImageDraw object
        x, y: Top-left corner of graph
        width, height: Graph dimensions
        values: List of values to plot
        color: Line color
    """
    if not values or len(values) < 2:
        return

    if min_val is None:
        min_val = min(values)
    if max_val is None:
        max_val = max(values)
    val_range = max_val - min_val if max_val != min_val else 1

    points = [
        (x + (i * width // (len(values) - 1)),
         y + height - int(((val - min_val) / val_range) * height))
        for i, val in enumerate(values)
    ]

    # Draw the graph line
    draw.line(points, fill=color, width=1)

    # Draw border
    draw.rectangle([x, y, x + width, y + height], outline=outline, width=1)
