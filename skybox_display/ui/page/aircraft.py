import typing
from typing import Any

from skybox_display.ui import font, utils as ui_utils
from skybox_display.ui.page import page

if typing.TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw


class AircraftPage(page.Page):
    name = "Aircraft Info"
    icon = "\ue539"
    accent = "aircraft_page"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.line_height = 14
        self.display_toggle = True
        self.scroll_mode = False
        self.scroll_offset = 0
        self.last_total = 0
        self.last_max_lines = 0
        self.scroll_visible = False
        self.sort_key_funcs = {
            "distance": self._sort_key_distance,
            "signal": self._sort_key_signal,
            "altitude": self._sort_key_alt,
            "speed": self._sort_key_speed,
        }

    @staticmethod
    def _sort_key_distance(ac: dict) -> float:
        d = ac.get("distance_km")
        try:
            return float(d)
        except (TypeError, ValueError):
            return float('inf')

    @staticmethod
    def _sort_key_signal(ac: dict) -> float:
        # Higher is better (less negative)
        s = ac.get("rssi", ac.get("signal"))
        try:
            return -float(s)  # negative to sort descending
        except (TypeError, ValueError):
            return float('inf')

    @staticmethod
    def _sort_key_alt(ac: dict) -> float:
        a = ac.get("alt_baro", ac.get("altitude"))
        try:
            return -float(a)  # higher first
        except (TypeError, ValueError):
            return float('inf')

    @staticmethod
    def _sort_key_speed(ac: dict) -> float:
        v = ac.get("gs")
        try:
            return -float(v)  # faster first
        except (TypeError, ValueError):
            return float('inf')

    def render(self, draw: "ImageDraw", stats: dict[str, Any]) -> None:
        aircraft_data = stats.get("aircraft", {})
        aircraft_list = aircraft_data.get("aircraft", [])
        imu_data = stats.get("imu", {})
        imu_heading = imu_data.get("heading")
        heading_rot = float(imu_heading) % 360.0 if isinstance(imu_heading, (int, float)) else 0.0

        # Handle empty list
        if not aircraft_list:
            draw.text((self.x + self.width/2, self.y + self.height/2), "No aircraft data",
                      font=font.DATA, fill=self.ui.theme.secondary, anchor="mm")

        # Aircraft list
        
        max_lines = max(1, self.height // self.line_height)

        # Update last-known paging metrics
        total = len(aircraft_list)
        self.last_total = total
        self.last_max_lines = max_lines
        self.scroll_visible = total > max_lines

        # Clamp scroll offset
        max_offset = max(0, total - max_lines)
        if self.scroll_offset > max_offset:
            self.scroll_offset = max_offset
        if self.scroll_offset < 0:
            self.scroll_offset = 0

        # Sorting per setting
        sort_key = self.ui.config.get("aircraft_sort")
        if sort_key and sort_key != "none":
            kf = self.sort_key_funcs.get(sort_key, self._sort_key_distance)
            aircraft_list = sorted(aircraft_list, key=kf)

        start_idx = self.scroll_offset
        units = self.ui.config["units"]
        for i, aircraft in enumerate(aircraft_list[start_idx:start_idx + max_lines]):
            item_y = self.y + i * self.line_height

            if self.display_toggle:
                # Show flight name, distance, and speed
                flight = aircraft.get("flight", "").strip() or "N/A"
                distance = aircraft.get("distance_km")
                if distance is not None:
                    dist_text = f"{distance:.1f}km" if units == "metric" else f"{distance * 0.539957:.1f}nm"
                else:
                    dist_text = "N/A"

                speed = aircraft.get("gs")
                if speed is not None:
                    speed_text = f"{int(speed * 1.852)}km/h" if units == "metric" else f"{int(speed)}kt"
                else:
                    speed_text = "N/A"

                draw.text((self.x, item_y), flight, font=font.DATA, fill=self.ui.theme.accent)
                draw.text((self.x + 70, item_y), dist_text, font=font.DEFAULT, fill=self.ui.theme.fg)
                draw.text((self.x + 150, item_y), speed_text, font=font.DEFAULT, fill=self.ui.theme.secondary)

                # Draw heading arrow if available
                heading = aircraft.get("track") or aircraft.get("mag_heading") or aircraft.get("true_heading")
                if heading is not None:
                    arrow_x = self.x + self.width - 20
                    arrow_y = item_y + 7
                    hdg_rel = (float(heading) - heading_rot) % 360.0
                    ui_utils.draw_heading_arrow(draw, arrow_x, arrow_y, hdg_rel, 6, self.ui.theme.accent_2)
            else:
                # Show hex, altitude, and RSSI
                hex_code = aircraft.get("hex", "N/A")
                altitude = aircraft.get("alt_baro", aircraft.get("altitude", 0))
                if altitude is None:
                    alt_text = "N/A"
                elif isinstance(altitude, int):
                    alt_text = f"{int(altitude / 3.2808)}m" if units == "metric" else f"{int(altitude)}ft"
                else:
                    alt_text = altitude
                rssi = aircraft.get("rssi", aircraft.get("signal", 0))
                rssi_text = f"{rssi:.1f}dB" if rssi else "N/A"

                draw.text((self.x, item_y), hex_code, font=font.DATA, fill=self.ui.theme.accent)
                draw.text((self.x + 70, item_y), alt_text, font=font.DEFAULT, fill=self.ui.theme.fg)
                draw.text((self.x + 140, item_y), rssi_text, font=font.DEFAULT, fill=self.ui.theme.neutral)

        # Scrollbar (show only if content exceeds page)
        if self.scroll_visible:
            rail_x = self.x + self.width - 3
            rail_y0 = self.y
            rail_y1 = self.y + self.height
            # Rail line
            draw.line((rail_x, rail_y0, rail_x, rail_y1), fill=self.ui.theme.shade, width=1)

            # Thumb size and position
            content_h = self.height
            # Minimum thumb height at least one line
            thumb_h = max(self.line_height, int(content_h * (max_lines / total)))
            # Position proportional to offset
            max_off = max(1, total - max_lines)
            pos_ratio = self.scroll_offset / max_off
            thumb_y = rail_y0 + int((content_h - thumb_h) * pos_ratio)

            thumb_color = self.accent_color if self.scroll_mode else self.ui.theme.secondary
            draw.rectangle((rail_x - 2, thumb_y, rail_x + 2, thumb_y + thumb_h), outline=thumb_color, fill=None, width=1)

    def _scroll(self, direction: int) -> None:
        """Scroll aircraft list by a page minus one row in the given direction."""
        max_lines = max(1, self.last_max_lines or 0)
        total = max(0, self.last_total or 0)
        if total <= max_lines:
            return  # Nothing to scroll
        step = max(1, max_lines - 1)
        new_off = self.scroll_offset + (step if direction > 0 else -step)
        max_offset = max(0, total - max_lines)
        self.scroll_offset = max(0, min(max_offset, new_off))

    def on_ok(self) -> bool:
        if self.scroll_visible:
            self.scroll_mode = not self.scroll_mode
            return True
        return False

    def on_cancel(self) -> bool:
        self.display_toggle = not self.display_toggle
        return True

    def on_next(self) -> bool:
        if self.scroll_mode:
            self._scroll(+1)
            return True

    def on_prev(self) -> bool:
        if self.scroll_mode:
            self._scroll(-1)
            return True
