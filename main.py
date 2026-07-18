# Small Daikin AC UART helper library.

from enum import Enum

try:
    import machine
except ImportError:
    machine = None

try:
    import time
except ImportError:
    import utime as time


START_BIT = b'\x02'
END_BIT = b'\x03'
ACK = b'\x06'
NAK = b'\x15'


class DaikinQuery(bytes, Enum):
    POWER_MODE_TEMP_FAN = b'F1'
    FEATURES = b'F2'
    SWING_HUMIDITY = b'F5'
    POWERFUL_QUIET_LED = b'F6'
    DEMAND_ECO = b'F7'
    PROTOCOL_VERSION = b'F8'
    TEMPS_ALT = b'F9'
    FEATURE_BITS = b'FK'
    POWER_CONSUMPTION = b'FM'
    MODEL = b'FC'
    ROOM_TEMP = b'RH'
    OUTSIDE_TEMP = b'Ra'
    INLET_TEMP = b'RI'
    FAN_RPM = b'RL'
    COMPRESSOR_RPM = b'Rd'
    HUMIDITY = b'Re'
    LOUVER_ANGLE = b'RN'


class DaikinMode(bytes, Enum):
    AUTO = b'0'
    DRY = b'2'
    COOL = b'3'
    HEAT = b'4'
    FAN = b'6'


class DaikinFanSpeed(bytes, Enum):
    AUTO = b'A'
    QUIET = b'B'
    SPEED_1 = b'3'
    SPEED_2 = b'4'
    SPEED_3 = b'5'
    SPEED_4 = b'6'
    SPEED_5 = b'7'


class DaikinSetter(bytes, Enum):
    POWER_MODE_TEMP_FAN = b'D1'
    SWING_HUMIDITY = b'D5'
    POWERFUL_QUIET_LED = b'D6'
    DEMAND_ECO = b'D7'


class DaikinPower(bytes, Enum):
    ON = b'1'
    OFF = b'0'


def calculate_checksum(data):
    """Return the single-byte checksum for the supplied command/payload bytes."""
    chk_sum_int = sum(data) & 0xFF
    reserved = {START_BIT[0], END_BIT[0], ACK[0], NAK[0]}
    if chk_sum_int in reserved:
        chk_sum_int = (chk_sum_int + 2) & 0xFF
    return bytes([chk_sum_int])


def assemble_packet(command, payload=b""):
    """Assemble a full UART packet for the AC unit."""
    checksum = calculate_checksum(command + payload)
    return START_BIT + command + payload + checksum + END_BIT


def parse_packet(packet):
    """Parse a framed packet and return (command, payload)."""
    if len(packet) < 5:
        raise ValueError("Invalid packet length: {0}".format(len(packet)))
    if not packet.startswith(START_BIT) or not packet.endswith(END_BIT):
        raise ValueError("Invalid packet framing")

    command = packet[1:3]
    payload = packet[3:-2]
    checksum = packet[-2:-1]

    if calculate_checksum(command + payload) != checksum:
        raise ValueError("Checksum mismatch")

    return command, payload


def encode_temp(temp):
    """Convert a Celsius temperature to the encoded byte used by the AC."""
    clamped_temp = max(18, min(temp, 30))
    return bytes([int((clamped_temp - 18.0) * 2 + 64)])


def decode_temp(temp_byte):
    """Convert the AC-encoded temperature byte back to Celsius."""
    if isinstance(temp_byte, bytes):
        temp_byte = temp_byte[0]
    return (temp_byte - 64) / 2 + 18


