import logging
from pathlib import Path
from PIL import ImageFont

LOGGER = logging.getLogger(__name__)


def load_font(font: str, size) -> ImageFont:
        base_path = Path("/usr/share/fonts/truetype/")
        font_path = base_path / font
        try:
            return ImageFont.truetype(font_path, size)
        except (FileNotFoundError, OSError):
            LOGGER.warning(f"Font {font_path} not found, using default")
            return ImageFont.load_default()


DEFAULT = load_font("dejavu/DejaVuSans.ttf", 14)
HEADER = load_font("dejavu/DejaVuSansMono-Bold.ttf", 14)
DATA = load_font("dejavu/DejaVuSansMono.ttf", 14)
SMALL = load_font("dejavu/DejaVuSans.ttf", 10)
ICON = load_font("material-design-icons-iconfont/MaterialIcons-Regular.ttf", 30)
