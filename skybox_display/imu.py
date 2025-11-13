import logging
import math
import struct
import threading
import time
from typing import Any, Sequence

import numpy as np
from smbus2 import SMBus

from skybox_display import config as config_mod

LOGGER = logging.getLogger(__name__)


def _normalize_matrix(matrix: Sequence[Sequence[float]] | np.ndarray | None) -> np.ndarray:
    """Return a valid 3x3 rotation matrix, falling back to identity."""
    if matrix is None:
        return np.identity(3, dtype=float)
    try:
        arr = np.array(matrix, dtype=float)
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.warning("Invalid IMU rotation matrix (%s). Using identity", exc)
        return np.identity(3, dtype=float)
    if arr.shape != (3, 3):
        LOGGER.warning("IMU rotation matrix must be 3x3; got %s. Using identity", arr.shape)
        return np.identity(3, dtype=float)
    return arr


def _matrix_from_vectors(mag: np.ndarray, acc: np.ndarray) -> np.ndarray | None:
    """Compute a rotation matrix that maps sensor vectors to the device frame."""
    acc_norm = np.linalg.norm(acc)
    if acc_norm == 0:
        return None
    z_axis = -acc / acc_norm  # Device +Z points away from gravity

    mag_horizontal = mag - np.dot(mag, z_axis) * z_axis
    mag_norm = np.linalg.norm(mag_horizontal)
    if mag_norm == 0:
        return None
    y_axis = mag_horizontal / mag_norm  # Device +Y points toward magnetic north

    x_axis = np.cross(y_axis, z_axis)
    x_norm = np.linalg.norm(x_axis)
    if x_norm == 0:
        return None
    x_axis /= x_norm

    y_axis = np.cross(z_axis, x_axis)
    y_norm = np.linalg.norm(y_axis)
    if y_norm == 0:
        return None
    y_axis /= y_norm

    # Stack rows so outputs correspond to (forward/north, right/east, up)
    return np.vstack([y_axis, x_axis, z_axis])


class IMUBase:
    """Common functionality for IMU devices, including calibration orchestration."""
    SUPPORTS_CALIBRATION = False

    def __init__(self, cfg: dict[str, Any]):
        self._config = cfg
        self._rotation = _normalize_matrix(cfg.get("imu_rotation"))
        self._decl = float(cfg.get("imu_declination_deg", 0.0))
        self._offset = float(cfg.get("imu_heading_offset", 0.0))
        self._cal_thread: threading.Thread | None = None
        self._cal_lock = threading.Lock()

    def read_heading(self) -> float | None:
        pass

    def close(self) -> None:
        pass

    def start_calibration(self, duration: float = 3.0, sample_delay: float = 0.05) -> bool:
        """Kick off orientation calibration in a background thread."""
        if not self.SUPPORTS_CALIBRATION:
            LOGGER.warning("IMU calibration not supported for %s", self.__class__.__name__)
            return False
        with self._cal_lock:
            if self._cal_thread and self._cal_thread.is_alive():
                LOGGER.info("IMU calibration already running")
                return False
            self._cal_thread = threading.Thread(
                target=self._calibration_worker,
                args=(duration, sample_delay),
                name=f"{self.__class__.__name__}Cal",
                daemon=True,
            )
            self._cal_thread.start()
        LOGGER.info("IMU calibration started")
        return True

    def _collect_calibration_matrix(self, duration: float, sample_delay: float) -> np.ndarray | None:
        return None

    def _calibration_worker(self, duration: float, sample_delay: float) -> None:
        try:
            matrix = self._collect_calibration_matrix(duration, sample_delay)
            if matrix is None:
                LOGGER.warning("IMU calibration failed: no data captured")
                return
            self._rotation = matrix
            as_list = matrix.tolist()
            self._config["imu_rotation"] = as_list
            config_mod.save_config(self._config)
            LOGGER.info("IMU calibration complete")
        except Exception as exc:
            LOGGER.exception("IMU calibration error: %s", exc)
        finally:
            with self._cal_lock:
                self._cal_thread = None

    def _apply_rotation(self, vec: np.ndarray) -> np.ndarray:
        return self._rotation @ vec

    def _tilt_compass_heading(
        self,
        mag_vec: Sequence[float] | np.ndarray,
        acc_vec: Sequence[float] | np.ndarray,
        declination_deg: float = 0.0,
        offset_deg: float = 0.0,
    ) -> float | None:
        """Compute tilt-compensated heading using device-frame projections."""
        mag = np.asarray(mag_vec, dtype=float).reshape(3)
        acc = np.asarray(acc_vec, dtype=float).reshape(3)

        acc_norm = np.linalg.norm(acc)
        if acc_norm == 0:
            return None
        up = -acc / acc_norm  # device +Z points away from gravity

        # Remove vertical component from magnetometer
        mag_horizontal = mag - np.dot(mag, up) * up
        mag_norm = np.linalg.norm(mag_horizontal)
        if mag_norm == 0:
            return None
        mag_horizontal /= mag_norm

        forward_axis = np.array([1.0, 0.0, 0.0])
        right_axis = np.array([0.0, 1.0, 0.0])

        heading = math.degrees(
            math.atan2(np.dot(mag_horizontal, right_axis), np.dot(mag_horizontal, forward_axis))
        )
        return (heading + declination_deg + offset_deg) % 360.0


