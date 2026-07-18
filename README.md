# Daikin Wifi Control


## Hey! 

This literally only has the UART library. this won't work right now, and is heavily under work. Expect a working version in the next week.

A MicroPython/CircuitPython library for controlling Daikin air conditioning units via the S21 serial protocol.

## What This Does

This library lets you communicate with Daikin AC units over UART using the S21 protocol. You can:
- Turn the AC on/off
- Set temperature, mode, and fan speed
- Query sensor data (room temp, humidity, RPM, power consumption, etc.)
- Control features like swing, quiet mode, eco mode, and LED brightness

## Why This Exists

The S21 protocol is genuinely bizarre. It uses reversed ASCII, @-based temperature encoding, and other quirks that make no sense. This library handles all that weirdness so you don't have to suffer through it.

## Installation

Copy `daikin_ac_utils.py` to your MicroPython/CircuitPython device.

## Quick Start

```python
import daikin_ac_utils as daikin

# Initialize UART (pins may vary by board)
daikin.init_uart(uart_id=1, tx=7, rx=6)

# Turn on the AC at 22°C in cool mode
daikin.turn_ac_on(mode=daikin.DaikinMode.COOL, temp=22)

# Get current status
status = daikin.get_status()
print(status)  # {'power': True, 'mode': DaikinMode.COOL, 'target_temp': 22.0, 'fan': ...}

# Query sensors
room_temp = daikin.query_room_temp()
humidity = daikin.query_humidity()
print(f"Room: {room_temp}°C, Humidity: {humidity}%")

# Turn it off
daikin.turn_ac_off()
```

## Main Classes & Functions

### DaikinController
Low-level class for direct UART communication. Use this if you want fine-grained control.

```python
controller = daikin.DaikinController(uart_id=1, tx=7, rx=6)
controller.init_uart()
status = controller.get_status()
```

### Module-Level Functions
High-level convenience functions for common operations:
- `init_uart()` – Initialize the UART
- `turn_ac_on(temp, mode, fan)` – Turn on with settings
- `turn_ac_off()` – Turn off
- `get_status()` – Get current power/mode/temp/fan state
- `query_*()` – Query sensor data (temp, humidity, RPM, etc.)

### Enums
Pre-defined byte values for commands:
- `DaikinMode` – AUTO, DRY, COOL, HEAT, FAN
- `DaikinFanSpeed` – AUTO, QUIET, SPEED_1–SPEED_5
- `DaikinQuery` – F1, F2, etc. (query commands)
- `DaikinSetter` – D1, D5, etc. (setter commands)

## UART Configuration

Default pins and settings:
```python
daikin.init_uart(
    uart_id=1,      # UART instance
    tx=7,           # TX pin
    rx=6,           # RX pin
    baudrate=2400,  # Fixed by S21 protocol
    bits=8,
    parity=0,       # None
    stop=2,
    timeout=1000    # ms
)
```

Adjust `tx` and `rx` for your board. Baud rate must stay at 2400 (that's what the AC speaks).

## Examples

### Set Temperature
```python
daikin.turn_ac_on(temp=24, mode=daikin.DaikinMode.COOL)
```

### Enable Quiet Mode
```python
payload = daikin.make_powerful_quiet_led(quiet=True)
daikin.set_powerful_quiet_led(payload=payload)
```

### Check Power Consumption
```python
wh = daikin.query_power_consumption()
print(f"Total energy used: {wh} Wh")
```

### Vertical Swing
```python
payload = daikin.make_swing_payload(vertical=True)
daikin.set_swing_humidity(payload=payload)
```

## Notes

- The S21 protocol is stateless and synchronous — each command waits for acknowledgment.
- Temperature range is typically 18–30°C (clamped in `encode_temp()`).
- Timeouts default to 1000 ms but can be adjusted per call.
- Some features may not be available on all AC models.

## Debugging

If things aren't working:
1. Check that UART tx/rx pins are correct for your board
2. Make sure the baud rate is 2400 (non-negotiable)
3. Verify the AC unit is powered on and connected
4. Increase the timeout if you're getting `TimeoutError`

## License

nah dont feel like it 

---

**Pro Tip:** Read the comments in `daikin_ac_utils.py` if you want to understand the S21 protocol weirdness. You've been warned.
