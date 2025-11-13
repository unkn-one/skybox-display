import logging
import math

from smbus2 import SMBus

LOGGER = logging.getLogger(__name__)


class IMUBase:
    def __init__(self, bus: int):
        self._busno = bus
        self._bus = SMBus(bus)

    def read_heading(self) -> float | None:
        return None

    def close(self) -> None:
        try:
            self._bus.close()
        except Exception as e:
            LOGGER.exception(f"Unable to close I2C bus: {e}")

    def tilt_compass_heading(
        self,
        mx: float,
        my: float,
        mz: float,
        ax: float,
        ay: float,
        az: float,
        declination_deg: float = 0.0,
        offset_deg: float = 0.0,
    ) -> float | None:
        """Compute tilt-compensated compass heading from mag + accel.

        Bearing convention: 0 degrees points to North (up), 90 to East (right).

        Args:
            mx, my, mz: Magnetometer axes (arbitrary units)
            ax, ay, az: Accelerometer axes (arbitrary units)
            declination_deg: Magnetic declination correction (deg)
            offset_deg: Additional manual heading trim (deg)

        Returns:
            Heading in degrees [0..360) or None if unavailable.
        """
        anorm = (ax * ax + ay * ay + az * az) ** 0.5 or 1.0
        axn, ayn, azn = ax / anorm, ay / anorm, az / anorm

        # Roll and pitch from accelerometer
        roll = math.atan2(ayn, azn)
        pitch = math.atan2(-axn, (ayn * ayn + azn * azn) ** 0.5)

        # Tilt-compensate magnetometer
        Xh = mx * math.cos(pitch) + mz * math.sin(pitch)
        Yh = mx * math.sin(roll) * math.sin(pitch) + my * math.cos(roll) - mz * math.sin(roll) * math.cos(pitch)

        if Xh == 0 and Yh == 0:
            return None
        heading = math.degrees(math.atan2(Yh, Xh))
        if heading < 0:
            heading += 360.0
        heading = (heading + declination_deg + offset_deg) % 360.0
        return heading


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

    def __init__(self, bus: int, mag_addr: int, ag_addr: int,
                 declination_deg: float = 0.0, heading_offset_deg: float = 0.0):
        super().__init__(bus)
        self._mag_addr = mag_addr
        self._ag_addr = ag_addr
        self._decl = declination_deg
        self._off = heading_offset_deg
        self._init_mag()
        self._init_ag()

    def _write_mag(self, reg: int, val: int) -> None:
        self._bus.write_byte_data(self._mag_addr, reg, val & 0xFF)

    def _read_mag_block(self, reg: int, length: int) -> bytes:
        # Auto-increment on multi-byte reads by setting MSB of subaddress
        return self._bus.read_i2c_block_data(self._mag_addr, reg | 0x80, length)

    def _write_ag(self, reg: int, val: int) -> None:
        self._bus.write_byte_data(self._ag_addr, reg, val & 0xFF)

    def _read_ag_block(self, reg: int, length: int) -> bytes:
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
        except Exception:
            # If init fails, we'll still try to read; device may already be configured.
            pass

    def _init_ag(self) -> None:
        # Accelerometer: +/- 2g, ODR ~ 10Hz (sufficient for heading smoothing)
        try:
            # CTRL_REG6_XL: ODR_XL = 0101 (~ 10 Hz), FS = 00 (+/-2g), BW = 00
            self._write_ag(self.CTRL_REG6_XL, 0x50)
        except Exception:
            pass

    @staticmethod
    def _twos_compl(val_l: int, val_h: int) -> int:
        v = (val_h << 8) | val_l
        if v & 0x8000:
            v -= 0x10000
        return v

    def read_heading(self) -> float | None:
        """Tilt-compensated compass heading in degrees [0..360)."""
        try:
            # Read raw magnetometer
            m = self._read_mag_block(self.OUT_X_L_M, 6)
            mx = self._twos_compl(m[0], m[1])
            my = self._twos_compl(m[2], m[3])
            mz = self._twos_compl(m[4], m[5])

            # Read raw accelerometer
            a = self._read_ag_block(self.OUT_X_L_XL, 6)
            ax = self._twos_compl(a[0], a[1])
            ay = self._twos_compl(a[2], a[3])
            az = self._twos_compl(a[4], a[5])

            return self.tilt_compass_heading(mx, my, mz, ax, ay, az, self._decl, self._off)
        except Exception:
            return None


class DummyIMU(IMUBase):
    def __init__(self):
        pass

    def close(self) -> None:
        pass


def load(config: dict) -> IMUBase:
    model = config.get("imu_model")
    LOGGER.info(f"Initializing IMU: {model}")
    if model == "LSM9DS1":
        try:
            return LSM9DS1(
                bus=int(config.get("imu_bus", 1)),
                mag_addr=int(config.get("imu_mag_addr", 0x1E)),
                ag_addr=int(config.get("imu_ag_addr", 0x6B)),
                declination_deg=float(config.get("imu_declination_deg", 0.0)),
                heading_offset_deg=float(config.get("imu_heading_offset", 0.0)),
            )
        except Exception as e:
            LOGGER.exception(f"Unable to initialize IMU({model}): {e}")
    return DummyIMU()
