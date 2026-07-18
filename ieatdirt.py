# Small Daikin AC UART helper library for S21 Protocol.
# Optimized for MicroPython (ESP32-C3) heap efficiency.

from enum import Enum

try:
    import machine
except ImportError:
    machine = None

try:
    import time
except ImportError:
    import utime as time

START_BIT = b'\x02'  # STX (Start of text)
END_BIT = b'\x03'    # ETX (End of text)
ACK = b'\x06'        # Acknowledged
NAK = b'\x15'        # Not Acknowledged


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


# ---------------------------------------------------------------------------
# Helper enums / bit masks for setter payloads (to avoid magic bytes)
# ---------------------------------------------------------------------------
class SwingBits:
    VERTICAL   = 0x01   # bit 0
    HORIZONTAL = 0x02   # bit 1

def make_swing_payload(vertical=False, horizontal=False):
    """Return a single-byte payload for D5 (swing/humidity)."""
    val = 0
    if vertical:
        val |= SwingBits.VERTICAL
    if horizontal:
        val |= SwingBits.HORIZONTAL
    return bytes([val])

class PowerfulBits:
    POWERFUL = 0x02    # bit 1
    QUIET    = 0x80    # bit 7
    COMFORT  = 0x40    # bit 6
    STREAMER = 0x80    # byte 1, bit 7 (separate byte)
    SENSOR   = 0x08    # bit 3
    LED_MASK = 0x0C    # bits 2+3 (LED: 00=off, 01=dim, 10=bright)

def make_powerful_quiet_led_payload(powerful=False, quiet=False, comfort=False,
                                    streamer=False, sensor=False, led=0):
    """
    Build the 4-byte payload for D6 (powerful/quiet/LED).
    led: 0=off, 1=dim, 2=bright (as per AC manual).
    """
    pkt = bytearray(4)
    # byte 0 – bits: powerful(1), comfort(6), quiet(7)
    if powerful:
        pkt[0] |= PowerfulBits.POWERFUL
    if comfort:
        pkt[0] |= PowerfulBits.COMFORT
    if quiet:
        pkt[0] |= PowerfulBits.QUIET
    # byte 1 – streamer bit 7
    if streamer:
        pkt[1] = 0x80
    # byte 3 – sensor bit 3, LED bits 2+3
    if sensor:
        pkt[3] |= PowerfulBits.SENSOR
    pkt[3] |= (led << 2) & PowerfulBits.LED_MASK
    return bytes(pkt)

class DemandEcoBits:
    DEMAND_BASE = 0x30  # '0' character
    ECO         = 0x02  # bit 1

def make_demand_eco_payload(demand=0, eco=False):
    """
    demand: 0-100 (mapped to character '0' + value)
    eco: True/False
    """
    if not 0 <= demand <= 100:
        raise ValueError("Demand must be 0-100")
    b0 = bytes([DemandEcoBits.DEMAND_BASE + demand])
    b1 = bytes([0x02]) if eco else b'\x00'
    # assume payload: byte0 demand, byte1 eco flag, bytes 2,3 zero
    return b0 + b1 + b'\x00\x00'


# ---------------------------------------------------------------------------
# Decoding helpers
# ---------------------------------------------------------------------------

def decode_temp_numeric(payload):
    """
    Decode a 4-byte reversed numeric temperature (e.g. b'581+' -> 18.5 °C).
    Returns float.
    """
    if len(payload) < 4:
        raise ValueError("Numeric temp payload too short")
    s = payload.decode('ascii')
    # reversed string
    rev = s[::-1]
    # rev is like "+185" or "-050" or "0010"
    try:
        return float(rev) / 10.0
    except ValueError:
        raise ValueError("Invalid numeric temperature format: %s" % s)

def decode_numeric_int(payload):
    """
    Decode a reversed decimal integer payload (e.g. b'0021' -> 1200).
    No sign, just integer. Returns int.
    """
    s = payload.decode('ascii').strip()
    if not s:
        return 0
    rev = s[::-1].lstrip('0') or '0'
    return int(rev)

def decode_hex_reversed(payload):
    """Decode a reversed hex value (e.g. b'25A3' -> 0x3A52 = 14930)."""
    s = payload.decode('ascii')
    return int(s[::-1], 16)

