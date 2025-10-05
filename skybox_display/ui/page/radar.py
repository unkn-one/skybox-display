import math
import typing
from typing import Any

from skybox_display.ui import font, utils as ui_utils
from skybox_display import math_utils
from skybox_display.ui.page import page

if typing.TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw


class RadarPage(page.Page):
    name = "Virtual Radar"
    icon = "\uf04e"
    accent = "radar_page"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ring_candidates = [1, 2, 5, 10, 20, 25, 50, 100, 200, 300, 400, 500]
        self._scales = ["linear", "log5", "log10"]
        self._radio_lat = self.ui.config["radio_lat"]
        self._radio_lon = self.ui.config["radio_lon"]

    @staticmethod
    def _quantise_range_25(dist: float, max_dist: float) -> float:
        """Clip/quantise range to 25 km increments and cap by config."""
        return max(25.0, min(max_dist, math.ceil(dist / 25.0) * 25.0))

    def _draw_radar_grid(self, draw: "ImageDraw", cx: int, cy: int,
                         radius: int, dmax_km: float, scale_mode: str,
                         heading_rot: float) -> None:
        """Crosshair, rings, labels, and N/E/S/W rotated by device heading."""

        from skybox_display import math_utils as mu

        # Crosshair rotated by heading
        # East-West axis line
        ex, ey = math_utils.pt_for_brg(cx, cy, radius, (90.0 - heading_rot) % 360.0)
        wx, wy = math_utils.pt_for_brg(cx, cy, radius, (270.0 - heading_rot) % 360.0)
        draw.line((wx, wy, ex, ey), fill=self.ui.theme.neutral)
        # North-South axis line
        nx, ny = math_utils.pt_for_brg(cx, cy, radius, (0.0 - heading_rot) % 360.0)
        sx, sy = math_utils.pt_for_brg(cx, cy, radius, (180.0 - heading_rot) % 360.0)
        draw.line((sx, sy, nx, ny), fill=self.ui.theme.neutral)

        # ring step (~≤5 rings)
        step = next((s for s in self._ring_candidates if (dmax_km // s) <= 5), self._ring_candidates[-1])
        n = int(dmax_km // step)

        labels = []
        for i in range(1, n + 1):
            r_km = i * step
            r_px = math_utils.range_scale(r_km, dmax_km, scale_mode) * radius
            draw.ellipse((cx - r_px, cy - r_px, cx + r_px, cy + r_px), outline=self.ui.theme.shade)

            # Label: place along rotated E/W axes
            label = str(int(r_km))
            if i % 2:  # east side
                tx, ty = math_utils.pt_for_brg(cx, cy, r_px + 2, (90.0 - heading_rot) % 360.0)
            else:      # west side
                tx, ty = math_utils.pt_for_brg(cx, cy, r_px + 2, (270.0 - heading_rot) % 360.0)
            labels.append(((tx, ty), label, "mm"))

        # draw later to avoid overlap
        for pos, label, anchor in labels:
            draw.text(pos, label, font=font.SMALL, fill=self.ui.theme.secondary, anchor=anchor)

        # N/E/S/W rotated
        # for brg, lbl in ((0.0, "N"), (90.0, "E"), (180.0, "S"), (270.0, "W")):
        for brg, lbl in ((0.0, "N"), (180.0, "S")):
            tx, ty = math_utils.pt_for_brg(cx, cy, radius, (brg - heading_rot) % 360.0)
            draw.text((tx, ty), lbl, font=font.SMALL, fill=self.ui.theme.accent, anchor="mm")

    def render(self, draw: "ImageDraw", stats: dict[str, Any]) -> None:
        # Refresh scale from config in case it was changed via Settings
        scale_mode = self.ui.config["radar_scale"]
        pad = 4
        cx = self.x + self.width // 2
        cy = self.y + self.height // 2
        radius = max(4, min(self.width, self.height) // 2 - pad)

        aircraft_data = stats.get("aircraft", {})
        aircraft_list = aircraft_data.get("aircraft", [])
        imu_data = stats.get("imu", {})
        imu_heading = imu_data.get("heading")
        heading_rot = float(imu_heading) % 360.0 if isinstance(imu_heading, (int, float)) else 0.0

        # Collect (distance, bearing, heading, label)
        points = []
        dmax = 1e-3
        for ac in aircraft_list:
            lat = ac.get("lat")
            lon = ac.get("lon")
            if lat is None or lon is None:
                continue
            d = ac.get("distance_km")
            if d is None:
                d = math_utils.haversine_distance(self._radio_lat, self._radio_lon, lat, lon)
            brg = math_utils.bearing(self._radio_lat, self._radio_lon, lat, lon)
            hdg = ac.get("track") or ac.get("mag_heading") or ac.get("true_heading")
            label = (ac.get("flight") or ac.get("callsign") or ac.get("hex") or "").strip()
            points.append((d, brg, hdg, label))
            dmax = max(dmax, d)

        # Quantised span: farthest * 1.1 -> round up to 25 km steps (min 25, capped)
        dspan_raw = max(dmax * 1.1, 10.0)
        dspan = math_utils.quantise_range(dspan_raw, self.ui.config["radar_max_range_km"], 25.0)

        # Cached grid; include heading (rounded) so we redraw only when orientation changes
        with self.ui.cache.draw(draw, (id(self), int(dspan), scale_mode, int(heading_rot))) as layer_draw:
            if layer_draw:
                self._draw_radar_grid(layer_draw, cx, cy, radius, dspan, scale_mode, heading_rot)

        # Range and scale
        draw.text((self.x, self.y), f"RNG: {int(dspan)}km", font=font.DEFAULT,
                  fill=self.ui.theme.secondary, anchor="la")
        draw.text((self.x, self.y + self.height), f"SCL: {scale_mode.upper()}",
                  font=font.DEFAULT, fill=self.ui.theme.secondary, anchor="lb")

        # Ownship
        rdot = 3  # Radar center dot size
        draw.ellipse((cx - rdot, cy - rdot, cx + rdot, cy + rdot), fill=self.ui.theme.accent)

        # Aircraft drawing with label overlap avoidance
        placed_boxes: list[tuple[int, int, int, int]] = []
        for d, brg, hdg, label in points:
            r_px = math_utils.range_scale(d, dspan, scale_mode) * radius
            brg_rel = (brg - heading_rot) % 360.0
            a = math.radians(brg_rel)
            px = cx + r_px * math.sin(a)
            py = cy - r_px * math.cos(a)

            # Icon: arrow if heading present, else dot
            if hdg is not None:
                hdg_rel = (float(hdg) - heading_rot) % 360.0
                ui_utils.draw_heading_arrow(draw, px, py, hdg_rel, 6, self.ui.theme.accent_2)
            else:
                draw.ellipse((px - 2, py - 2, px + 2, py + 2), fill=self.ui.theme.secondary)

            # Label (centre-top anchored under icon)
            if label:
                label_off = 8
                tx, ty = px, py + label_off
                # initial bbox at anchor "mt" (middle top)
                bbox_l, bbox_t, bbox_r, bbox_b = draw.textbbox((tx, ty), label, font=font.SMALL, anchor="mt")

                # Clamp into content rect by shifting anchor point
                min_x, min_y = self.x + 2, self.y + 2
                max_x, max_y = self.x + self.width - 2, self.y + self.height - 2
                dx = 0
                dy = 0
                if bbox_l < min_x: dx += (min_x - bbox_l)
                if bbox_r > max_x: dx -= (bbox_r - max_x)
                if bbox_t < min_y: dy += (min_y - bbox_t)
                if bbox_b > max_y: dy -= (bbox_b - max_y)
                if dx or dy:
                    tx += dx
                    ty += dy
                    bbox_l, bbox_t, bbox_r, bbox_b = draw.textbbox((tx, ty), label, font=font.SMALL, anchor="mt")

                # Overlap check
                overlaps = any(not (bbox_r < b_l or bbox_l > b_r or bbox_b < b_t or bbox_t > b_b)
                               for b_l, b_t, b_r, b_b in placed_boxes)
                if not overlaps:
                    placed_boxes.append((bbox_l, bbox_t, bbox_r, bbox_b))
                    draw.text((tx, ty), label, font=font.SMALL, fill=self.ui.theme.fg, anchor="mt")

    def on_cancel(self) -> bool:
        scale_mode = self.ui.config["radar_scale"]
        current_idx = self._scales.index(scale_mode)
        self.ui.config["radar_scale"] = self._scales[(current_idx + 1) % len(self._scales)]
        return True
