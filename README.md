# Daikin Wifi Control

A MicroPython library for controlling Daikin air conditioning units via the S21 serial protocol, plus a full device firmware that connects to your homelab over MQTT.

## What This Is

This runs on a Raspberry Pi Pico W wired to your Daikin AC's S21 port. It speaks the S21 protocol over UART (2400 baud, because of course it does), connects to WiFi, and publishes/subscribes to MQTT so you can monitor and control your AC from anywhere.

The project is split into two files:
- `daikin_ac_utils.py` — the S21 protocol library. All the weirdness lives here.
- `main.py` — the device firmware. Connects to WiFi, connects to MQTT, runs the control loop.

## Why This Exists

The S21 protocol is genuinely bizarre. It uses reversed ASCII, @-based temperature encoding, and other quirks that make no sense. This library handles all that weirdness so you don't have to suffer through it.

Also, Daikin's official app is garbage and I wanted to integrate my AC into my homelab without using some sketchy cloud API.

## Installation

1. Flash MicroPython onto your Pico W
2. Copy `daikin_ac_utils.py` and `main.py` to the board
3. Create a `config.py` with your WiFi and MQTT credentials:

```python
WIFI_SSID = "your_ssid"
WIFI_PASSWORD = "your_password"
CLIENT_ID = "daikin_ac"
MQTT_BROKER = "10.0.0.121"  # or whatever your broker is
MQTT_USER = "your_mqtt_user"
MQTT_PASSWORD = "your_mqtt_password"
```

4. Wire the Pico W to your AC's S21 port (TX, RX, GND)
5. Power it up and watch the magic happen

## UART Configuration

Default pins and settings:
```python
daikin.init_uart(
    uart_id=1,      # UART instance
    tx=7,           # TX pin
    rx=6,           # RX pin
    baudrate=2400,  # Fixed by S21 protocol
    bits=8,
    parity=2,       # None (MicroPython quirk: 2 = None)
    stop=2,
    timeout=1000    # ms
)
```

Adjust `tx` and `rx` for your wiring. Baud rate must stay at 2400 (that's what the AC speaks).

## Using the Library

### High-Level Functions

```python
import daikin_ac_utils as daikin

# Initialize UART
daikin.init_uart(uart_id=1, tx=7, rx=6)

# Turn on the AC at 22°C in cool mode
daikin.turn_on(temp=22, mode=daikin.DaikinMode.COOL)

# Get current status
status = daikin.get_status()
print(status)  # {'power': True, 'mode': b'3', 'target_temp': 22.0, 'fan': b'A'}

# Query sensors
room_temp = daikin.query_room_temp()
humidity = daikin.query_humidity()
print(f"Room: {room_temp}°C, Humidity: {humidity}%")

# Turn it off
daikin.turn_off()
```

### Low-Level Control

```python
controller = daikin.DaikinController(uart_id=1, tx=7, rx=6)
controller.init_uart()

# Raw query
payload = controller.query_payload(daikin.DaikinQuery.ROOM_TEMP)
temp = daikin.decode_room_temp(payload)

# Raw command
controller.send_command(daikin.DaikinSetter.POWER_MODE_TEMP_FAN, payload=b'13H A')
```

### Enums

- `DaikinMode` — AUTO, DRY, COOL, HEAT, FAN
- `DaikinFanSpeed` — AUTO, QUIET, SPEED_1 through SPEED_5
- `DaikinQuery` — F1, F2, F3, F5, F8, RH, Ra, RI, RL, Rd, Re, RN
- `DaikinSetter` — D1, D5

## MQTT Integration

The `main.py` firmware connects to your MQTT broker and can publish/subscribe to topics. This is what lets you integrate the AC into Home Assistant, Node-RED, or whatever else you're running.

The main loop is where you'd add your pub/sub logic — publish sensor data on a schedule, subscribe to control commands, etc.

## S21 Protocol Notes

The S21 protocol is stateless and synchronous — each command waits for acknowledgment. Some quirks:

- Temperature is encoded relative to '@' (ASCII 64) = 18.0°C, with each byte step = 0.5°C
- Some payloads use reversed ASCII (e.g. 18.5°C = `b'581+'`)
- The checksum is sum-of-bytes mod 256, but if it equals 0x03 (ETX), it's replaced with 0x05 (ENQ) to avoid confusion
- The AC sends ACK (0x06) or NAK (0x15) after each command
- Some queries return 5-byte frames, others return 9-byte frames — the code handles both

## Debugging

If things aren't working:
1. Check that UART tx/rx pins are correct for your wiring
2. Make sure the baud rate is 2400 (non-negotiable)
3. Verify the AC unit is powered on and connected
4. Increase the timeout if you're getting `TimeoutError`
5. Check that your MQTT broker is reachable from the Pico W

## License

nah dont feel like it

---

**Pro Tip:** Read the comments in `daikin_ac_utils.py` if you want to understand the S21 protocol weirdness. You've been warned.
