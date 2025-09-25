import contextlib
import copy
import evdev
import glob
import logging
import socket
import math
import os
import selectors
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from fcntl import ioctl
from pathlib import Path
from typing import Callable, Any

import numpy as np
import psutil
import requests
from PIL import Image, ImageDraw, ImageFont
from inotify_simple import INotify, flags

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

Color = tuple[int, int, int]

class Config:
    """Configuration constants for the application."""
    # Display
    fb_path = "/dev/fb1"
    active_tty = "tty8"
    width = 320
    height = 240
    display_interval = 0.2

    # Data sources setup
    timeout = 1.0
    piaware_stats_url = "http://localhost:8080/data/stats.json"
    piaware_aircraft_url = "http://localhost:8080/data/aircraft.json"
    aircraft_poll_interval = 0.5
    status_poll_interval = 1.0
    system_poll_interval = 5.0
    system_samples = 20

    # Radio position (configure these for your location)
    radio_lat = 54.3724396  # Example: Gdansk airport, Poland
    radio_lon = 18.49458

    # Radar view settings
    radar_max_range_km = 300  # Maximum range to display
    radar_center_dot_size = 3


@dataclass
class Theme:
    """Base theme class (colors must be provided by subclasses)."""
    Color = tuple[int, int, int]

    bg: Color
    tab_bg: Color
    fg: Color
    secondary: Color
    neutral: Color
    shade: Color
    accent: Color
    accent_2: Color
    # Tab-specific accents
    flight_tab: Color
    radar_tab: Color
    receiver_tab: Color
    system_tab: Color
    settings_tab: Color
    # Status colors
    error: Color
    success: Color


VaporwaveTheme = Theme(
    # Vaporwave color theme for the UI.
    bg = (20, 10, 30),  # Very dark purple
    tab_bg = (35, 20, 50),  # Muted violet
    fg = (240, 240, 255),  # Light purple-white
    secondary = (160, 140, 190),  # Muted lavender
    neutral = (100, 90, 120),  # Gray-purple
    shade = (70, 50, 100),  # Deep violet
    accent = (255, 255, 20),  # Yellow
    accent_2 = (50, 255, 50),  # Bright green

    # Tab-specific accent colors
    flight_tab = (255, 20, 147),  # Deep pink
    radar_tab = (50, 255, 50),  # Bright green
    receiver_tab = (0, 255, 255),  # Cyan
    system_tab = (186, 85, 211),  # Medium orchid
    settings_tab = (255, 165, 0),  # Orange

    error = (255, 100, 100),
    success = (100, 255, 200)
)


DarkOneTheme = Theme(
    # Atom One Dark inspired theme.
    bg = (40, 44, 52),
    tab_bg = (36, 40, 47),
    fg = (171, 178, 191),
    secondary = (97, 175, 239),
    neutral = (92, 99, 112),
    shade = (62, 68, 81),
    accent = (229, 192, 123),
    accent_2 = (152, 195, 121),

    # Tab-specific accent colors
    flight_tab = (224, 108, 117),   # red
    radar_tab = (152, 195, 121),    # green
    receiver_tab = (86, 182, 194),  # cyan
    system_tab = (198, 120, 221),   # purple
    settings_tab = (209, 154, 102), # orange

    error = (224, 108, 117),
    success = (152, 195, 121)
)


# Available themes mapping
THEMES: dict[str, Theme] = {
    "Vaporwave": VaporwaveTheme,
    "One Dark": DarkOneTheme,
}


class GeoUtils:
    """Utility functions for geographic calculations."""

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate the great circle distance between two points on Earth.

        Args:
            lat1, lon1: First point coordinates
            lat2, lon2: Second point coordinates

        Returns:
            Distance in kilometers
        """
        R = 6371.0  # Earth radius in kilometers

        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    @staticmethod
    def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate the bearing from point 1 to point 2.

        Args:
            lat1, lon1: First point coordinates
            lat2, lon2: Second point coordinates

        Returns:
            Bearing in degrees (0-360)
        """
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        dlon = lon2_rad - lon1_rad

        y = math.sin(dlon) * math.cos(lat2_rad)
        x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)

        bearing = math.atan2(y, x)
        bearing = math.degrees(bearing)
        bearing = (bearing + 360) % 360

        return bearing


class Threaded(threading.Thread):
    """Thread with stop support"""

    def __init__(self):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self._stop = threading.Event()

    def stop(self, join_timeout: float | None = None) -> None:
        """Signal the thread to stop and optionally join.

        Args:
            join_timeout: If provided, block up to this many seconds
                          for the thread to finish. If None, do not join.
        """
        self._stop.set()
        # Avoid deadlock if called from within the same thread
        if join_timeout is not None and threading.current_thread() is not self:
            if self.is_alive():
                try:
                    self.join(timeout=join_timeout)
                except Exception:
                    pass

    def run(self) -> None:
        logger.debug(f"Starting {self.name} thread")
        try:
            while not self._stop.is_set():
                self._execute()
        finally:
            self._clean()

    def _execute(self) -> None:
        pass

    def _clean(self):
        pass