def decode_temp(temp_byte):
    """
    Convert an S21 protocol @-based notation byte back to a Celsius float.
    Returns float.
    """
    if isinstance(temp_byte, bytes):
        temp_byte = temp_byte[0]
    return (temp_byte - 64) / 2 + 18

# ---------------------------------------------------------------------------
# Specific response decoders
# ---------------------------------------------------------------------------

def decode_f1_response(payload):
    """
    Decode an F1/G1 status byte string.
    Returns dict with enums where possible.
    """
    if len(payload) < 4:
        raise ValueError("Invalid F1 payload: expected 4 bytes, got %d" % len(payload))

    power = payload[0:1] == b'1'
    mode_byte = payload[1:2]
    target_temp = decode_temp(payload[2])
    fan_byte = payload[3:4]

    try:
        mode = DaikinMode(mode_byte)
    except ValueError:
        mode = mode_byte  # fallback to raw bytes
    try:
        fan = DaikinFanSpeed(fan_byte)
    except ValueError:
        fan = fan_byte

    return {
        'power': power,
        'mode': mode,
        'target_temp': target_temp,
        'fan': fan,
    }

def decode_swing_humidity(payload):
    """Decode G5 swing/humidity payload."""
    if len(payload) < 1:
        raise ValueError("Payload too short for swing")
    b = payload[0]
    return {
        'vertical_swing': bool(b & SwingBits.VERTICAL),
        'horizontal_swing': bool(b & SwingBits.HORIZONTAL),
    }

def decode_powerful_quiet_led(payload):
    """Decode G6 powerful/quiet/LED payload."""
    if len(payload) < 4:
        raise ValueError("Payload too short for G6")
    byte0 = payload[0]
    byte1 = payload[1]
    byte3 = payload[3]

    led_bits = (byte3 & PowerfulBits.LED_MASK) >> 2
    led_state = {0: 'off', 1: 'dim', 2: 'bright'}.get(led_bits, 'unknown')

    return {
        'powerful': bool(byte0 & PowerfulBits.POWERFUL),
        'quiet': bool(byte0 & PowerfulBits.QUIET),
        'comfort': bool(byte0 & PowerfulBits.COMFORT),
        'streamer': bool(byte1 & PowerfulBits.STREAMER),
        'sensor': bool(byte3 & PowerfulBits.SENSOR),
        'led': led_state,
    }

def decode_demand_eco(payload):
    """Decode G7 demand/eco payload."""
    if len(payload) < 2:
        raise ValueError("Payload too short for G7")
    demand_byte = payload[0] - DemandEcoBits.DEMAND_BASE
    if not 0 <= demand_byte <= 100:
        demand_byte = 0  # fallback
    eco = bool(payload[1] & DemandEcoBits.ECO)
    return {
        'demand': demand_byte,
        'eco': eco,
    }

def decode_temps_alt(payload):
    """Decode G9 alternate temperatures (home & outside @-based)."""
    if len(payload) < 2:
        raise ValueError("Payload too short for G9")
    return {
        'home_temp': decode_temp(payload[0]),
        'outside_temp': decode_temp(payload[1]),
    }

def decode_power_consumption(payload):
    """Decode GM energy consumption (Wh). Returns int."""
    return decode_hex_reversed(payload)

def decode_protocol_version(payload):
    """Return protocol version string."""
    return payload.decode('ascii').strip()

def decode_feature_bits(payload):
    """Return raw feature bits (not yet decoded)."""
    return payload  # placeholder

def decode_model(payload):
    """Return model string."""
    return payload.decode('ascii').strip()

def decode_room_temp(payload):
    """Decode RH room temperature (numeric reversed, °C)."""
    return decode_temp_numeric(payload)

def decode_outside_temp(payload):
    """Decode Ra outside temperature (numeric reversed, °C)."""
    return decode_temp_numeric(payload)

def decode_inlet_temp(payload):
    """Decode RI inlet temperature (numeric reversed, °C)."""
    return decode_temp_numeric(payload)

def decode_fan_rpm(payload):
    """
    Decode RL fan RPM.
    The payload contains RPM/10 as reversed decimal, multiplied by 10 gives RPM.
    """
    raw = decode_numeric_int(payload)
    return raw * 10

