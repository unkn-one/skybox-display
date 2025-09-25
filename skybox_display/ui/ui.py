import logging
import typing
from typing import Any

from PIL import Image, ImageDraw

from skybox_display.ui import font, theme, utils
from skybox_display.ui.page import aircraft, radar, receiver, settings, system

if typing.TYPE_CHECKING:
    from skybox_display.app import App
    from skybox_display.ui.page.page import Page

LOGGER = logging.getLogger(__name__)


class UI:
    """User interface renderer."""

    def __init__(self, app: "App", config: dict[str, Any]):
        """Initialize the UI."""
        self.app = app
        self.config = config
        self.width = config["width"]
        self.height = config["height"]
        self.cache = utils.CachedDraw(self.width, self.height)
        self.theme = None
        self.load_theme()

        # Page configuration
        self.tab_width = 40
        self.header_height = 24
        self.page_padding = 8
        self.content_x = self.tab_width + self.page_padding
        self.content_y = self.header_height + self.page_padding
        self.content_width = self.width - self.content_x - self.page_padding
        self.content_height = self.height - self.content_y - self.page_padding

        self.pages: tuple["Page", ...] = (
            aircraft.AircraftPage(self),
            radar.RadarPage(self),
            receiver.ReceiverPage(self),
            system.SystemPage(self),
            settings.SettingsPage(self)
        )

    def load_theme(self, name: str | None = None):
        t = name or self.config["theme"]
        LOGGER.info(f"Loaded theme {t}")
        self.theme = theme.get_theme(t)

    @property
    def active_page(self) -> "Page":
        return self.pages[self.config["active_page"]]

    def set_page(self, direction: int) -> None:
        """Set the active page."""
        self.config["active_page"] = (self.config["active_page"] + direction) % len(self.pages)
        LOGGER.info(f"Switched to page {self.active_page.name}")

    def on_ok(self) -> None:
        self.active_page.on_ok()

    def on_cancel(self) -> None:
        self.active_page.on_cancel()

    def on_next(self) -> None:
        if not self.active_page.on_next():
            self.set_page(+1)

    def on_prev(self) -> None:
        if not self.active_page.on_prev():
            self.set_page(-1)

    def render(self, stats: dict[str, Any]) -> Image.Image:
        """Render the current UI state."""
        img = Image.new("RGB", (self.width, self.height), self.theme.bg)
        draw = ImageDraw.Draw(img)

        active_page = self.config["active_page"]
        current_tab = self.pages[active_page]

        with self.cache.draw(draw, (id(self), active_page)) as layer_draw:
            if layer_draw:
                self._draw_page(layer_draw, active_page)

        # Draw header text
        draw.text((self.tab_width + 5, 5), current_tab.name.upper(), font=font.HEADER, fill=self.theme.bg)

        self.active_page.render(draw, stats)

        return img

    def _draw_page(self, draw: ImageDraw.ImageDraw, active_page: int) -> None:
        """Draw the page with header, sidebar and tabs."""
        current_tab = self.pages[active_page]
        accent_color = current_tab.accent_color

        # Sidebar background
        draw.rectangle([0, 0, self.tab_width, self.height], fill=self.theme.tab_bg)

        tab_height = self.height // len(self.pages)

        for i, page in enumerate(self.pages):
            y_start = i * tab_height
            y_end = (i + 1) * tab_height

            if i == active_page:
                # Highlight active tab
                draw.rectangle([0, y_start, self.tab_width, y_end], fill=page.accent_color)
                icon_color = self.theme.bg
            else:
                icon_color = self.theme.fg

            # Draw icon
            icon_x = self.tab_width // 2
            icon_y = y_start + tab_height // 2
            draw.text((icon_x, icon_y), page.icon, font=font.ICON, fill=icon_color, anchor="mm")

        header_rect = [self.tab_width, 0, self.width, self.header_height]
        draw.rectangle(header_rect, fill=accent_color)

        # Draw border around content area
        content_rect = (self.tab_width, self.header_height, self.width - 1, self.height - 1)
        draw.rectangle(content_rect, outline=accent_color, width=1)
