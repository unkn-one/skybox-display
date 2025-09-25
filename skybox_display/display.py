import logging
import threading
import typing
from fcntl import ioctl
from typing import Any

import numpy as np
from inotify_simple import INotify, flags

from skybox_display import concurrency

if typing.TYPE_CHECKING:
    from PIL.Image import Image

LOGGER = logging.getLogger(__name__)


class Display(concurrency.Threaded):
    """Framebuffer display handler."""
    VT_ACTIVATE = 0x5606  # ioctl command to switch TTY

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.fb_path = config["fb_path"]
        self.target_tty = config["target_tty"]
        self._active_event = threading.Event()
        self._tty_path = "/sys/class/tty/tty0/active"
        self._tty_notify = INotify()
        self._tty_notify.add_watch(self._tty_path, flags.MODIFY)
        self._prev_tty = None
        LOGGER.info(f"Initialized display on {self.fb_path}, active on {self.target_tty}")

    def _execute(self) -> None:
        events = self._tty_notify.read(timeout=250)  # milliseconds
        for event in events:
            if event.mask & flags.MODIFY:
                with open(self._tty_path, "r") as f:
                    current_tty = f.read().strip()

                LOGGER.info(f"Active TTY changed to {current_tty}")
                if current_tty == self.target_tty:
                    self._active_event.set()
                else:
                    self._active_event.clear()

    def _get_active_tty(self) -> str | None:
        """Read and return the currently active TTY name (e.g., 'tty1')."""
        try:
            with open(self._tty_path, "r") as f:
                return f.read().strip()
        except Exception as e:
            LOGGER.exception(f"Unable to get current TTY: {e}")
            return None

    def _activate_tty(self, tty_name: str) -> bool:
        """Activate a TTY by name and update internal active flag.

        Returns True on success, False otherwise.
        """
        if not tty_name or not tty_name.startswith("tty"):
            return False
        try:
            with open("/dev/tty0", "w") as tty:
                ioctl(tty, self.VT_ACTIVATE, int(tty_name.removeprefix("tty")))
            if tty_name == self.target_tty:
                self._active_event.set()
            else:
                self._active_event.clear()
            return True
        except Exception as e:
            LOGGER.exception(f"Unable to switch to {tty_name}: {e}")
            return False

    def is_active(self) -> bool:
        return self._active_event.is_set()

    def switch_to_target(self) -> None:
        """Switch to the target TTY."""
        self._prev_tty = self._get_active_tty()
        self._activate_tty(self.target_tty)

    def switch_to_prev(self) -> None:
        """Switch back to the previously active TTY if known."""
        if not self._prev_tty:
            return
        self._activate_tty(self._prev_tty)

    def show(self, img: "Image") -> None:
        """Display an image on the framebuffer."""
        try:
            # Convert PIL image to RGB565 format for framebuffer
            arr = np.array(img, dtype=np.uint16)
            r = (arr[:, :, 0] >> 3) & 0x1F
            g = (arr[:, :, 1] >> 2) & 0x3F
            b = (arr[:, :, 2] >> 3) & 0x1F
            rgb565 = (r << 11) | (g << 5) | b

            with open(self.fb_path, "wb") as f:
                f.write(rgb565.astype("<u2").tobytes())
        except Exception as e:
            LOGGER.exception(f"Display error: {e}")