def decode_compressor_rpm(payload):
    """Decode Rd compressor RPM (numeric integer)."""
    return decode_numeric_int(payload)

def decode_humidity(payload):
    """Decode Re humidity (assumed integer percentage)."""
    return decode_numeric_int(payload)

def decode_louver_angle(payload):
    """Decode RN louver angle (assumed integer degrees)."""
    return decode_numeric_int(payload)


# ---------------------------------------------------------------------------
# Checksum and packet assembly
# ---------------------------------------------------------------------------

def calculate_checksum(data):
    """
    Return the single-byte checksum for the supplied command/payload bytes.
    Per S21 spec, if the sum is 0x03 (ETX), 0x05 (ENQ) is substituted instead.
    """
    chk_sum_int = sum(data) & 0xFF
    if chk_sum_int == 0x03:
        chk_sum_int = 0x05
    return bytes([chk_sum_int])


def assemble_packet(command, payload=b""):
    """
    Assemble a full S21 UART packet frame.
    """
    checksum = calculate_checksum(command + payload)
    return START_BIT + command + payload + checksum + END_BIT


def parse_packet(packet):
    """
    Parse a framed packet and extract components.
    Returns (command, payload).
    """
    if len(packet) < 5:
        raise ValueError("Invalid packet length: %d" % len(packet))
    if not packet.startswith(START_BIT) or not packet.endswith(END_BIT):
        raise ValueError("Invalid packet framing")

    command = packet[1:3]
    payload = packet[3:-2]
    checksum = packet[-2:-1]

    if calculate_checksum(command + payload) != checksum:
        raise ValueError("Checksum mismatch")

    return command, payload


def encode_temp(temp):
    """
    Convert a Celsius temperature to the S21 protocol @-based notation byte.
    Clamped to 18.0-30.0°C (your AC's safe limits).
    """
    clamped_temp = max(18, min(temp, 30))
    return bytes([int((clamped_temp - 18.0) * 2 + 64)])


# ---------------------------------------------------------------------------
# Controller class
# ---------------------------------------------------------------------------

