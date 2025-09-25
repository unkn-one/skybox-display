import typing
from typing import Any

from skybox_display.ui import font, utils
from skybox_display.ui.page import page

if typing.TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw


class SystemPage(page.Page):
    name = "System Info"
    icon = "\ue322"
    accent = "system_page"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.line_height = 20

    def render(self, draw: "ImageDraw", stats: dict[str, Any]) -> None:
        """Render the system information page.

        Args:
            draw: PIL ImageDraw object
            stats: Statistics dictionary
            x, y: Content area position
            width, height: Content area dimensions
        """
        system_data = stats.get("system", {})

        cpu_vals = system_data.get("cpu")
        mem_vals = system_data.get("mem")
        temp_vals = system_data.get("temp")
        ip = system_data.get("ip", "N/A")

        # Current values
        data = (
            ("CPU:", f"{cpu_vals[-1] or 0:.0f}%" if cpu_vals else "N/A"),
            ("MEM:", f"{mem_vals[-1] or 0:.0f}%" if mem_vals else "N/A"),
            ("TEMP:", f"{temp_vals[-1] or 0:.1f}°C" if temp_vals else "N/A"),
            ("NET:", ip),
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
