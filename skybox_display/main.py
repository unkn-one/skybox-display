import logging
import sys

from skybox_display.app import App


def main():
    # Configure logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logger = logging.getLogger(__name__)

    try:
        app = App()
        app.run()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