class DaikinController:
    """Memory-optimized controller for the Daikin S21 serial interface."""

    def __init__(self, uart_id=1, tx=7, rx=6, timeout=1000, baudrate=2400,
                 bits=8, parity=0, stop=2):
        self.uart_id = uart_id
        self.tx = tx
        self.rx = rx
        self.timeout = timeout
        self.baudrate = baudrate
        self.bits = bits
        self.parity = parity
        self.stop = stop
        self._uart = None

    def init_uart(self):
        """Initialize the UART hardware."""
        if machine is None:
            raise RuntimeError("MicroPython machine module not available")
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

    def deinit_uart(self):
        """De-initialize UART, releasing resources."""
        if self._uart is not None:
            try:
                self._uart.deinit()
            except Exception:
                pass
            self._uart = None

    def _flush_uart(self):
        if self._uart is None:
            return
        while self._uart.any():
            self._uart.read()

    def _read_exact(self, n, deadline):
        buf = b""
        if self._uart is None:
            return buf
        while len(buf) < n and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if self._uart.any():
                chunk = self._uart.read(n - len(buf))
                if chunk:
                    buf += chunk
        return buf

    def _transaction(self, packet, expect_reply=False, timeout=1000):
        """
        Executes a deterministic S21 bus lifecycle transaction:
        1. Write command packet.
        2. Wait for immediate ACK/NAK from the AC.
        3. If Query, read full incoming data frame and write ACK back to AC.
        """
        if self._uart is None:
            raise RuntimeError("UART not initialized. Call init_uart() first.")

        self._flush_uart()
        self._uart.write(packet)

        deadline = time.ticks_add(time.ticks_ms(), timeout)

        # Step 1: Read the immediate response token (ACK or NAK)
        status_token = b""
        while not status_token and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if self._uart.any():
                status_token = self._uart.read(1)

        if not status_token:
            raise TimeoutError("Daikin AC connection timed out waiting for initial transaction handshake.")

        if status_token == NAK:
            raise ValueError(
                "Daikin AC returned a NAK (Not Acknowledged)! "
                "This command or query field is unsupported on this AC unit model."
            )

        if status_token != ACK:
            # Serial fallback edgecase: data byte read instead of token frame
            if status_token == START_BIT:
                # AC directly sent a frame skipping explicit ACK token
                frame = status_token
            else:
                raise ValueError("Unexpected byte received from AC line: %s" % status_token)
        else:
            if not expect_reply:
                return b""
            # Step 2: Find START_BIT of the subsequent data frame
            frame = b""
            while not frame and time.ticks_diff(deadline, time.ticks_ms()) > 0:
                if self._uart.any():
                    b = self._uart.read(1)
                    if b == START_BIT:
                        frame += b

        if not frame:
            raise TimeoutError("Timed out waiting for the AC data payload frame header.")

        # Step 3: Securely parse packet length without guessing.
        # After STX, we have command (2 bytes), then either:
        #   - checksum + ETX (5-byte frame, no payload)
        #   - payload[0:2] (+ later 2 payload bytes + checksum + ETX) -> 9-byte frame
        frame += self._read_exact(2, deadline)          # command
        frame += self._read_exact(2, deadline)          # possibly checksum+ETX, or payload[0:2]

        # If the 4th byte after STX is ETX, it's a valid 5-byte frame.
        if frame[-1:] == END_BIT:
            candidate = frame
            try:
                parse_packet(candidate)
                # valid 5-byte frame
                self._uart.write(ACK)
                return candidate
            except ValueError:
                # checksum mismatch, do NOT fallback – discard
                raise ValueError("Checksum mismatch in short (5-byte) frame")
        else:
            # It's a 9-byte frame: read remaining 4 bytes
            frame += self._read_exact(4, deadline)
            parse_packet(frame)          # will raise if invalid
            self._uart.write(ACK)
            return frame

    def send_command(self, command, payload=b"", read_response=False, timeout=1000):
        """
        Send a generic command or setter payload frame.
        """
        if isinstance(command, (DaikinQuery, DaikinSetter)):
            command_bytes = command.value
        elif isinstance(command, (bytes, bytearray)):
            command_bytes = bytes(command)
        elif isinstance(command, str):
            command_bytes = command.encode("ascii")
        else:
            raise TypeError("Command must be DaikinQuery, DaikinSetter, bytes, or str")

        packet = assemble_packet(command_bytes, payload)
        return self._transaction(packet, expect_reply=read_response, timeout=timeout)

    def query_payload(self, query_enum, timeout=1000):
        """
        Execute a clean sensor or register parameter pull query execution.
        Returns raw payload bytes.
        """
        response_frame = self.send_command(query_enum, read_response=True, timeout=timeout)
        _, payload = parse_packet(response_frame)
        return payload

    def turn_on(self, temp, fan=DaikinFanSpeed.AUTO, mode=DaikinMode.COOL, timeout=1000):
        payload = DaikinPower.ON.value + mode.value + encode_temp(temp) + fan.value
        return self.send_command(DaikinSetter.POWER_MODE_TEMP_FAN, payload=payload, read_response=False, timeout=timeout)

    def turn_off(self, timeout=1000):
        payload = DaikinPower.OFF.value + DaikinMode.AUTO.value + encode_temp(18) + DaikinFanSpeed.AUTO.value
        return self.send_command(DaikinSetter.POWER_MODE_TEMP_FAN, payload=payload, read_response=False, timeout=timeout)

    def get_status(self, timeout=1000):
        payload = self.query_payload(DaikinQuery.POWER_MODE_TEMP_FAN, timeout=timeout)
        return decode_f1_response(payload)


# ---------------------------------------------------------------------------
# Module-level convenience wrapper (kept for non‑RAM‑constrained users)
# ---------------------------------------------------------------------------
_DEFAULT_CONTROLLER = DaikinController()


