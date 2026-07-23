# Daikin AC UART helper library for the S21 protocol.

# This library is designed for MicroPython and CircuitPython environments.

try:
    import machine
except ImportError:
    machine = None

try:
    import time
except ImportError:
    import utime as time

# MicroPython doesn't have TimeoutError – define it ourselves if missing.
try:
    TimeoutError
except NameError:
    class TimeoutError(Exception):
        pass

START_BIT = b'\x02'  # STX (Start of text)
END_BIT = b'\x03'    # ETX (End of text)
ACK = b'\x06'        # Acknowledged
NAK = b'\x15'        # Not Acknowledged


"""
Constants for the S21 protocol's fixed command and setting byte values.
Plain bytes used directly – no enum machinery, no metaclasses, no broken
MicroPython inheritance.  Use them like DaikinMode.COOL, DaikinQuery.ROOM_TEMP,
etc.  They are just bytes and can be concatenated or passed as-is.
"""

class DaikinQuery:
    POWER_MODE_TEMP_FAN = b'F1'
    FEATURES            = b'F2'
    SWING_HUMIDITY      = b'F5'
    POWERFUL_QUIET_LED  = b'F6'
    DEMAND_ECO          = b'F7'
    PROTOCOL_VERSION    = b'F8'
    TEMPS_ALT           = b'F9'
    FEATURE_BITS        = b'FK'
    POWER_CONSUMPTION   = b'FM'
    MODEL               = b'FC'
    ROOM_TEMP           = b'RH'
    OUTSIDE_TEMP        = b'Ra'
    INLET_TEMP          = b'RI'
    FAN_RPM             = b'RL'
    COMPRESSOR_RPM      = b'Rd'
    HUMIDITY            = b'Re'
    LOUVER_ANGLE        = b'RN'


class DaikinMode:
    AUTO = b'0'
    DRY  = b'2'
    COOL = b'3'
    HEAT = b'4'
    FAN  = b'6'


class DaikinFanSpeed:
    AUTO    = b'A'
    QUIET   = b'B'
    SPEED_1 = b'3'
    SPEED_2 = b'4'
    SPEED_3 = b'5'
    SPEED_4 = b'6'
    SPEED_5 = b'7'


class DaikinSetter:
    POWER_MODE_TEMP_FAN = b'D1'
    SWING_HUMIDITY      = b'D5'
    POWERFUL_QUIET_LED  = b'D6'
    DEMAND_ECO          = b'D7'


class DaikinPower:
    ON  = b'1'
    OFF = b'0'


"""
Bit masks are defined here as tiny namespace classes because these S21 setter payloads
are built from multiple independent flags packed into specific byte positions.

A normal Enum is great for single fixed values, but these helpers have to make
multi-byte bitfields for D5/D6/D7 payloads, so explicit builder functions are clearer
and safer than trying to get the exposed methods to do bitwise operations on raw bytes directly.
"""

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
    led: 0=off, 1=dim, 2=bright.
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

"""
The following functions help out with decoding the various payloads returned by the AC unit, because the S21 protocol
is really weird and uses reversed ASCII, @-based temperature encoding, and other quirks. These helpers make it easier to
interpret the raw bytes into meaningful values like temperature, fan speed, and swing state.
Trust me, some of the stuff that you see this protocol doing is just bizarre, and these helpers are here to make it less painful.
"""

def decode_temp_numeric(payload):
    """
    Decode a 4-byte reversed numeric temperature payload into a float.

    The S21 protocol stores some temperatures as 4 ASCII characters in reverse order
    with a leading sign. For example, 18.5°C becomes the bytes b'581+':
      - The raw bytes are reversed: "+185"
      - The string is parsed as a float and divided by 10: 185 / 10 = 18.5

    This handles both positive and negative values (e.g. b'050-' → -5.0°C).
    Returns the temperature as a float in degrees Celsius.
    """
    if len(payload) < 4:
        raise ValueError("Numeric temp payload too short")
    s = payload.decode('ascii')
    rev = s[::-1]
    try:
        return float(rev) / 10.0
    except ValueError:
        raise ValueError("Invalid numeric temperature format: %s" % s)

def decode_numeric_int(payload):
    """
    Decode a reversed decimal integer payload into an int.

    The S21 protocol stores some integer values as ASCII digits in reverse order.
    For example, 1200 RPM (stored as RPM/10 = 120) becomes the bytes b'0210':
      - The raw bytes are reversed: "0120"
      - Leading zeros are stripped: "120"
      - The string is parsed as an integer: 120

    Returns the decoded integer value.
    """
    s = payload.decode('ascii').strip()
    if not s:
        return 0
    rev = s[::-1].lstrip('0') or '0'
    return int(rev)

