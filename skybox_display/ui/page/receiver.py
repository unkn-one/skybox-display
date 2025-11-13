import logging
import typing
from typing import Any

from skybox_display.ui import font
from skybox_display.ui.page import page

if typing.TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw

LOGGER = logging.getLogger(__name__)


class ReceiverPage(page.Page):
    name = "Receiver Stats"
    icon = "\ue8bf"
    accent = "receiver_page"

    def render(self, draw: "ImageDraw", data: dict[str, Any]) -> None:
        stats_data = data.get("stats", {})

        try:
            # Get last minute stats
            last1min = stats_data.get("last1min", {})
            local_stats = last1min.get("local", {})

            # Extract values
            signal = local_stats.get("signal")
            noise = local_stats.get("noise")
            snr = signal - noise if signal and noise else None
            samples = local_stats.get("samples_processed", 0)
            accepted = local_stats.get("accepted", [0])[0]

            # Draw aligned labels/values like system page
            rows = (
                ("Signal:", f"{signal:.1f} dBFS" if signal else "N/A"),
                ("Noise:", f"{noise:.1f} dBFS" if noise else "N/A"),
                ("SNR:", f"{snr:.1f} dB" if snr else "N/A"),
                ("Samples:", f"{samples}"),
                ("Msgs/Min:", f"{accepted}"),
            )
            for i, (label, value) in enumerate(rows):
                cy = self.y + i * self.line_height
                draw.text((self.x, cy), label, font=font.DEFAULT, fill=self.ui.theme.fg)
                draw.text((self.x + 80, cy), value, font=font.DEFAULT, fill=self.ui.theme.secondary)

        except (KeyError, IndexError, TypeError) as e:
            draw.text((self.x, self.y), "No receiver data",
                      font=font.DEFAULT, fill=self.ui.theme.error)
            LOGGER.exception(f"Receiver stats render error: {e}")