class LSM9DS1(IMUBase):
    # Magnetometer register addresses (mag device)
    WHO_AM_I_M = 0x0F
    CTRL_REG1_M = 0x20
    CTRL_REG2_M = 0x21
    CTRL_REG3_M = 0x22
    CTRL_REG4_M = 0x23
    OUT_X_L_M = 0x28

    # Accelerometer/Gyro register addresses (AG device)
    CTRL_REG6_XL = 0x20  # Accel ODR and scale
    OUT_X_L_XL = 0x28

    SUPPORTS_CALIBRATION = True

    def __init__(self, cfg: dict[str, Any]):
        super().__init__(cfg)
        bus = cfg.get("imu_bus")
        self._bus = SMBus(bus) if bus is not None else None
        self._mag_addr = int(cfg.get("imu_mag_addr", 0x1E))
        self._ag_addr = int(cfg.get("imu_ag_addr", 0x6B))
        self._init_mag()
        self._init_ag()

    def close(self) -> None:
        if self._bus is None:
            return
        try:
            self._bus.close()
        except Exception as exc:
            LOGGER.exception("Unable to close I2C bus: %s", exc)

    def _write_mag(self, reg: int, val: int) -> None:
        self._bus.write_byte_data(self._mag_addr, reg, val & 0xFF)

    def _read_mag_block(self, reg: int, length: int) -> list[int]:
        return self._bus.read_i2c_block_data(self._mag_addr, reg | 0x80, length)

    def _write_ag(self, reg: int, val: int) -> None:
        self._bus.write_byte_data(self._ag_addr, reg, val & 0xFF)

    def _read_ag_block(self, reg: int, length: int) -> list[int]:
        return self._bus.read_i2c_block_data(self._ag_addr, reg | 0x80, length)

    def _init_mag(self) -> None:
        # Continuous conversion mode, high-performance XY and Z, ~10Hz ODR
        try:
            # CTRL_REG1_M: TempComp=1, OM=11 (UHP), DO=100 (~10Hz)
            self._write_mag(self.CTRL_REG1_M, 0x70)
            # CTRL_REG2_M: FS=00 (+/-4 gauss)
            self._write_mag(self.CTRL_REG2_M, 0x00)
            # CTRL_REG3_M: MD=00 (continuous-conversion)
            self._write_mag(self.CTRL_REG3_M, 0x00)
            # CTRL_REG4_M: OMZ=11 (UHP)
            self._write_mag(self.CTRL_REG4_M, 0x0C)
        except Exception as exc:
            LOGGER.exception("Error while initializing magnetometer: %s", exc)

    def _init_ag(self) -> None:
        # Accelerometer: +/- 2g, ODR ~ 10Hz (sufficient for heading smoothing)
        try:
            # CTRL_REG6_XL: ODR_XL = 0101 (~ 10 Hz), FS = 00 (+/-2g), BW = 00
            self._write_ag(self.CTRL_REG6_XL, 0x50)
        except Exception as exc:
            LOGGER.exception("Error while initializing accelerometer: %s", exc)

    def _read_raw_vectors(self) -> tuple[np.ndarray, np.ndarray]:
        m = bytes(self._read_mag_block(self.OUT_X_L_M, 6))
        mag = np.array(struct.unpack("<hhh", m), dtype=float)

        a = bytes(self._read_ag_block(self.OUT_X_L_XL, 6))
        acc = np.array(struct.unpack("<hhh", a), dtype=float)
        return mag, acc

    def read_heading(self) -> float | None:
        try:
            mag_raw, acc_raw = self._read_raw_vectors()
            mag = self._apply_rotation(mag_raw)
            acc = self._apply_rotation(acc_raw)
            return self._tilt_compass_heading(mag, acc, self._decl, self._offset)
        except Exception as exc:
            LOGGER.exception("IMU heading read failed: %s", exc)
            return None

    def _collect_calibration_matrix(self, duration: float, sample_delay: float) -> np.ndarray | None:
        end_time = time.monotonic() + duration
        mag_samples: list[np.ndarray] = []
        acc_samples: list[np.ndarray] = []

        while time.monotonic() < end_time:
            try:
                mag, acc = self._read_raw_vectors()
                mag_samples.append(mag)
                acc_samples.append(acc)
            except Exception as exc:
                LOGGER.debug("IMU sample failed during calibration: %s", exc)
            time.sleep(sample_delay)

        if not mag_samples or not acc_samples:
            return None

        mag_avg = np.mean(mag_samples, axis=0)
        acc_avg = np.mean(acc_samples, axis=0)
        return _matrix_from_vectors(mag_avg, acc_avg)


class DummyIMU(IMUBase):
    pass


def load(cfg: dict[str, Any]) -> IMUBase:
    model = cfg.get("imu_model")
    LOGGER.info("Initializing IMU: %s", model)
    if model == "LSM9DS1":
        try:
            return LSM9DS1(cfg)
        except Exception as exc:
            LOGGER.exception("Unable to initialize IMU(%s): %s", model, exc)
    return DummyIMU(cfg)