def decode_hex_reversed(payload):
    """
    Decode a reversed hexadecimal payload into an int.

    Some S21 values (like total energy consumption in Wh) are stored as
    4 ASCII hex characters in reverse order. For example, 14930 Wh (0x3A52)
    becomes the bytes b'25A3':
      - The raw bytes are reversed: "3A52"
      - The string is parsed as hex: 0x3A52 = 14930

    Returns the decoded integer value.
    """
    s = payload.decode('ascii')
    return int(s[::-1], 16)

def decode_temp(temp_byte):
    """
    Decode an S21 @-based temperature byte into a Celsius float.

    The S21 protocol encodes setpoint temperatures relative to the '@' character
    (ASCII 64), which represents 18.0°C. Each step of 1 in the byte value
    represents a 0.5°C change:
      - Subtract 64 from the byte to get the offset from '@'
      - Divide by 2 to convert half-degree steps to whole degrees
      - Add 18.0 to get the actual temperature in Celsius

    (YES, THIS IS ACTUALLY HOW THE AC UNIT DOES IT. I DIDN'T MAKE THIS UP.)

    Example: '@' (64) → (64-64)/2 + 18 = 18.0°C
             'A' (65) → (65-64)/2 + 18 = 18.5°C
             '?' (63) → (63-64)/2 + 18 = 17.5°C

    Returns the temperature as a float in degrees Celsius.
    """
    if isinstance(temp_byte, bytes):
        temp_byte = temp_byte[0]
    return (temp_byte - 64) / 2 + 18


def decode_f1_response(payload):
    """
    Decode an F1/G1 status payload into a dict.

    The F1 payload contains 4 bytes:
      - Byte 0: Power state (b'1' = ON, b'0' = OFF)
      - Byte 1: Operating mode (raw byte, see DaikinMode constants)
      - Byte 2: Target setpoint temperature (@-based encoding, decoded via decode_temp)
      - Byte 3: Fan speed (raw byte, see DaikinFanSpeed constants)

    Returns a dict with keys 'power' (bool), 'mode' (bytes),
    'target_temp' (float), and 'fan' (bytes).

    Why a dict and not a string? 
    It's easier to programatically parse and use the values in code, and it allows for future expansion if more fields are added to the payload.
    (I also just hate parsing strings in Python, so this is also a personal preference.)
    """
    if len(payload) < 4:
        raise ValueError("Invalid F1 payload: expected 4 bytes, got %d" % len(payload))

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

"""
The S21 protocol bundles swing (louver oscillation) and humidity control
into a single register: D5 (setter) and G5 (query response).

Currently only the swing bits are reverse-engineered and documented:
  - Bit 0: Vertical swing
  - Bit 1: Horizontal swing

Might change the name but otherwise it's alright for now.
"""

def decode_swing_humidity(payload):
    """
    Decode G5 swing/humidity payload.

    The spec sheet says these bits have something to do with both swing and humidity, but the exact mapping is not fully documented.

    The swing state is stored in bit 0 (vertical) and bit 1 (horizontal)
    of the first payload byte. Each bit is extracted using a bitwise AND
    with the corresponding SwingBits constant and converted to a boolean.

    Returns a dict with keys 'vertical_swing' (bool) and 'horizontal_swing' (bool).
    """
    if len(payload) < 1:
        raise ValueError("Payload too short for swing")
    b = payload[0]
    return {
        'vertical_swing': bool(b & SwingBits.VERTICAL),
        'horizontal_swing': bool(b & SwingBits.HORIZONTAL),
    }

def decode_powerful_quiet_led(payload):
    """
    Decode G6 powerful/quiet/LED payload into a dict of settings.

    The G6 payload uses 4 bytes with bit-packed flags:
      - Byte 0: powerful (bit 1), comfort (bit 6), quiet (bit 7)
      - Byte 1: streamer (bit 7)
      - Byte 3: sensor (bit 3), LED brightness (bits 2-3, where 00=off, 01=dim, 10=bright)

    Each flag is extracted by masking the appropriate bit and converting to a boolean.
    The LED value is extracted by masking bits 2-3, shifting right by 2, and mapping
    the resulting value (0, 1, 2) to a human-readable string.

    Returns a dict with keys 'powerful', 'quiet', 'comfort', 'streamer', 'sensor' (all bool),
    and 'led' (string: 'off', 'dim', 'bright', or 'unknown').

    Why are 3 pretty much unrelated functions all bundled into one payload? 
    Because the S21 protocol is genuinely not made for any sane human being.
    """
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
    """
    Decode G7 demand/eco payload into a dict.

    For reference, this is supposed to be the ECONO mode that you have on your remote.
    You're usually not allowed to edit the demand percentage, but some units allow it.

    The G7 payload contains:
      - Byte 0: Demand percentage encoded as an ASCII character offset from '0' (0x30).
                Subtract 0x30 from the byte to get the demand value (0-100).
      - Byte 1: Eco mode flag in bit 1 (0x02).

    Returns a dict with keys 'demand' (int, 0-100) and 'eco' (bool).
    """
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
    """
    Decode G9 alternate temperatures payload into a dict.

    The G9 payload contains two @-based temperature bytes:
      - Byte 0: Home/indoor temperature (@-based encoding)
      - Byte 1: Outside temperature (@-based encoding)

    Each byte is decoded using decode_temp(), which subtracts 64 from the byte,
    divides by 2, and adds 18.0 to convert from the @-based notation to Celsius.

    Returns a dict with keys 'home_temp' (float °C) and 'outside_temp' (float °C).
    """
    if len(payload) < 2:
        raise ValueError("Payload too short for G9")
    return {
        'home_temp': decode_temp(payload[0]),
        'outside_temp': decode_temp(payload[1]),
    }

