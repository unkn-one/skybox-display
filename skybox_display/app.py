import logging
import os
import sys
import time

import evdev

from skybox_display import config, collector, display, keyboard, ui

LOGGER = logging.getLogger(__name__)

class App:
    """Main application class that coordinates all components."""

    def __init__(self):
        """Initialize the application."""
        self.config = config.load_config()
        ui.load_themes()
        self.ui = ui.UI(self, self.config)
        self.collector = collector.DataCollector(self.config)
        self.display = display.Display(self.config)
        self.keyboard = keyboard.KeyboardInput()
        self.running = False

    def connect_keyboard(self):
        """Connect keyboard callbacks."""
        self.keyboard.set_callback(evdev.ecodes.KEY_UP, self.ui.on_prev)
        self.keyboard.set_callback(evdev.ecodes.KEY_DOWN, self.ui.on_next)
        self.keyboard.set_callback(evdev.ecodes.KEY_ENTER, self.ui.on_ok)
        self.keyboard.set_callback(evdev.ecodes.KEY_BACKSPACE, self.ui.on_cancel)

    def run(self) -> None:
        """Run the main application loop."""
        LOGGER.info("Starting application")

        if os.geteuid() != 0:
            LOGGER.error("You need to run this program as root")
            sys.exit(1)

        self.display.start()
        self.collector.start()
        self.connect_keyboard()
        self.keyboard.start()

        self.display.switch_to_target()
        self.running = True
        try:
            while self.running:
                loop_start = time.monotonic()
                if self.display.is_active():
                    stats = self.collector.snapshot()
                    img = self.ui.render(stats)
                    self.display.show(img)

                # Sleep only the remaining time up to display_interval
                remaining = self.config["display_interval"] - (time.monotonic() - loop_start)
                if remaining > 0:
                    time.sleep(remaining)

        except KeyboardInterrupt:
            LOGGER.info("Interrupted by user")
        except Exception as e:
            LOGGER.exception(f"Application error: {e}")
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """Clean up resources before exit."""
        LOGGER.info("Cleaning up")
        self.running = False
        try:
            config.save_config(self.config)
        except Exception as e:
            LOGGER.exception(f"Unable to save on exit: {e}")
        self.display.switch_to_prev()
        self.keyboard.stop(join_timeout=1.0)
        self.collector.stop(join_timeout=1.0)
        self.display.stop(join_timeout=1.0)