def init_uart(uart_id=1, tx=7, rx=6, baudrate=2400, bits=8, parity=0, stop=2, timeout=1000):
    """Initialize the shared module-level UART controller."""
    global _DEFAULT_CONTROLLER
    # properly release old UART if exists
    if _DEFAULT_CONTROLLER is not None and _DEFAULT_CONTROLLER._uart is not None:
        _DEFAULT_CONTROLLER.deinit_uart()
    _DEFAULT_CONTROLLER = DaikinController(
        uart_id=uart_id, tx=tx, rx=rx, timeout=timeout,
        baudrate=baudrate, bits=bits, parity=parity, stop=stop
    )
    return _DEFAULT_CONTROLLER.init_uart()


def send_command(command, payload=b"", read_response=False, timeout=1000):
    return _DEFAULT_CONTROLLER.send_command(command, payload=payload, read_response=read_response, timeout=timeout)

def send_query(query, timeout=1000):
    response_frame = send_command(query, read_response=True, timeout=timeout)
    return parse_packet(response_frame)

def send_setter(setter, payload=b"", read_response=False, timeout=1000):
    return send_command(setter, payload=payload, read_response=read_response, timeout=timeout)

# Query helpers that return raw payload (keep existing)
def query_power_mode_temp_fan(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.POWER_MODE_TEMP_FAN, timeout=timeout)

def query_features(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.FEATURES, timeout=timeout)

def query_swing_humidity(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.SWING_HUMIDITY, timeout=timeout)

def query_powerful_quiet_led(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.POWERFUL_QUIET_LED, timeout=timeout)

def query_demand_eco(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.DEMAND_ECO, timeout=timeout)

def query_protocol_version(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.PROTOCOL_VERSION, timeout=timeout)

def query_temps_alt(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.TEMPS_ALT, timeout=timeout)

def query_feature_bits(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.FEATURE_BITS, timeout=timeout)

def query_power_consumption(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.POWER_CONSUMPTION, timeout=timeout)

def query_model(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.MODEL, timeout=timeout)

def query_room_temp(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.ROOM_TEMP, timeout=timeout)

def query_outside_temp(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.OUTSIDE_TEMP, timeout=timeout)

def query_inlet_temp(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.INLET_TEMP, timeout=timeout)

def query_fan_rpm(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.FAN_RPM, timeout=timeout)

def query_compressor_rpm(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.COMPRESSOR_RPM, timeout=timeout)

def query_humidity(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.HUMIDITY, timeout=timeout)

def query_louver_angle(timeout=1000):
    return _DEFAULT_CONTROLLER.query_payload(DaikinQuery.LOUVER_ANGLE, timeout=timeout)

# Setter wrappers (raw bytes still accepted, but you can use helpers)
def set_swing_humidity(payload=b"", read_response=False, timeout=1000):
    return send_setter(DaikinSetter.SWING_HUMIDITY, payload=payload, read_response=read_response, timeout=timeout)

def set_powerful_quiet_led(payload=b"", read_response=False, timeout=1000):
    return send_setter(DaikinSetter.POWERFUL_QUIET_LED, payload=payload, read_response=read_response, timeout=timeout)

def set_demand_eco(payload=b"", read_response=False, timeout=1000):
    return send_setter(DaikinSetter.DEMAND_ECO, payload=payload, read_response=read_response, timeout=timeout)

# Convenience on/off
def turn_on(temp, fan=DaikinFanSpeed.AUTO, mode=DaikinMode.COOL, timeout=1000):
    return _DEFAULT_CONTROLLER.turn_on(temp=temp, fan=fan, mode=mode, timeout=timeout)

def turn_off(timeout=1000):
    return _DEFAULT_CONTROLLER.turn_off(timeout=timeout)

def turn_ac_on(mode=DaikinMode.COOL, temp=18, fan=DaikinFanSpeed.AUTO, timeout=1000):
    return turn_on(temp=temp, fan=fan, mode=mode, timeout=timeout)

def turn_ac_off(timeout=1000):
    return turn_off(timeout=timeout)

# Temperature / status shortcuts
def get_temp(timeout=1000):
    payload = _DEFAULT_CONTROLLER.query_payload(DaikinQuery.POWER_MODE_TEMP_FAN, timeout=timeout)
    status = decode_f1_response(payload)
    return status['target_temp']

def get_target_temp(timeout=1000):
    return get_temp(timeout=timeout)

def get_status(timeout=1000):
    return _DEFAULT_CONTROLLER.get_status(timeout=timeout)