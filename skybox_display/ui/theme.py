import logging
from dataclasses import dataclass, asdict

import yaml

from skybox_display.config import get_config_path


LOGGER = logging.getLogger(__name__)
Color = tuple[int, int, int]


@dataclass
class Theme:
    bg: Color
    tab_bg: Color
    fg: Color
    secondary: Color
    neutral: Color
    shade: Color
    accent: Color
    accent_2: Color
    # Tab-specific accents
    aircraft_page: Color
    radar_page: Color
    receiver_page: Color
    system_page: Color
    settings_page: Color
    # Status colors
    error: Color
    success: Color


CACHE: dict[str, Theme] | None = None
DEFAULT_THEMES = {
    "Vaporwave": Theme(
        bg = (20, 10, 30),  # Very dark purple
        tab_bg = (35, 20, 50),  # Muted violet
        fg = (240, 240, 255),  # Light purple-white
        secondary = (160, 140, 190),  # Muted lavender
        neutral = (100, 90, 120),  # Gray-purple
        shade = (70, 50, 100),  # Deep violet
        accent = (255, 255, 20),  # Yellow
        accent_2 = (50, 255, 50),  # Bright green

        # Tab-specific accent colors
        aircraft_page = (255, 20, 147),  # Deep pink
        radar_page = (50, 255, 50),  # Bright green
        receiver_page = (0, 255, 255),  # Cyan
        system_page = (186, 85, 211),  # Medium orchid
        settings_page = (255, 165, 0),  # Orange

        error = (255, 100, 100),
        success = (100, 255, 200)
    ),

    # Atom One Dark inspired
    "One Dark": Theme(
        bg = (40, 44, 52),
        tab_bg = (36, 40, 47),
        fg = (171, 178, 191),
        secondary = (97, 175, 239),
        neutral = (92, 99, 112),
        shade = (62, 68, 81),
        accent = (229, 192, 123),
        accent_2 = (152, 195, 121),

        aircraft_page = (224, 108, 117),
        radar_page = (152, 195, 121),
        receiver_page = (86, 182, 194),
        system_page = (198, 120, 221),
        settings_page = (209, 154, 102),

        error = (224, 108, 117),
        success = (152, 195, 121)
    ),

    # Monokai
    "Monokai": Theme(
        bg = (39, 40, 34),
        tab_bg = (30, 31, 28),
        fg = (248, 248, 242),
        secondary = (102, 217, 239),
        neutral = (117, 113, 94),
        shade = (59, 58, 50),
        accent = (253, 151, 31),
        accent_2 = (166, 226, 46),

        aircraft_page = (249, 38, 114),
        radar_page = (166, 226, 46),
        receiver_page = (102, 217, 239),
        system_page = (174, 129, 255),
        settings_page = (253, 151, 31),

        error = (249, 38, 114),
        success = (166, 226, 46)
    ),

    # Solarized Dark
    "Solarized Dark": Theme(
        bg = (0, 43, 54),
        tab_bg = (7, 54, 66),
        fg = (147, 161, 161),
        secondary = (38, 139, 210),
        neutral = (88, 110, 117),
        shade = (7, 54, 66),
        accent = (181, 137, 0),
        accent_2 = (42, 161, 152),

        aircraft_page = (220, 50, 47),
        radar_page = (133, 153, 0),
        receiver_page = (42, 161, 152),
        system_page = (108, 113, 196),
        settings_page = (203, 75, 22),

        error = (220, 50, 47),
        success = (133, 153, 0)
    ),

    # Solarized Light
    "Solarized Light": Theme(
        bg = (253, 246, 227),   # base3
        tab_bg = (238, 232, 213),
        fg = (101, 123, 131),   # base00
        secondary = (38, 139, 210),
        neutral = (131, 148, 150),  # base1
        shade = (238, 232, 213),
        accent = (181, 137, 0),
        accent_2 = (133, 153, 0),

        aircraft_page = (220, 50, 47),
        radar_page = (133, 153, 0),
        receiver_page = (42, 161, 152),
        system_page = (108, 113, 196),
        settings_page = (203, 75, 22),

        error = (220, 50, 47),
        success = (133, 153, 0)
    ),

    # Dracula
    "Dracula": Theme(
        bg = (40, 42, 54),
        tab_bg = (30, 31, 41),
        fg = (248, 248, 242),
        secondary = (139, 233, 253),
        neutral = (98, 114, 164),
        shade = (68, 71, 90),
        accent = (255, 184, 108),
        accent_2 = (80, 250, 123),

        aircraft_page = (255, 121, 198),
        radar_page = (80, 250, 123),
        receiver_page = (139, 233, 253),
        system_page = (189, 147, 249),
        settings_page = (255, 184, 108),

        error = (255, 85, 85),
        success = (80, 250, 123)
    ),

    # Gruvbox Dark
    "Gruvbox Dark": Theme(
        bg = (40, 40, 40),
        tab_bg = (29, 32, 33),
        fg = (235, 219, 178),
        secondary = (131, 165, 152),
        neutral = (146, 131, 116),
        shade = (60, 56, 54),
        accent = (250, 189, 47),
        accent_2 = (184, 187, 38),

        aircraft_page = (251, 73, 52),
        radar_page = (184, 187, 38),
        receiver_page = (142, 192, 124),
        system_page = (211, 134, 155),
        settings_page = (254, 128, 25),

        error = (251, 73, 52),
        success = (184, 187, 38)
    ),

    # Gruvbox Light
    "Gruvbox Light": Theme(
        bg = (251, 241, 199),
        tab_bg = (242, 229, 188),
        fg = (60, 56, 54),
        secondary = (131, 165, 152),
        neutral = (146, 131, 116),
        shade = (235, 219, 178),
        accent = (215, 153, 33),
        accent_2 = (152, 151, 26),

        aircraft_page = (204, 36, 29),
        radar_page = (152, 151, 26),
        receiver_page = (131, 165, 152),
        system_page = (177, 98, 134),
        settings_page = (214, 93, 14),

        error = (204, 36, 29),
        success = (152, 151, 26)
    ),

    # Nord
    "Nord": Theme(
        bg = (46, 52, 64),
        tab_bg = (43, 48, 59),
        fg = (216, 222, 233),
        secondary = (136, 192, 208),
        neutral = (76, 86, 106),
        shade = (59, 66, 82),
        accent = (235, 203, 139),
        accent_2 = (163, 190, 140),

        aircraft_page = (191, 97, 106),
        radar_page = (163, 190, 140),
        receiver_page = (136, 192, 208),
        system_page = (180, 142, 173),
        settings_page = (208, 135, 112),

        error = (191, 97, 106),
        success = (163, 190, 140)
    ),
}