class DataCollector(Threaded):
    """Collects data from various sources in a separate thread."""

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._stats: dict[str, Any] = {"status": "unknown", "last_update": 0}
        self._aircraft: dict[str, Any] = {"status": "unknown", "last_update": 0, "aircraft": []}
        self._system: dict[str, Any] = {
            "cpu": deque(maxlen=Config.system_samples),
            "mem": deque(maxlen=Config.system_samples),
            "temp": deque(maxlen=Config.system_samples),
            "ip": str | None,
        }
        # Task scheduler: name, function, interval, next due time, and optional error target for status marking
        now = time.monotonic()
        self._tasks: list[dict[str, Any]] = [
            {
                "name": "aircraft",
                "fn": self.update_aircraft,
                "interval": Config.aircraft_poll_interval,
                "due": now,
                "error_target": "aircraft",
            },
            {
                "name": "stats",
                "fn": self.update_stats,
                "interval": Config.status_poll_interval,
                "due": now,
                "error_target": "stats",
            },
            {
                "name": "system",
                "fn": self.update_system,
                "interval": Config.system_poll_interval,
                "due": now,
                "error_target": None,
            },
        ]

    def _execute(self) -> None:
        """Scheduler loop: run each task at its configured interval."""
        now = time.monotonic()
        next_due = float("inf")

        for t in self._tasks:
            due = t["due"]
            interval = float(t["interval"]) if t["interval"] else 1.0
            if now >= due:
                self._run_task(t["name"], t["fn"], t.get("error_target"))
                # Advance due by whole intervals to avoid drift/catch-up storms
                intervals = max(1, int((now - due) // interval) + 1)
                t["due"] = due + intervals * interval
            next_due = min(next_due, t["due"])

        # Sleep until the earliest next due, bounded for responsiveness
        sleep_for = max(0.01, min(0.25, next_due - time.monotonic()))
        self._stop.wait(sleep_for)

    def _run_task(self, name: str, fn: Callable[[], None], error_target: str | None) -> None:
        """Run a polling task with unified error handling and status marking."""
        try:
            fn()
        except requests.RequestException as e:
            logger.error(f"{name.capitalize()} update failed: {e}")
            if error_target:
                with self._lock:
                    if error_target == "aircraft":
                        self._aircraft["status"] = "error"
                    elif error_target == "stats":
                        self._stats["status"] = "error"

    def update_stats(self) -> None:
        """Update PiAware statistics."""
        r = requests.get(Config.piaware_stats_url, timeout=Config.timeout)
        r.raise_for_status()
        data = r.json()
        with self._lock:
            self._stats = data
            self._stats["status"] = "ok"
            self._stats["last_update"] = time.time()

    def update_aircraft(self) -> None:
        """Update aircraft data."""
        r = requests.get(Config.piaware_aircraft_url, timeout=Config.timeout)
        r.raise_for_status()
        data = r.json()

        # Calculate distances for aircraft with position data
        aircraft_list = data.get("aircraft", [])
        for aircraft in aircraft_list:
            lat = aircraft.get("lat")
            lon = aircraft.get("lon")
            if lat is not None and lon is not None:
                distance = GeoUtils.haversine_distance(
                    Config.radio_lat, Config.radio_lon, lat, lon
                )
                aircraft["distance_km"] = distance

        with self._lock:
            self._aircraft = data
            self._aircraft["status"] = "ok"
            self._aircraft["last_update"] = time.time()

    def update_system(self) -> None:
        """Update system statistics (CPU, memory, temperature)."""
        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory().percent
        temp = self._get_temperature()
        ip = self._get_primary_ip()

        with self._lock:
            self._system["cpu"].append(cpu)
            self._system["mem"].append(mem)
            self._system["temp"].append(temp)
            self._system["ip"] = ip

    def _get_temperature(self) -> float:
        """Get system temperature."""
        try:
            return psutil.sensors_temperatures().get('cpu_thermal')[0].current
        except Exception as e:
            logger.warning(f"Unable to get temperature: {e}")
            return 0

    def _get_primary_ip(self) -> str | None:
        """Return the first IPv4 from preferred interfaces."""
        preferred = ("eth0", "wlan0", "en0")
        addrs = psutil.net_if_addrs()
        for name in preferred:
            for addr in addrs.get(name, []):
                if getattr(addr, "family", None) == socket.AF_INET:
                    ip = getattr(addr, "address", None)
                    if ip:
                        return ip

    def snapshot(self) -> dict[str, Any]:
        """Get a thread-safe snapshot of all collected data."""
        with self._lock:
            return {
                "stats": copy.deepcopy(self._stats),
                "aircraft": copy.deepcopy(self._aircraft),
                "system": {
                    "cpu": list(self._system["cpu"]),
                    "mem": list(self._system["mem"]),
                    "temp": list(self._system["temp"]),
                    "ip": self._system["ip"],
                }
            }


class KeyboardInput(Threaded):
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
        logger.info(f"Found input devices: {devices}")
        for device_path in devices:
            try:
                dev = evdev.InputDevice(device_path)
                self._selector.register(dev, selectors.EVENT_READ, data=dev)
                logger.info(f"Registered device: {device_path}")
            except Exception as e:
                logger.exception(f"Failed to open {device_path}: {e}")

    def set_callback(self, key: int, callback: Callable[[], None]) -> None:
        """Set callback for a specific key.

        Args:
            key: Key code to listen for
            callback: Function to call when key is pressed
        """
        self._callbacks[key] = callback

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
                logger.debug(f"Handled key press: {key_code}")
            except Exception as e:
                logger.exception(f"Callback error for key {key_code}: {e}")


class Display(Threaded):
    """Framebuffer display handler."""
    VT_ACTIVATE = 0x5606  # ioctl command to switch TTY

    def __init__(self, fb_path: str, target_tty: str):
        """Initialize the display.

        Args:
            fb_path: Path to framebuffer device
            target_tty: Display only when specific tty is active
        """
        super().__init__()
        self.fb_path = fb_path
        self.target_tty = target_tty
        self._active_event = threading.Event()
        self._tty_path = "/sys/class/tty/tty0/active"
        self._tty_notify = INotify()
        self._tty_notify.add_watch(self._tty_path, flags.MODIFY)
        self._prev_tty = None
        logger.info(f"Initialized display on {fb_path}, active on {target_tty}")

    def _execute(self) -> None:
        events = self._tty_notify.read(timeout=250)  # milliseconds
        for event in events:
            if event.mask & flags.MODIFY:
                with open(self._tty_path, "r") as f:
                    current_tty = f.read().strip()

                logger.info(f"Active TTY changed to {current_tty}")
                if current_tty == self.target_tty:
                    self._active_event.set()
                else:
                    self._active_event.clear()

    def _get_active_tty(self) -> str | None:
        """Read and return the currently active TTY name (e.g., 'tty1')."""
        try:
            with open(self._tty_path, "r") as f:
                return f.read().strip()
        except Exception:
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
        except Exception:
            logger.exception(f"Unable to switch to {tty_name}")
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

    def show(self, img: Image.Image) -> None:
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
            logger.exception(f"Display error: {e}")


class UI:
    """User interface renderer."""

    def __init__(self, width: int, height: int, theme: Theme):
        """Initialize the UI."""
        self.width = width
        self.height = height
        self.theme = theme
        self.active_page = 0
        self.aircraft_display_toggle = True
        self.aircraft_scroll_mode = False
        self.aircraft_scroll_offset = 0
        self._last_aircraft_total = 0
        self._last_aircraft_max_lines = 0
        self.radar_scale_mode = "log5"   # or "linear"

        # Tab configuration
        self.tabs = [
            {"name": "Aircraft Info", "icon": "\ue539", "accent": theme.flight_tab, "render": self._render_flight_page},
            {"name": "Virtual Radar", "icon": "\uf04e", "accent": theme.radar_tab, "render": self._render_radar_page},
            {"name": "Receiver Stats", "icon": "\ue8bf", "accent": theme.receiver_tab, "render": self._render_receiver_page},
            {"name": "System Info", "icon": "\ue322", "accent": theme.system_tab, "render": self._render_system_page},
            {"name": "Settings", "icon": "\ue8b8", "accent": theme.settings_tab, "render": self._render_settings_page},
        ]

        self.tab_width = 40
        self.header_height = 24

        self.font = self._load_font("dejavu/DejaVuSans.ttf", 14)
        self.header_font = self._load_font("dejavu/DejaVuSansMono-Bold.ttf", 14)
        self.data_font = self._load_font("dejavu/DejaVuSansMono.ttf", 14)
        self.small_font = self._load_font("dejavu/DejaVuSans.ttf", 10)
        self.icon_font = self._load_font("material-design-icons-iconfont/MaterialIcons-Regular.ttf", 30)

        self._layer_cache: dict[tuple, Image.Image] = {}

        # Settings state
        # Derive current theme name from provided theme instance
        self.theme_name = next((name for name, th in THEMES.items() if theme == th), "Vaporwave")
        self.settings_mode = "off"  # off | select | edit
        self.settings_index = 0
        theme_names = list(THEMES.keys())
        selected_idx = theme_names.index(self.theme_name) if self.theme_name in theme_names else 0
        self.settings_items = [{
            "key": "theme",
            "label": "Theme",
            "values": theme_names,
            "index": selected_idx,
            "pending": None,
        }]

    def _load_font(self, font: str, size) -> ImageFont:
        base_path = Path("/usr/share/fonts/truetype/")
        font_path = base_path / font
        try:
            return ImageFont.truetype(font_path, size)
        except (FileNotFoundError, OSError):
            logger.warning(f"Font {font_path} not found, using default")
            return ImageFont.load_default()

    def set_page(self, idx: int) -> None:
        """Set the active page."""
        self.active_page = idx % len(self.tabs)
        logger.info(f"Switched to page {self.active_page}: {self.tabs[self.active_page]['name']}")

    def on_next(self) -> None:
        # Settings page navigation when in select/edit modes
        if self.active_page == self._settings_tab_idx() and self.settings_mode in ("select", "edit"):
            if self.settings_mode == "select":
                self.settings_index = min(len(self.settings_items) - 1, self.settings_index + 1)
            else:  # edit mode cycles values
                item = self.settings_items[self.settings_index]
                cur = item["pending"] if item["pending"] is not None else item["index"]
                item["pending"] = (cur + 1) % len(item["values"])
        elif self.active_page == 0 and self.aircraft_scroll_mode:
            self._scroll_aircraft(+1)
        else:
            self.set_page(self.active_page + 1)

    def on_prev(self) -> None:
        if self.active_page == self._settings_tab_idx() and self.settings_mode in ("select", "edit"):
            if self.settings_mode == "select":
                self.settings_index = max(0, self.settings_index - 1)
            else:
                item = self.settings_items[self.settings_index]
                cur = item["pending"] if item["pending"] is not None else item["index"]
                item["pending"] = (cur - 1) % len(item["values"])
        elif self.active_page == 0 and self.aircraft_scroll_mode:
            self._scroll_aircraft(-1)
        else:
            self.set_page(self.active_page - 1)

    def on_ok(self) -> None:
        if self.active_page == self._settings_tab_idx():
            if self.settings_mode == "off":
                # Enter settings selection mode
                self.settings_mode = "select"
                self.settings_index = 0
            elif self.settings_mode == "select":
                # Enter edit mode for current item
                self.settings_mode = "edit"
                item = self.settings_items[self.settings_index]
                if item["pending"] is None:
                    item["pending"] = item["index"]
            elif self.settings_mode == "edit":
                # Confirm change
                item = self.settings_items[self.settings_index]
                if item["pending"] is not None:
                    item["index"] = item["pending"]
                item["pending"] = None
                self.settings_mode = "select"
                self._apply_setting(item)
        elif self.active_page == 0:
            # Toggle scroll mode for aircraft list
            self.aircraft_scroll_mode = not self.aircraft_scroll_mode
        elif self.active_page == 1:
            scales = ["linear", "log5", "log10"]
            current_idx = scales.index(self.radar_scale_mode)
            self.radar_scale_mode = scales[(current_idx + 1) % len(scales)]

    def on_cancel(self) -> None:
        if self.active_page == self._settings_tab_idx():
            if self.settings_mode == "edit":
                # Discard pending and go back to select
                item = self.settings_items[self.settings_index]
                item["pending"] = None
                self.settings_mode = "select"
            elif self.settings_mode == "select":
                # Exit settings interaction
                self.settings_mode = "off"
        elif self.active_page == 0:
            self.aircraft_display_toggle = not self.aircraft_display_toggle


    def render(self, stats: dict[str, Any]) -> Image.Image:
        """Render the current UI state."""
        img = Image.new("RGB", (self.width, self.height), self.theme.bg)
        draw = ImageDraw.Draw(img)

        current_tab = self.tabs[self.active_page]

        with self._cached_draw(draw, ("page", self.active_page)) as layer_draw:
            if layer_draw:
                self._draw_page(layer_draw, self.active_page)

        # Draw header text
        draw.text((self.tab_width + 5, 5), current_tab["name"].upper(), font=self.header_font, fill=self.theme.bg)

        # Draw content
        pad = 8
        content_x = self.tab_width + pad
        content_y = self.header_height + pad
        content_width = self.width - content_x - pad
        content_height = self.height - content_y - pad

        renderer = current_tab.get("render")
        if callable(renderer):
            renderer(draw, stats, content_x, content_y, content_width, content_height)

        return img

    @contextlib.contextmanager
    def _cached_draw(self, draw: ImageDraw.ImageDraw, key: tuple) -> Image.Image:
        """Return cached transparent overlay for given key or render and cache it."""
        layer_draw = None
        layer = self._layer_cache.get(key)
        if layer is None:
            layer = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            self._layer_cache[key] = layer
            layer_draw = ImageDraw.Draw(layer)
        yield layer_draw
        draw._image.paste(layer, layer)

    def _draw_page(self, draw: ImageDraw.ImageDraw, active_page: int) -> None:
        """Draw the page with header, sidebar and tabs."""
        current_tab = self.tabs[active_page]
        accent_color = current_tab["accent"]

        # Sidebar background
        draw.rectangle([0, 0, self.tab_width, self.height], fill=self.theme.tab_bg)

        tab_height = self.height // len(self.tabs)

        for i, tab in enumerate(self.tabs):
            y_start = i * tab_height
            y_end = (i + 1) * tab_height

            if i == active_page:
                # Highlight active tab
                draw.rectangle([0, y_start, self.tab_width, y_end], fill=tab["accent"])
                icon_color = self.theme.bg
            else:
                icon_color = self.theme.fg

            # Draw icon
            icon_x = self.tab_width // 2
            icon_y = y_start + tab_height // 2
            draw.text((icon_x, icon_y), tab["icon"], font=self.icon_font, fill=icon_color, anchor="mm")

        header_rect = [self.tab_width, 0, self.width, self.header_height]
        draw.rectangle(header_rect, fill=accent_color)

        # Draw border around content area
        content_rect = (self.tab_width, self.header_height, self.width - 1, self.height - 1)
        draw.rectangle(content_rect, outline=accent_color, width=1)

    def _draw_heading_arrow(self, draw: ImageDraw.ImageDraw, x: float, y: float,
                            heading: float, size: int = 8, color: Color | None = None) -> None:
        """Draw a heading arrow pointing in the specified direction.

        Args:
            draw: PIL ImageDraw object
            x, y: Center position of the arrow
            heading: Heading in degrees (0 = North, 90 = East)
            size: Size of the arrow
            color: Arrow color (defaults to accent_text)
        """
        if color is None:
            color = self.theme.accent

        # Convert heading to radians (subtract 90 to make 0 degrees point up)
        angle = math.radians(heading - 90)

        # Calculate arrow points
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        # Arrow tip
        tip_x = x + size * cos_a
        tip_y = y + size * sin_a

        # Arrow base points
        base_angle1 = angle + math.radians(150)
        base_angle2 = angle + math.radians(210)

        base1_x = x + (size * 0.6) * math.cos(base_angle1)
        base1_y = y + (size * 0.6) * math.sin(base_angle1)

        base2_x = x + (size * 0.6) * math.cos(base_angle2)
        base2_y = y + (size * 0.6) * math.sin(base_angle2)

        # Draw the arrow
        points = [(tip_x, tip_y), (base1_x, base1_y), (base2_x, base2_y)]
        draw.polygon(points, fill=color)

    def _render_flight_page(self, draw: ImageDraw.ImageDraw, stats: dict[str, Any],
                            x: int, y: int, width: int, height: int) -> None:
        """Render the flight information page.

        Args:
            draw: PIL ImageDraw object
            stats: Statistics dictionary
            x, y: Content area position
            width, height: Content area dimensions
        """

        aircraft_data = stats.get("aircraft", {})
        aircraft_list = aircraft_data.get("aircraft", [])

        # Aircraft list
        list_y = y
        line_height = 14
        max_lines = max(1, height // line_height)

        # Update last-known paging metrics
        total = len(aircraft_list)
        self._last_aircraft_total = total
        self._last_aircraft_max_lines = max_lines

        # Clamp scroll offset
        max_offset = max(0, total - max_lines)
        if self.aircraft_scroll_offset > max_offset:
            self.aircraft_scroll_offset = max_offset
        if self.aircraft_scroll_offset < 0:
            self.aircraft_scroll_offset = 0

        start_idx = self.aircraft_scroll_offset

        for i, aircraft in enumerate(aircraft_list[start_idx:start_idx + max_lines]):
            item_y = list_y + i * line_height

            if self.aircraft_display_toggle:
                # Show flight name, distance, and speed
                flight = aircraft.get("flight", "").strip() or "N/A"
                distance = aircraft.get("distance_km")
                dist_text = f"{distance:.1f}km" if distance is not None else "N/A"

                speed = aircraft.get("gs", 0)
                speed_text = f"{int(speed * 1.852)}km/h" if speed else "N/A"

                draw.text((x, item_y), flight, font=self.data_font, fill=self.theme.accent)
                draw.text((x + 70, item_y), dist_text, font=self.font, fill=self.theme.fg)
                draw.text((x + 150, item_y), speed_text, font=self.font, fill=self.theme.secondary)

                # Draw heading arrow if available
                heading = aircraft.get("track") or aircraft.get("mag_heading") or aircraft.get("true_heading")
                if heading is not None:
                    arrow_x = x + width - 20
                    arrow_y = item_y + 7
                    self._draw_heading_arrow(draw, arrow_x, arrow_y, heading, 6, self.theme.accent_2)
            else:
                # Show hex, altitude, and RSSI
                hex_code = aircraft.get("hex", "N/A")
                altitude = aircraft.get("alt_baro", aircraft.get("altitude", 0))
                alt_text = (f"{int(altitude / 3.2808)}m" if isinstance(altitude, int) else altitude) if altitude else "N/A"
                rssi = aircraft.get("rssi", aircraft.get("signal", 0))
                rssi_text = f"{rssi:.1f}dB" if rssi else "N/A"

                draw.text((x, item_y), hex_code, font=self.data_font, fill=self.theme.accent)
                draw.text((x + 70, item_y), alt_text, font=self.font, fill=self.theme.fg)
                draw.text((x + 140, item_y), rssi_text, font=self.font, fill=self.theme.neutral)

        # Scrollbar (show only if content exceeds page)
        if total > max_lines:
            rail_x = x + width - 3
            rail_y0 = y
            rail_y1 = y + height
            # Rail line
            draw.line((rail_x, rail_y0, rail_x, rail_y1), fill=self.theme.shade, width=1)

            # Thumb size and position
            content_h = height
            # Minimum thumb height at least one line
            thumb_h = max(line_height, int(content_h * (max_lines / total)))
            # Position proportional to offset
            max_off = max(1, total - max_lines)
            pos_ratio = self.aircraft_scroll_offset / max_off
            thumb_y = rail_y0 + int((content_h - thumb_h) * pos_ratio)

            thumb_color = self.tabs[self.active_page]["accent"] if self.aircraft_scroll_mode else self.theme.secondary
            draw.rectangle((rail_x - 2, thumb_y, rail_x + 2, thumb_y + thumb_h), outline=thumb_color, fill=None, width=1)

    def _quantise_range_25(self, km: float) -> float:
        """Clip/quantise range to 25 km increments and cap by config."""
        return max(25.0, min(Config.radar_max_range_km, math.ceil(km / 25.0) * 25.0))

    def _radar_px_radius(self, d_km: float, dmax_km: float, radius: float) -> float:
        """Map distance (km) to pixels using current scale mode."""
        dmax_km = max(dmax_km, 1e-3)
        ratio = min(max(d_km / dmax_km, 0.0), 1.0)

        if self.radar_scale_mode == "log5":
            f = math.log(1.0 + 4.0 * ratio, 5.0)
        elif self.radar_scale_mode == "log10":
            f = math.log(1.0 + 9.0 * ratio, 10.0)
        else:  # linear
            f = ratio

        return min(max(f, 0.0), 1.0) * radius

    def _draw_radar_grid(self, draw: ImageDraw.ImageDraw, cx: int, cy: int,
                         radius: int, dmax_km: float) -> None:
        """Crosshair, alternating ring labels (no units), N/E/S/W."""
        # crosshair
        draw.line((cx - radius, cy, cx + radius, cy), fill=self.theme.neutral)
        draw.line((cx, cy - radius, cx, cy + radius), fill=self.theme.neutral)

        # ring step (~≤5 rings)
        candidates = [1, 2, 5, 10, 20, 25, 50, 100, 200, 300, 400, 500]
        step = next((s for s in candidates if (dmax_km // s) <= 5), candidates[-1])
        n = int(dmax_km // step)

        labels = []
        for i in range(1, n + 1):
            r_km = i * step
            r_px = self._radar_px_radius(r_km, dmax_km, radius)
            draw.ellipse((cx - r_px, cy - r_px, cx + r_px, cy + r_px), outline=self.theme.shade)

            # Label: just the number, alternate sides to reduce overlap
            label = str(int(r_km))
            if i % 2:  # right side
                tx, ty, anchor = cx + r_px + 2, cy, "la"
            else:  # left side
                tx, ty, anchor = cx - r_px - 2, cy, "ra"
            labels.append(((tx, ty), label, anchor))

        # draw later to avoid overlap
        for pos, label, anchor in labels:
            draw.text(pos, label, font=self.small_font, fill=self.theme.secondary, anchor=anchor)

        # N/E/S/W
        # (("N", 0, -radius), ("E", radius, 0), ("S", 0, radius), ("W", -radius, 0))
        for lbl, dx, dy in (("N", 0, -radius), ("S", 0, radius)):
            draw.text((cx + dx, cy + dy), lbl, font=self.small_font, fill=self.theme.accent, anchor="mm")

    def _render_radar_page(self, draw: ImageDraw.ImageDraw, stats: dict[str, Any],
                           x: int, y: int, width: int, height: int) -> None:
        pad = 4
        cx = x + width // 2
        cy = y + height // 2
        radius = max(4, min(width, height) // 2 - pad)

        aircraft_data = stats.get("aircraft", {})
        aircraft_list = aircraft_data.get("aircraft", [])

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
                d = GeoUtils.haversine_distance(Config.radio_lat, Config.radio_lon, lat, lon)
            brg = GeoUtils.bearing(Config.radio_lat, Config.radio_lon, lat, lon)
            hdg = ac.get("track") or ac.get("mag_heading") or ac.get("true_heading")
            label = (ac.get("flight") or ac.get("callsign") or ac.get("hex") or "").strip()
            points.append((d, brg, hdg, label))
            dmax = max(dmax, d)

        # Quantised span: farthest * 1.1 → round up to 25 km steps (min 25, capped)
        dspan_raw = max(dmax * 1.1, 10.0)
        dspan = self._quantise_range_25(dspan_raw)

        # Cached grid
        with self._cached_draw(draw, ("radar_grid", dspan, self.radar_scale_mode)) as layer_draw:
            if layer_draw:
                self._draw_radar_grid(layer_draw, cx, cy, radius, dspan)
        
        # Range and scale
        draw.text((x, y), f"RNG: {int(dspan)}km", font=self.font,
                  fill=self.theme.secondary, anchor="la")
        draw.text((x, y + height), f"SCL: {self.radar_scale_mode.upper()}",
                  font=self.font, fill=self.theme.secondary, anchor="lb")
        
        # Ownship
        rdot = Config.radar_center_dot_size
        draw.ellipse((cx - rdot, cy - rdot, cx + rdot, cy + rdot), fill=self.theme.accent)

        # Aircraft drawing with label overlap avoidance
        placed_boxes: list[tuple[int, int, int, int]] = []
        for d, brg, hdg, label in points:
            r_px = self._radar_px_radius(d, dspan, radius)
            a = math.radians(brg)
            px = cx + r_px * math.sin(a)
            py = cy - r_px * math.cos(a)

            # Icon: arrow if heading present, else dot
            if hdg is not None:
                self._draw_heading_arrow(draw, px, py, float(hdg), size=6, color=self.theme.accent_2)
            else:
                draw.ellipse((px - 2, py - 2, px + 2, py + 2), fill=self.theme.secondary)

            # Label (centre-top anchored under icon)
            if label:
                label_off = 8
                tx, ty = px, py + label_off
                # initial bbox at anchor "mt" (middle top)
                bbox_l, bbox_t, bbox_r, bbox_b = draw.textbbox((tx, ty), label, font=self.small_font, anchor="mt")

                # Clamp into content rect by shifting anchor point
                min_x, min_y = x + 2, y + 2
                max_x, max_y = x + width - 2, y + height - 2
                dx = 0
                dy = 0
                if bbox_l < min_x: dx += (min_x - bbox_l)
                if bbox_r > max_x: dx -= (bbox_r - max_x)
                if bbox_t < min_y: dy += (min_y - bbox_t)
                if bbox_b > max_y: dy -= (bbox_b - max_y)
                if dx or dy:
                    tx += dx
                    ty += dy
                    bbox_l, bbox_t, bbox_r, bbox_b = draw.textbbox((tx, ty), label, font=self.small_font, anchor="mt")

                # Overlap check
                overlaps = any(not (bbox_r < b_l or bbox_l > b_r or bbox_b < b_t or bbox_t > b_b)
                               for b_l, b_t, b_r, b_b in placed_boxes)
                if not overlaps:
                    placed_boxes.append((bbox_l, bbox_t, bbox_r, bbox_b))
                    draw.text((tx, ty), label, font=self.small_font, fill=self.theme.fg, anchor="mt")

    def _scroll_aircraft(self, direction: int) -> None:
        """Scroll aircraft list by a page minus one row in the given direction."""
        max_lines = max(1, self._last_aircraft_max_lines or 0)
        total = max(0, self._last_aircraft_total or 0)
        if total <= max_lines:
            # Nothing to scroll
            return
        step = max(1, max_lines - 1)
        new_off = self.aircraft_scroll_offset + (step if direction > 0 else -step)
        max_offset = max(0, total - max_lines)
        self.aircraft_scroll_offset = max(0, min(max_offset, new_off))

    def _render_receiver_page(self, draw: ImageDraw.ImageDraw, stats: dict[str, Any],
                              x: int, y: int, width: int, height: int) -> None:
        """Render the receiver statistics page.

        Args:
            draw: PIL ImageDraw object
            stats: Statistics dictionary
            x, y: Content area position
            width, height: Content area dimensions
        """
        stats_data = stats.get("stats", {})
        line_height = 20

        try:
            # Get last minute stats
            last1min = stats_data.get("last1min", {})
            local_stats = last1min.get("local", {})

            # Extract values
            signal = local_stats.get("signal", 0.0)
            noise = local_stats.get("noise", 0.0)
            samples = local_stats.get("samples_processed", 0)
            accepted = local_stats.get("accepted", [0])[0]

            # Draw aligned labels/values like system page
            rows = (
                ("Signal:", f"{signal:.1f} dBFS"),
                ("Noise:", f"{noise:.1f} dBFS"),
                ("Samples:", f"{samples}"),
                ("Msgs/Min:", f"{accepted}"),
            )
            for i, (label, value) in enumerate(rows):
                cy = y + i * line_height
                draw.text((x, cy), label, font=self.font, fill=self.theme.fg)
                draw.text((x + 80, cy), value, font=self.font, fill=self.theme.secondary)

        except (KeyError, IndexError, TypeError) as e:
            draw.text((x, y), "No receiver data",
                      font=self.font, fill=self.theme.error)
            logger.exception(f"Receiver stats render error: {e}")

    def _render_system_page(self, draw: ImageDraw.ImageDraw, stats: dict[str, Any],
                            x: int, y: int, width: int, height: int) -> None:
        """Render the system information page.

        Args:
            draw: PIL ImageDraw object
            stats: Statistics dictionary
            x, y: Content area position
            width, height: Content area dimensions
        """
        line_height = 20
        system_data = stats.get("system", {})

        cpu_vals = system_data.get("cpu", [])
        mem_vals = system_data.get("mem", [])
        temp_vals = system_data.get("temp", [])
        ip = system_data.get("ip", "N/A")

        # Current values
        data = (
            ("CPU:", f"{cpu_vals[-1] or 0:.0f}%"),
            ("MEM:", f"{mem_vals[-1] or 0:.0f}%"),
            ("TEMP:", f"{temp_vals[-1] or 0:.1f}°C"),
            ("NET:", ip),
        )
        for i, (key, value) in enumerate(data):
            cur_y = y + line_height * i
            draw.text((x, cur_y), key, font=self.font, fill=self.theme.fg)
            draw.text((x + 50, cur_y), value, font=self.font, fill=self.theme.secondary)
        
        # Mini graphs
        if width > 150:  # Only draw graphs if we have space
            graph_x = x + 120
            graph_width = width - 130
            graph_height = 15

            if cpu_vals and len(cpu_vals) > 1:
                self._draw_mini_graph(draw, graph_x, y, graph_width, graph_height,
                                      cpu_vals, self.theme.accent, self.theme.neutral, 0, 100)
            if mem_vals and len(mem_vals) > 1:
                self._draw_mini_graph(draw, graph_x, y + 20, graph_width, graph_height,
                                      mem_vals, self.theme.accent, self.theme.neutral, 0, 100)
            if temp_vals and len(temp_vals) > 1:
                self._draw_mini_graph(draw, graph_x, y + 40, graph_width, graph_height,
                                      temp_vals, self.theme.accent, self.theme.neutral, 20, 80)

    def _draw_mini_graph(self, draw: ImageDraw.ImageDraw, x: int, y: int,
                         width: int, height: int, values: list[float],
                         color: Color, outline: Color,
                         min_val: float | None = None, max_val: float | None = None) -> None:
        """Draw a mini graph of values.

        Args:
            draw: PIL ImageDraw object
            x, y: Top-left corner of graph
            width, height: Graph dimensions
            values: List of values to plot
            color: Line color
        """
        if not values or len(values) < 2:
            return

        if min_val is None:
            min_val = min(values)
        if max_val is None:
            max_val = max(values)
        val_range = max_val - min_val if max_val != min_val else 1

        points = [
            (x + (i * width // (len(values) - 1)),
             y + height - int(((val - min_val) / val_range) * height))
            for i, val in enumerate(values)
        ]

        # Draw the graph line
        draw.line(points, fill=color, width=1)

        # Draw border
        draw.rectangle([x, y, x + width, y + height], outline=outline, width=1)

    def _render_settings_page(self, draw: ImageDraw.ImageDraw, stats: dict[str, Any],
                              x: int, y: int, width: int, height: int) -> None:
        """Render the Settings page with selection/edit flow."""
        line_h = 20
        val_x = x + 90
        for i, item in enumerate(self.settings_items):
            cy = y + i * line_h
            label = item["label"].upper() + ":"
            idx = item["pending"] if (self.settings_mode == "edit" and i == self.settings_index and item["pending"] is not None) else item["index"]
            value = item["values"][idx]

            label_color = self.theme.fg
            value_color = self.theme.secondary
            if self.settings_mode == "select" and i == self.settings_index:
                label_color = self.tabs[self.active_page]["accent"]
            if self.settings_mode == "edit" and i == self.settings_index:
                value_color = self.tabs[self.active_page]["accent"]

            draw.text((x, cy), label, font=self.font, fill=label_color)
            draw.text((val_x, cy), value, font=self.font, fill=value_color)

        hint = "OK: Select/Edit/Confirm  Back: Exit"
        draw.text((x, y + height - 2), hint, font=self.small_font, fill=self.theme.neutral, anchor="lb")

    def _apply_setting(self, item: dict) -> None:
        if item.get("key") == "theme":
            name = item["values"][item["index"]]
            self._apply_theme_by_name(name)

    def _apply_theme_by_name(self, name: str) -> None:
        theme = THEMES.get(name)
        if not theme:
            return
        self.theme = theme
        self.theme_name = name
        self._update_tab_accents()
        try:
            self._layer_cache.clear()
        except Exception:
            pass

    def _update_tab_accents(self) -> None:
        accents = [
            self.theme.flight_tab,
            self.theme.radar_tab,
            self.theme.receiver_tab,
            self.theme.system_tab,
            self.theme.settings_tab,
        ]
        for i, tab in enumerate(self.tabs):
            if i < len(accents):
                tab["accent"] = accents[i]

    def _settings_tab_idx(self) -> int:
        for i, tab in enumerate(self.tabs):
            if tab.get("name") == "Settings":
                return i
        return len(self.tabs) - 1


class App:
    """Main application class that coordinates all components."""

    def __init__(self):
        """Initialize the application."""
        self.ui = UI(Config.width, Config.height, VaporwaveTheme)
        self.collector = DataCollector()
        self.display = Display(Config.fb_path, Config.active_tty)
        self.keyboard = KeyboardInput()
        self.running = True

        # Connect keyboard callbacks
        self.keyboard.set_callback(evdev.ecodes.KEY_UP, self.ui.on_prev)
        self.keyboard.set_callback(evdev.ecodes.KEY_DOWN, self.ui.on_next)
        self.keyboard.set_callback(evdev.ecodes.KEY_ENTER, self.ui.on_ok)
        self.keyboard.set_callback(evdev.ecodes.KEY_BACKSPACE, self.ui.on_cancel)

    def run(self) -> None:
        """Run the main application loop."""
        logger.info("Starting application")

        if os.geteuid() != 0:
            logger.error("You need to run this program as root")
            sys.exit(1)

        self.display.start()
        self.collector.start()
        self.keyboard.start()

        self.display.switch_to_target()

        try:
            while self.running:
                if self.display.is_active():
                    stats = self.collector.snapshot()
                    img = self.ui.render(stats)
                    self.display.show(img)

                time.sleep(Config.display_interval)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.exception(f"Application error: {e}")
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """Clean up resources before exit."""
        logger.info("Cleaning up")
        self.running = False
        self.display.switch_to_prev()
        self.keyboard.stop(join_timeout=1.0)
        self.collector.stop(join_timeout=1.0)
        self.display.stop(join_timeout=1.0)


if __name__ == "__main__":
    try:
        app = App()
        app.run()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
