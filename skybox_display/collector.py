import copy
import logging
import socket
import threading
import time
from collections import deque
from typing import Callable, Any

import psutil
import requests

from skybox_display import USER_AGENT, concurrency, math_utils, imu as imu_mod


LOGGER = logging.getLogger(__name__)


class DataCollector(concurrency.Threaded):
    """Collects data from various sources in a separate thread."""

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self._config = config
        self._lock = threading.Lock()
        self._stats: dict[str, Any] = {"status": "unknown", "last_update": 0}
        self._aircraft: dict[str, Any] = {"status": "unknown", "last_update": 0, "aircraft": []}
        self._system: dict[str, Any] = {
            "cpu": deque(maxlen=self._config["system_samples"]),
            "mem": deque(maxlen=self._config["system_samples"]),
            "temp": deque(maxlen=self._config["system_samples"]),
            "ip": "",
        }
        self._imu_state: dict[str, Any] = {"status": "unknown", "last_update": 0, "heading": None}
        self._imu_dev = imu_mod.create(self._config)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        # Task scheduler: name, function, interval, next due time, and optional error target for status marking
        now = time.monotonic()
        self._tasks: list[dict[str, Any]] = [
            {
                "name": "receiver",
                "fn": self.update_receiver,
                "interval": None,
                "due": now,
                "error_target": None,
            },
            {
                "name": "imu",
                "fn": self.update_imu,
                "interval": self._config.get("imu_poll_interval", 0.5) if self._config.get("imu_model") else None,
                "due": now,
                "error_target": "imu",
            },
            {
                "name": "aircraft",
                "fn": self.update_aircraft,
                "interval": self._config["aircraft_poll_interval"],
                "due": now,
                "error_target": "aircraft",
            },
            {
                "name": "stats",
                "fn": self.update_stats,
                "interval": self._config["status_poll_interval"],
                "due": now,
                "error_target": "stats",
            },
            {
                "name": "system",
                "fn": self.update_system,
                "interval": self._config["system_poll_interval"],
                "due": now,
                "error_target": None,
            },
        ]

    def _clean(self):
        """Close shared HTTP resources."""
        try:
            self._session.close()
        except Exception as e:
            LOGGER.exception(e)

    def _execute(self) -> None:
        """Scheduler loop: run each task at its configured interval."""
        now = time.monotonic()
        next_due = float("inf")

        for t in self._tasks:
            due = t["due"]
            interval = t.get("interval")
            if now >= due:
                self._run_task(t["name"], t["fn"], t.get("error_target"))
                if interval is None:
                    # One-time task: disable further runs
                    t["due"] = float("inf")
                else:
                    # Advance due by whole intervals to avoid drift/catch-up storms
                    interval_f = float(interval)
                    intervals = max(1, int((now - due) // interval_f) + 1)
                    t["due"] = due + intervals * interval_f
            next_due = min(next_due, t["due"])

        # Sleep until the earliest next due, bounded for responsiveness
        sleep_for = max(0.01, min(0.25, next_due - time.monotonic()))
        self._stop.wait(sleep_for)

    def _run_task(self, name: str, fn: Callable[[], None], error_target: str | None) -> None:
        """Run a polling task with unified error handling and status marking."""
        try:
            fn()
        except requests.RequestException as e:
            LOGGER.error(f"{name.capitalize()} update failed: {e}")
            if error_target:
                with self._lock:
                    if error_target == "aircraft":
                        self._aircraft["status"] = "error"
                    elif error_target == "stats":
                        self._stats["status"] = "error"
                    elif error_target == "imu":
                        self._imu_state["status"] = "error"
                        self._imu_state["last_update"] = time.time()

    def update_imu(self) -> None:
        """Update IMU heading if device is available."""
        if not self._config.get("imu_enabled"):
            return
        try:
            heading = self._imu_dev.read_heading() if self._imu_dev else None
        except Exception:
            heading = None
        with self._lock:
            self._imu_state["heading"] = heading
            self._imu_state["status"] = "ok" if heading is not None else "unknown"
            self._imu_state["last_update"] = time.time()

    def update_receiver(self):
        """Update dump1090 receiver info."""
        r = self._session.get(self._config["receiver_url"], timeout=self._config["timeout"])
        r.raise_for_status()
        data = r.json()
        lat = data.get("lat")
        lon = data.get("lon")
        refresh = data.get("refresh")
        if not self._config["radio_lat"] and lat is not None:
            self._config["radio_lat"] = lat
        if not self._config["radio_lon"] and lon is not None:
            self._config["radio_lon"] = lon
        if refresh is not None:
            self._config["aircraft_poll_interval"] = refresh / 1000

    def update_stats(self) -> None:
        """Update dump1090 statistics."""
        r = self._session.get(self._config["stats_url"], timeout=self._config["timeout"])
        r.raise_for_status()
        data = r.json()
        with self._lock:
            self._stats = data
            self._stats["status"] = "ok"
            self._stats["last_update"] = time.time()

    def update_aircraft(self) -> None:
        """Update dump1090 aircraft data."""
        r = self._session.get(self._config["aircraft_url"], timeout=self._config["timeout"])
        r.raise_for_status()
        data = r.json()

        # Calculate distances for aircraft with position data
        aircraft_list = data.get("aircraft", [])
        for aircraft in aircraft_list:
            lat = aircraft.get("lat")
            lon = aircraft.get("lon")
            if lat is not None and lon is not None:
                distance = math_utils.haversine_distance(
                    self._config["radio_lat"], self._config["radio_lon"], lat, lon
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
            LOGGER.warning(f"Unable to get temperature: {e}")
            return 0

    def _get_primary_ip(self) -> str:
        """Return the first IPv4 from preferred interfaces."""
        preferred = ("eth0", "wlan0", "en0")
        addrs = psutil.net_if_addrs()
        for name in preferred:
            for addr in addrs.get(name, []):
                if getattr(addr, "family", None) == socket.AF_INET:
                    ip = getattr(addr, "address", None)
                    if ip:
                        return ip
        return ""

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
                },
                "imu": copy.deepcopy(self._imu_state),
            }
