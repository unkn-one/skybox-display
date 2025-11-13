import logging
import signal
import sys

from skybox_display.app import App


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logger = logging.getLogger(__name__)

    try:
        app = App()

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda s, f: app.cleanup())

        app.run()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