def decode_power_consumption(payload):
    """
    Decode GM energy consumption payload into watt-hours.

    The payload is a 4-character reversed hexadecimal string representing
    the total energy used in watt-hours. For example, b'25A3' reversed is
    '3A52' which is 0x3A52 = 14930 Wh.

    Returns the total energy consumption as an int in watt-hours.
    """
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
    """
    Decode RH room temperature payload into a float.

    Uses decode_temp_numeric() to reverse the 4 ASCII bytes, parse as a
    signed decimal, and divide by 10 to get the temperature in degrees Celsius.
    For example, b'582+' → reversed "+285" → 28.5°C.

    Returns the room temperature as a float in degrees Celsius.
    """
    return decode_temp_numeric(payload)

def decode_outside_temp(payload):
    """
    Decode Ra outside temperature payload into a float.

    Uses decode_temp_numeric() to reverse the 4 ASCII bytes, parse as a
    signed decimal, and divide by 10 to get the temperature in degrees Celsius.

    Returns the outside temperature as a float in degrees Celsius.
    """
    return decode_temp_numeric(payload)

def decode_inlet_temp(payload):
    """
    Decode RI inlet temperature payload into a float.

    Uses decode_temp_numeric() to reverse the 4 ASCII bytes, parse as a
    signed decimal, and divide by 10 to get the temperature in degrees Celsius.

    Returns the inlet temperature as a float in degrees Celsius.
    """
    return decode_temp_numeric(payload)

def decode_fan_rpm(payload):
    """
    Decode RL fan RPM payload into revolutions per minute.

    The payload stores RPM/10 as a reversed decimal integer. For example,
    if the fan is running at 1200 RPM, the payload contains b'0210':
      - decode_numeric_int() reverses and parses this to 120
      - Multiply by 10 to get the actual RPM: 1200

    Returns the fan speed as an int in RPM.
    """
    raw = decode_numeric_int(payload)
    return raw * 10

def decode_compressor_rpm(payload):
    """
    Decode Rd compressor RPM payload into revolutions per minute.

    The payload stores the compressor speed as a reversed decimal integer.
    For example, b'0420' → reversed "0240" → 240 RPM.

    Returns the compressor speed as an int in RPM.
    """
    return decode_numeric_int(payload)

def decode_humidity(payload):
    """
    Decode Re humidity payload into a percentage.

    The payload stores the relative humidity as a reversed decimal integer.
    For example, b'0500' → reversed "0050" → 50%.

    Returns the humidity as an int (0-100).
    """
    return decode_numeric_int(payload)

def decode_louver_angle(payload):
    """
    Decode RN louver angle payload into degrees.

    The payload stores the louver angle as a reversed decimal integer.
    For example, b'001+' → reversed "+100" → 100 degrees (fully open).

    Returns the louver angle as an int in degrees.
    """
    return decode_numeric_int(payload)

"""
Phew, all the decoders done! these next guys are the actual S21 packet assembly and parsing functions, which are a bit more involved.
"""

def calculate_checksum(data):
    """
    Compute the single-byte checksum for S21 packet data.

    The S21 checksum is the sum of all bytes between STX and ETX, masked to 8 bits
    (modulo 256). If the result equals the ETX byte value (0x03), the ENQ byte (0x05)
    is substituted instead. This prevents the checksum byte from being mistaken for
    an end-of-packet marker inside the frame. Yeah, this is a weird quirk of the S21 protocol, but it's how the AC unit expects it.

    Takes a bytes-like object containing the command and payload bytes.
    Returns a single checksum byte as a bytes object.
    """
    chk_sum_int = sum(data) & 0xFF
    if chk_sum_int == 0x03:
        chk_sum_int = 0x05
    return bytes([chk_sum_int])


