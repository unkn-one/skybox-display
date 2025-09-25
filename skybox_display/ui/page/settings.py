import typing
from collections import namedtuple
from typing import Any, Optional
from enum import Enum

from skybox_display.ui import font, theme
from skybox_display import config
from skybox_display.ui.page import page
from skybox_display.ui.page.receiver import LOGGER

if typing.TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw

SettingItem = namedtuple("SettingItem", ("label", "key", "values", "on_set"))


class SettingsMode(str, Enum):
    OFF = "off"
    SELECT = "select"
    EDIT = "edit"


class SettingsPage(page.Page):
    name = "Settings"
    icon = "\ue8b8"
    accent = "settings_page"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.line_height = 20
        self.settings_mode: SettingsMode = SettingsMode.OFF
        self.settings_index: int = 0
        self.pending: Optional[int] = None  # index into current item's values while editing
        self.items = (
            SettingItem("Aircraft Sort", "aircraft_sort", ["none", "distance", "signal", "altitude", "speed"], None),
            SettingItem("UI Theme", "theme", theme.get_theme_names(), self.on_set_theme),
            SettingItem("Units", "units", ["metric", "imperial"], None),
            SettingItem("IMU", "imu_model", [None, "LSM9DS1"], None),
        )

    def render(self, draw: "ImageDraw", stats: dict[str, Any]) -> None:
        """Render the Settings page with selection/edit flow."""
        val_x = self.x + self.width/2
        for i, item in enumerate(self.items):
            cy = self.y + i * self.line_height
            label = item.label + ":"
            # Determine current index for display
            if self.settings_mode is SettingsMode.EDIT and i == self.settings_index and self.pending is not None:
                idx = self.pending
            else:
                try:
                    idx = item.values.index(self.ui.config[item.key])
                except ValueError:
                    idx = 0
            value = item.values[idx]
            if isinstance(value, str):
                value = value.title()

            label_color = self.ui.theme.fg
            value_color = self.ui.theme.secondary
            if self.settings_mode is SettingsMode.SELECT and i == self.settings_index:
                label_color = self.accent_color
            if self.settings_mode is SettingsMode.EDIT and i == self.settings_index:
                value_color = self.accent_color

            draw.text((self.x, cy), label, font=font.DEFAULT, fill=label_color)
            draw.text((val_x, cy), str(value), font=font.DEFAULT, fill=value_color)

        hint = "OK: Select/Edit/Confirm  Back: Exit"
        draw.text((self.x, self.y + self.height - 2), hint, font=font.SMALL, fill=self.ui.theme.neutral, anchor="lb")

    def on_set_theme(self) -> None:
        self.ui.theme = theme.get_theme(self.ui.config["theme"]) or self.ui.theme
        self.ui.cache.reset()

    def on_ok(self) -> bool:
        if self.settings_mode is SettingsMode.OFF:
            # Enter settings selection mode
            self.settings_mode = SettingsMode.SELECT
            self.settings_index = 0
            return True
        if self.settings_mode is SettingsMode.SELECT:
            # Enter edit mode for current item
            self.settings_mode = SettingsMode.EDIT
            item = self.items[self.settings_index]
            try:
                self.pending = item.values.index(self.ui.config[item.key])
            except ValueError:
                self.pending = 0
            return True
        if self.settings_mode is SettingsMode.EDIT:
            # Confirm change
            item = self.items[self.settings_index]
            if self.pending is not None:
                self.ui.config[item.key] = item.values[self.pending]
                # Apply side-effects
                try:
                    if callable(item.on_set):
                        item.on_set()
                except Exception:
                    LOGGER.exception(f"Unable to set {item.label}")
                # Persist updated configuration
                try:
                    config.save_config(self.ui.config)
                except Exception:
                    LOGGER.exception(f"Unable to save changed {item.label}")
            self.pending = None
            self.settings_mode = SettingsMode.SELECT
            return True
        return False

    def on_cancel(self) -> bool:
        if self.settings_mode is SettingsMode.EDIT:
            # Discard pending and go back to select
            self.pending = None
            self.settings_mode = SettingsMode.SELECT
            return True
        if self.settings_mode is SettingsMode.SELECT:
            # Exit settings interaction
            self.settings_mode = SettingsMode.OFF
            return True
        return False

    def on_next(self) -> bool:
        if self.settings_mode is SettingsMode.SELECT:
            self.settings_index = min(len(self.items) - 1, self.settings_index + 1)
            return True
        if self.settings_mode is SettingsMode.EDIT:
            item = self.items[self.settings_index]
            if self.pending is None:
                # Initialize from current config
                try:
                    self.pending = item.values.index(self.ui.config[item.key])
                except ValueError:
                    self.pending = 0
            self.pending = (self.pending + 1) % len(item.values)
            return True
        return False

    def on_prev(self) -> bool:
        if self.settings_mode is SettingsMode.SELECT:
            self.settings_index = max(0, self.settings_index - 1)
            return True
        if self.settings_mode is SettingsMode.EDIT:
            item = self.items[self.settings_index]
            if self.pending is None:
                try:
                    self.pending = item.values.index(self.ui.config[item.key])
                except ValueError:
                    self.pending = 0
            self.pending = (self.pending - 1) % len(item.values)
            return True
        return False
