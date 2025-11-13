import logging
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Any, Callable, Generic, TypeVar

import psutil
import requests

from skybox_display import USER_AGENT, concurrency, math_utils, imu

LOGGER = logging.getLogger(__name__)

TaskResult = TypeVar('TaskResult')
TaskFn = Callable[[], TaskResult]


class TaskStatus(StrEnum):
    ok = auto()
    error = auto()


@dataclass(slots=True)
class Task(Generic[TaskResult]):
    name: str
    fn: TaskFn[TaskResult]
    interval: float | None
    due: float = time.monotonic()
    result: TaskResult | None = None
    status: TaskStatus = TaskStatus.ok
    last_update: float = float("-inf")


class DataCollector(concurrency.Threaded):
    """Collects data from various sources in a separate thread."""

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self._config = config
        self._lock = threading.Lock()
        self._system: dict[str, Any] = {
            "cpu": deque(maxlen=self._config["system_samples"]),
            "mem": deque(maxlen=self._config["system_samples"]),
            "temp": deque(maxlen=self._config["system_samples"]),
            "ip": "",
        }
        self._imu_dev = imu.load(self._config)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        # Task scheduler: name, function, interval, next due time, and optional error target for status marking
        now = time.monotonic()
        self._tasks: dict[str, Task] = {
            "aircraft": Task[list](
                name="aircraft",
                fn=self.update_aircraft,
                interval=self._config["aircraft_poll_interval"],
                due=now,
            ),
            "stats": Task[dict[str, Any]](
                name="stats",
                fn=self.update_stats,
                interval=self._config["status_poll_interval"],
                due=now,
            ),
            "receiver": Task[None](
                name="receiver",
                fn=self.update_receiver,
                interval=None,
                due=now,
            ),
            "system": Task[dict[str, Any]](
                name="system",
                fn=self.update_system,
                interval=self._config["system_poll_interval"],
                due=now,
            ),
            "imu": Task[dict[str, Any]](
                name="imu",
                fn=self.update_imu,
                interval=self._config["imu_poll_interval"],
                due=now,
            ),
        }

    def get_data(self, task_name) -> Any:
        with self._lock:
            return self._tasks[task_name].result

    def _clean(self):
        """Clean up resources."""
        try:
            self._session.close()
            self._imu_dev.close()
        except Exception as e:
            LOGGER.exception(e)

    def _execute(self) -> None:
        """Scheduler loop: run each task at its configured interval."""
        now = time.monotonic()
        next_due = float("inf")

        for t in self._tasks.values():
            if now >= t.due:
                self._run_task(t)
                if t.interval is None:
                    # One-time task: disable further runs
                    t.due = float("inf")
                else:
                    # Advance due by whole intervals to avoid drift/catch-up storms
                    intervals = max(1, int((now - t.due) // t.interval) + 1)
                    t.due = t.due + intervals * t.interval
            next_due = min(next_due, t.due)

        # Sleep until the earliest next due, bounded for responsiveness
        sleep_for = max(0.01, min(0.25, next_due - time.monotonic()))
        self._stop_ev.wait(sleep_for)

    def _run_task(self, task: Task) -> None:
        """Run a polling task with unified error handling and status marking."""
        try:
            LOGGER.debug(f"Running '{task.name}' task")
            task.result = task.fn()
            task.last_update = time.time()
            task.status = TaskStatus.ok
        except Exception as e:
            LOGGER.error(f"Task '{task.name}' update failed: {e}")
            task.status = TaskStatus.error

    def update_imu(self) -> dict[str, Any]:
        """Update IMU heading if device is available."""
        return {"heading": self._imu_dev.read_heading()}

    def update_receiver(self) -> None:
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
            self._tasks["aircraft"].interval = self._config["aircraft_poll_interval"] = refresh / 1000

    def update_stats(self) -> dict[str, Any]:
        """Update dump1090 statistics."""
        r = self._session.get(self._config["stats_url"], timeout=self._config["timeout"])
        r.raise_for_status()
        return r.json()

    def update_aircraft(self) -> list:
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

        return aircraft_list

    def update_system(self) -> dict[str, Any]:
        """Update system statistics (CPU, memory, temperature)."""
        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory().percent
        temp = self._get_temperature()
        ip = self._get_primary_ip()

        self._system["cpu"].append(cpu)
        self._system["mem"].append(mem)
        self._system["temp"].append(temp)
        self._system["ip"] = ip

        return self._system

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
            return {name: task.result for name, task in self._tasks.items() if task.result is not None}