class DaikinController(object):
    """Small controller around the Daikin UART protocol."""

    def __init__(self, uart_id=1, tx=None, rx=None, baudrate=2400, bits=8, parity=0, stop=2, timeout=1000):
        self.uart_id = uart_id
        self.tx = tx
        self.rx = rx
        self.baudrate = baudrate
        self.bits = bits
        self.parity = parity
        self.stop = stop
        self.timeout = timeout
        self._uart = None

    def init_uart(self, uart_id=None, tx=None, rx=None, baudrate=None, bits=None, parity=None, stop=None, timeout=None):
        """Initialize the UART connection for this controller."""
        if machine is None:
            raise RuntimeError("MicroPython machine module not available")

        if uart_id is not None:
            self.uart_id = uart_id
        if tx is not None:
            self.tx = tx
        if rx is not None:
            self.rx = rx
        if baudrate is not None:
            self.baudrate = baudrate
        if bits is not None:
            self.bits = bits
        if parity is not None:
            self.parity = parity
        if stop is not None:
            self.stop = stop
        if timeout is not None:
            self.timeout = timeout

        self._uart = machine.UART(
            self.uart_id,
            baudrate=self.baudrate,
            bits=self.bits,
            parity=self.parity,
            stop=self.stop,
            tx=self.tx,
            rx=self.rx,
            timeout=self.timeout,
        )
        return self._uart

    def _flush_uart(self):
        if self._uart is None:
            return
        while self._uart.any():
            self._uart.read()

    def _uart_write(self, packet):
        if self._uart is None:
            raise RuntimeError("UART not initialized. Call init_uart() first.")
        self._uart.write(packet)

    def _uart_read_response(self, timeout=1000):
        if self._uart is None:
            raise RuntimeError("UART not initialized. Call init_uart() first.")

        deadline = time.ticks_add(time.ticks_ms(), timeout)
        response = b""
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if self._uart.any():
                chunk = self._uart.read()
                if chunk:
                    response += chunk
                    if response.endswith(END_BIT):
                        return response
        raise TimeoutError("UART response timed out")

    def send_packet(self, packet, read_response=False, timeout=1000):
        """Write a packet and optionally read back the response."""
        self._flush_uart()
        self._uart_write(packet)
        if read_response:
            return self._uart_read_response(timeout)
        return packet

    def turn_on(self, temp, fan=None, mode=None, read_response=False, timeout=1000):
        """Send power-on command for the supplied temperature and fan/mode settings."""
        if fan is None:
            fan = DaikinFanSpeed.AUTO
        if mode is None:
            mode = DaikinMode.COOL

        payload = DaikinPower.ON.value
        payload += mode.value
        payload += encode_temp(temp)
        payload += fan.value
        packet = assemble_packet(DaikinSetter.POWER_MODE_TEMP_FAN.value, payload)
        return self.send_packet(packet, read_response=read_response, timeout=timeout)

    def turn_off(self, read_response=False, timeout=1000):
        """Send power-off command."""
        payload = DaikinPower.OFF.value
        payload += DaikinMode.AUTO.value
        payload += encode_temp(18)
        payload += DaikinFanSpeed.AUTO.value
        packet = assemble_packet(DaikinSetter.POWER_MODE_TEMP_FAN.value, payload)
        return self.send_packet(packet, read_response=read_response, timeout=timeout)

    def get_temp(self, timeout=1000):
        """Query the AC unit for the current target set-point temperature."""
        packet = assemble_packet(DaikinQuery.POWER_MODE_TEMP_FAN.value)
        response = self.send_packet(packet, read_response=True, timeout=timeout)
        command, payload = parse_packet(response)
        if command != b'G1':
            raise ValueError("Unexpected response command: {0}".format(command))
        return decode_f1_response(payload)['target_temp']

    def get_status(self, timeout=1000):
        """Return the decoded F1 response payload as a dictionary."""
        packet = assemble_packet(DaikinQuery.POWER_MODE_TEMP_FAN.value)
        response = self.send_packet(packet, read_response=True, timeout=timeout)
        command, payload = parse_packet(response)
        if command != b'G1':
            raise ValueError("Unexpected response command: {0}".format(command))
        return decode_f1_response(payload)

    def get_target_temp(self, timeout=1000):
        return self.get_temp(timeout=timeout)


_DEFAULT_CONTROLLER = None


def _get_default_controller():
    global _DEFAULT_CONTROLLER
    if _DEFAULT_CONTROLLER is None:
        _DEFAULT_CONTROLLER = DaikinController()
    return _DEFAULT_CONTROLLER


def init_uart(uart_id=1, tx=None, rx=None, baudrate=2400, bits=8, parity=0, stop=2, timeout=1000):
    """Initialize the default controller UART."""
    return _get_default_controller().init_uart(uart_id=uart_id, tx=tx, rx=rx, baudrate=baudrate, bits=bits, parity=parity, stop=stop, timeout=timeout)


def turn_on(temp, fan=None, mode=None, read_response=False, timeout=1000):
    """Simple module-level wrapper for turning the AC on."""
    return _get_default_controller().turn_on(temp=temp, fan=fan, mode=mode, read_response=read_response, timeout=timeout)


def turn_off(read_response=False, timeout=1000):
    """Simple module-level wrapper for turning the AC off."""
    return _get_default_controller().turn_off(read_response=read_response, timeout=timeout)


def get_temp(timeout=1000):
    """Simple module-level wrapper for reading the target temperature."""
    return _get_default_controller().get_temp(timeout=timeout)


def get_status(timeout=1000):
    """Simple module-level wrapper for reading the decoded AC status."""
    return _get_default_controller().get_status(timeout=timeout)


def turn_ac_on(mode, temp, fan, read_response=False, timeout=1000):
    """Backward-compatible wrapper for the older API style."""
    return turn_on(temp=temp, fan=fan, mode=mode, read_response=read_response, timeout=timeout)


def turn_ac_off(read_response=False, timeout=1000):
    """Backward-compatible wrapper for the older API style."""
    return turn_off(read_response=read_response, timeout=timeout)


def get_target_temp(timeout=1000):
    """Backward-compatible wrapper for the old temperature query function."""
    return get_temp(timeout=timeout)


def decode_f1_response(payload):
    """Decode an F1 response payload from the AC unit."""
    if len(payload) < 4:
        raise ValueError("Invalid F1 response: expected 4 bytes, got {0}".format(len(payload)))

    power = payload[0:1] == b'1'
    mode = payload[1:2]
    target_temp = decode_temp(payload[2])
    fan = payload[3:4]

    return {
        'power': power,
        'mode': mode,
        'target_temp': target_temp,
        'fan': fan,
    }
