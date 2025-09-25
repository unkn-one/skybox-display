import glob
import logging
import selectors
import time
from typing import Callable

import evdev

from skybox_display import concurrency


LOGGER = logging.getLogger(__name__)


class KeyboardInput(concurrency.Threaded):
    """Handles keyboard input from the device tree gpio-key overlays."""

    def __init__(self):
        super().__init__()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._selector = selectors.DefaultSelector()
        self._open_input_devices()

    def _open_input_devices(self) -> None:
        """Find and open button input devices."""
        device_pattern = "/dev/input/by-path/platform-button*-event"

        devices = glob.glob(device_pattern)
        LOGGER.info(f"Found input devices: {devices}")
        for device_path in devices:
            try:
                dev = evdev.InputDevice(device_path)
                self._selector.register(dev, selectors.EVENT_READ, data=dev)
                LOGGER.info(f"Registered device: {device_path}")
            except Exception as e:
                LOGGER.exception(f"Failed to open {device_path}: {e}")

    def set_callback(self, key: int, callback: Callable[[], None]) -> None:
        """Set callback for a specific key.

        Args:
            key: Key code to listen for
            callback: Function to call when key is pressed
        """
        self._callbacks[key] = callback

    def clear_callbacks(self):
        """Clear all existing callbacks."""
        self._callbacks = {}

    def _execute(self) -> None:
        """Main input listening loop."""
        for key, mask in self._selector.select(timeout=0.01):
            dev = key.data
            for event in dev.read():
                if event.type == evdev.ecodes.EV_KEY:
                    key_event = evdev.categorize(event)
                    if key_event.keystate == evdev.events.KeyEvent.key_up:
                        self._handle_key_press(key_event.scancode)

        time.sleep(0.01)  # Small delay to prevent excessive CPU usage

    def _handle_key_press(self, key_code: int) -> None:
        """Handle a key press."""
        if key_code in self._callbacks:
            try:
                self._callbacks[key_code]()
                LOGGER.debug(f"Handled key press: {key_code}")
            except Exception as e:
                LOGGER.exception(f"Callback error for key {key_code}: {e}")
