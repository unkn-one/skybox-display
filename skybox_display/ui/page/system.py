import logging
import subprocess
import typing
from typing import Any

from skybox_display import APP_NAME
from skybox_display.ui import font, utils
from skybox_display.ui.page import page

if typing.TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw


LOGGER = logging.getLogger(__name__)


class SystemPage(page.Page):
    name = "System Info"
    icon = "\ue322"
    accent = "system_page"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buttons: tuple[dict[str, Any], ...] = (
            {"icon": "\ue5cd", "command": ("systemctl", "stop", f"{APP_NAME}.service")},
            {"icon": "\ue8ac", "command": ("systemctl", "poweroff")},
            {"icon": "\uf053", "command": ("systemctl", "reboot")},
        )
        self.selected_button: int | None = None

    def render(self, draw: "ImageDraw", data: dict[str, Any]) -> None:
        """Render the system information page.

        Args:
            draw: PIL ImageDraw object
            data: Statistics dictionary
            x, y: Content area position
            width, height: Content area dimensions
        """
        system_data = data.get("system", {})
        imu_data = data.get("imu", {})

        cpu_vals = system_data.get("cpu")
        mem_vals = system_data.get("mem")
        temp_vals = system_data.get("temp")
        ip = system_data.get("ip", "N/A")
        heading = imu_data.get("heading", "N/A")

        # Current values
        data = (
            ("CPU", f"{cpu_vals[-1] or 0:.0f}%" if cpu_vals else "N/A"),
            ("MEM", f"{mem_vals[-1] or 0:.0f}%" if mem_vals else "N/A"),
            ("TEMP", f"{temp_vals[-1] or 0:.1f}°C" if temp_vals else "N/A"),
            ("NET", ip),
            ("HEAD", f"{heading}°"),
        )
        for i, (key, value) in enumerate(data):
            cur_y = self.y + self.line_height * i
            draw.text((self.x, cur_y), key, font=font.DEFAULT, fill=self.ui.theme.fg)
            draw.text((self.x + 50, cur_y), value, font=font.DEFAULT, fill=self.ui.theme.secondary)

        # Mini graphs
        graph_x = self.x + 120
        graph_width = self.width - 130
        graph_height = 15

        if cpu_vals and len(cpu_vals) > 1:
            utils.draw_mini_graph(draw, graph_x, self.y, graph_width, graph_height,
                                  cpu_vals, self.ui.theme.accent, self.ui.theme.neutral, 0, 100)
        if mem_vals and len(mem_vals) > 1:
            utils.draw_mini_graph(draw, graph_x, self.y + 20, graph_width, graph_height,
                                  mem_vals, self.ui.theme.accent, self.ui.theme.neutral, 0, 100)
        if temp_vals and len(temp_vals) > 1:
            utils.draw_mini_graph(draw, graph_x, self.y + 40, graph_width, graph_height,
                                  temp_vals, self.ui.theme.accent, self.ui.theme.neutral, 20, 80)
        button_y = self.y + self.height - 24
        button_spacing = 60
        total_span = button_spacing * (len(self.buttons) - 1) if len(self.buttons) > 1 else 0
        start_x = self.x + self.width / 2 - total_span / 2
        for idx, button in enumerate(self.buttons):
            icon_color = self.ui.theme.accent if self.selected_button == idx else self.ui.theme.secondary
            draw.text((start_x + idx * button_spacing, button_y), button["icon"], font=font.ICON, fill=icon_color, anchor="mm")

    def _activate_button(self, index: int) -> None:
        command = self.buttons[index]["command"]
        try:
            subprocess.Popen(command)
        except Exception as e:
            LOGGER.error("Failed to execute %s: %s", command, e)

    def on_ok(self) -> bool:
        if self.buttons:
            if self.selected_button is None:
                self.selected_button = 0
            else:
                self._activate_button(self.selected_button)
                self.selected_button = None
            return True
        return False

    def on_cancel(self) -> bool:
        if self.selected_button is not None:
            self.selected_button = None
            return True
        try:
            if self.ui.app.collector.start_imu_calibration():
                LOGGER.info("IMU calibration started")
            else:
                LOGGER.warning("IMU calibration unavailable or already running")
            return True
        except Exception as exc:
            LOGGER.error("IMU calibration request failed: %s", exc)
            return False

    def on_next(self) -> bool:
        if self.buttons and self.selected_button is not None:
            self.selected_button = (self.selected_button + 1) % len(self.buttons)
            return True
        return False


    def on_prev(self) -> bool:
        if self.buttons and self.selected_button is not None:
            self.selected_button = (self.selected_button - 1) % len(self.buttons)
            return True
        return False
