import logging
import os
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)
DEFAULT_CONFIG: dict[str, Any] = {
    # Display
    "fb_path": "/dev/fb1",  # Path to frame buffer device
    "target_tty": "tty8",  # Display only when specific tty is active
    "width": 320,
    "height": 240,
    "display_interval": 0.2,
    "flipped": True,

    # Data sources setup
    "timeout": 1.0,
    "stats_url": "http://localhost:8080/data/stats.json",
    "aircraft_url": "http://localhost:8080/data/aircraft.json",
    "receiver_url": "http://localhost:8080/data/receiver.json",
    "aircraft_poll_interval": 0.5,
    "status_poll_interval": 1.0,
    "system_poll_interval": 5.0,
    "system_samples": 20,

    # Radio position (configure these for your location)
    "radio_lat": 0,
    "radio_lon": 0,

    # Radar view settings
    "radar_max_range_km": 400,
    "radar_center_dot_size": 3,

    # UI
    "theme": "Vaporwave",
    "units": "metric",      # metric | imperial
    "radar_scale": "log5",  # linear | log5 | log10
    "aircraft_sort": "none",  # none | distance | signal | altitude | speed
    "active_page": 0,

    # IMU (compass)
    "imu_model": "LSM9DS1",
    "imu_bus": 1,
    "imu_mag_addr": 0x1E,
    "imu_ag_addr": 0x6B,
    "imu_declination_deg": 0.0,
    "imu_heading_offset": 0.0,
    "imu_poll_interval": 0.5,
}


def get_config_path(filename: str) -> Path:
    """Return full path to the config file."""
    app_name = __package__ or "skybox_display"
    base = os.environ.get("XDG_CONFIG_HOME") or "/etc"
    conf_dir = Path(base) / app_name
    conf_dir.mkdir(exist_ok=True)
    return conf_dir / filename


def _coerce_value(default: Any, value: str) -> Any:
    """Coerce env string to the type of default where possible."""
    if default is None:
        return value
    t = type(default)
    if t is bool:
        v = value.strip().lower()
        return v in ("1", "true", "yes", "on")
    if t is int:
        try:
            return int(value)
        except ValueError:
            return default
    if t is float:
        try:
            return float(value)
        except ValueError:
            return default
    return value


def _apply_env_overrides(cfg: dict[str, Any], defaults: dict[str, Any], prefix: str = "SD") -> None:
    """Override config dict in-place with env vars based on defaults keys.

    Only keys present in defaults are considered to avoid surprises.
    """
    for key, dval in defaults.items():
        env_key = f"{prefix}_{key}".upper()
        env_val = os.environ.get(env_key)
        if env_val is not None:
            cfg[key] = _coerce_value(dval, env_val)


def save_config(config: dict[str, Any]) -> None:
    """Write config dict to YAML and return path."""
    try:
        conf_path = get_config_path("config.yml")
        with conf_path.open("w") as f:
            yaml.safe_dump(config, f)
        LOGGER.info(f"Saved app config to: {conf_path}")
    except Exception as e:
        LOGGER.error(f"Unable to save app config: {e}")


def load_config(env_prefix: str = "SD") -> dict[str, Any]:
    """Load config: defaults -> file -> env overrides. Returns merged dict."""
    cfg = DEFAULT_CONFIG
    data = {}
    try:
        with get_config_path("config.yml").open() as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        LOGGER.info("App config not found. Regenerating")
        save_config(DEFAULT_CONFIG)
    except Exception as e:
        LOGGER.error(f"Unable to load app config: {e}")
    if isinstance(data, dict):
        cfg.update(data)

    _apply_env_overrides(cfg, DEFAULT_CONFIG, env_prefix)
    return cfg