def assemble_packet(command, payload=b""):
    """
    Build a complete S21 protocol packet ready for transmission.

    Constructs the packet in this order:
      STX (0x02) + command (2 bytes) + payload (0-4 bytes) + checksum (1 byte) + ETX (0x03)

    The checksum is calculated over the command and payload bytes using calculate_checksum().

    Returns the fully framed packet as bytes.
    """
    checksum = calculate_checksum(command + payload)
    return START_BIT + command + payload + checksum + END_BIT


def parse_packet(packet):
    """
    Extract the command and payload from a received S21 packet.

    Validates the packet structure:
      - Minimum length of 5 bytes (STX + 2-byte command + checksum + ETX)
      - Starts with STX (0x02) and ends with ETX (0x03)
      - Checksum is calculated over the command+payload and must match the received checksum

    Returns a tuple of (command, payload) as bytes.
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
    Encode a Celsius temperature into the S21 @-based notation byte. God bless us all.

    The S21 protocol represents temperatures relative to '@' (ASCII 64) which equals 18.0°C.
    Each step of 1 in the byte value represents a 0.5°C change:
      - Clamp the temperature to the allowed range (18.0–30.0°C)
      - Subtract 18.0 to get the offset from the baseline
      - Multiply by 2 to convert to half-degree steps
      - Add 64 to get the ASCII byte value

    Example: 22°C → (22-18)*2 + 64 = 72 → 'H' (0x48)
             18°C → (18-18)*2 + 64 = 64 → '@' (0x40)

    The input is clamped to 18.0–30.0°C for safety (matches my unit's limits).
    Returns the encoded temperature as a single byte (bytes object).
    """
    clamped_temp = max(20, min(temp, 29))
    return bytes([int((clamped_temp - 18.0) * 2 + 64)])

"""
That's pertty much the entire backbone of the S21 protocol handling. The rest of the code is just a wrapper class to manage the UART
and provide higher-level methods for common operations. Finally something that isn't completely insane to read. 
"""


class DaikinController:

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
        """Initialize the UART hardware. Must be called before any communication."""
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
        """
        Discard any unread bytes waiting in the UART receive buffer.

        Reads and throws away all available data. This is called at the
        start of every transaction to ensure a clean slate — any stale or
        partial data from a previous failed exchange won't be mistaken for
        the response to the next command.
        """
        if self._uart is None:
            return
        while self._uart.any():
            self._uart.read()

    def _read_exact(self, n, deadline):
        """
        Read exactly n bytes from the UART, blocking until the deadline.

        Keeps reading in a loop until either:
            - The requested number of bytes have been collected (returns the buffer)
            - The deadline (in MicroPython ticks_ms units) has passed (returns whatever was collected so far, possibly fewer than n bytes)

        This is used instead of a plain uart.read(n) because the AC unit may
        send bytes in small chunks with gaps between them. The deadline ensures
        we don't hang forever if the AC stops transmitting mid-packet.
        """
    
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
        3. If we're asking for data, read full incoming data frame and write ACK back to AC.
        Returns the full received frame (including STX/ETX) if expect_reply is True,
        otherwise returns an empty bytes object.

        Sounds simple? No, this is hell.
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
                "Daikin AC returned a NAK!"
                "This command or query field is unsupported on this AC unit model, your code aint right."
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
            raise TimeoutError("Timed out waiting for the AC data payload frame header :(")

        """
        Step 3: Securely parse packet length without guessing.
        After STX, we have command (2 bytes), then either:
            - checksum + ETX (5-byte frame, no payload)
            - payload[0:2] (+ later 2 payload bytes + checksum + ETX) -> 9-byte frame
        """

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
        # Accept raw bytes or strings – all our constants are bytes, so this is simple.
        if isinstance(command, (bytes, bytearray)):
            command_bytes = bytes(command)
        elif isinstance(command, str):
            command_bytes = command.encode("ascii")
        else:
            raise TypeError("Command must be bytes or str")

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
        payload = DaikinPower.ON + mode + encode_temp(temp) + fan
        return self.send_command(DaikinSetter.POWER_MODE_TEMP_FAN, payload=payload, read_response=False, timeout=timeout)

    def turn_off(self, timeout=1000):
        payload = DaikinPower.OFF + DaikinMode.AUTO + encode_temp(18) + DaikinFanSpeed.AUTO
        return self.send_command(DaikinSetter.POWER_MODE_TEMP_FAN, payload=payload, read_response=False, timeout=timeout)

    def get_status(self, timeout=1000):
        payload = self.query_payload(DaikinQuery.POWER_MODE_TEMP_FAN, timeout=timeout)
        return decode_f1_response(payload)



"""
The following wrappers provide a simple, high-level interface that doesn't require
manually creating or managing a DaikinController instance.

Yes, every function here costs a small amount of RAM — a concern on
microcontrollers — but they're kept for users who prioritise ease of use
over squeezing every byte of heap. For RAM-constrained projects, use the
DaikinController class directly instead.
"""


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

# That's the end of the file! LETS GOOOOOOOOO