# Represent Color tuples as hex strings in yaml
def dump_color_tuple(data):
    return "${:02X}{:02X}{:02X}".format(*data)


def load_color_tuple(data):
    try:
        if data[0] != "$":
            raise ValueError
        color_int = int(data[1:], 16)
        r = (color_int >> 16) & 0xFF
        g = (color_int >> 8) & 0xFF
        b = color_int & 0xFF
        return r, g, b
    except Exception as e:
        raise ValueError(f"Invalid color str {data}") from e


def load_themes() -> dict[str, Theme]:
    """Load themes.yml from package resources and cache the result."""
    global CACHE
    if CACHE is not None:
        return CACHE

    themes = DEFAULT_THEMES
    theme_path = get_config_path("themes.yml")
    try:
        with theme_path.open() as f:
            data = yaml.safe_load(f)
            if data:
                themes = {name: Theme(**{k: load_color_tuple(v)
                                         for k, v in theme.items()})
                          for name, theme in data.items()}
    except FileNotFoundError:
        LOGGER.info("Themes config not found. Regenerating")

        with theme_path.open("w") as f:
            data = {name: {k: dump_color_tuple(v) for k, v in asdict(theme).items()}
                    for name, theme in DEFAULT_THEMES.items()}
            yaml.safe_dump(data, f, sort_keys=False)
        LOGGER.info(f"Saved themes config to: {theme_path}")
    except Exception as e:
        LOGGER.exception(f"Unable to load themes: {e}")

    CACHE = themes
    return themes


def get_theme_names() -> list[str]:
    return list(load_themes().keys())


def get_theme(name: str) -> Theme:
    return load_themes().get(name)
