import typing
from typing import Any

if typing.TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw
    from skybox_display.ui.ui import UI
    from skybox_display.ui.theme import Color


class Page:
    name: str
    icon: str
    accent: str

    def __init__(self, ui: "UI"):
        self.ui = ui
        self.x = ui.content_x
        self.y = ui.content_y
        self.width = ui.content_width
        self.height = ui.content_height
        self.line_height = 20

    def render(self, draw: "ImageDraw", data: dict[str, Any]) -> None:
        pass

    def on_next(self) -> bool:
        return False

    def on_prev(self) -> bool:
        return False

    def on_ok(self) -> bool:
        return False

    def on_cancel(self) -> bool:
        return False

    @property
    def accent_color(self) -> "Color":
        return getattr(self.ui.theme, self.accent)
