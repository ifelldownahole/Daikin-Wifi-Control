"""
Standalone example for the Daikin UART helper library.

This script demonstrates every public function and usage pattern
in the refactored library, using the direct controller instance
(recommended for RAM-constrained devices).

Each block shows:
- Function signature
- What it does
- A working example call

No error handling is included – this is a reference sheet for developers.
Replace UART pins and settings for your hardware before running.
"""

import daikin_ac_utils

"""
DaikinController(uart_id=1, tx=7, rx=6, timeout=1000, baudrate=2400,
                 bits=8, parity=0, stop=2)
Create a controller instance to manage the S21 UART interface.
"""
ac = daikin_ac_utils.DaikinController(uart_id=1, tx=17, rx=16, baudrate=2400,
                               bits=8, parity=0, stop=2, timeout=1000)

"""
init_uart()
Initialise the hardware UART with the parameters given to the constructor.
Must be called before any communication.
"""
ac.init_uart()

"""
calculate_checksum(data)
Compute the single-byte checksum for a command or payload.
"""
checksum = daikin_ac_utils.calculate_checksum(b"F1")
print("Checksum for F1:", checksum)

"""
assemble_packet(command, payload=b"")
Build a full S21 packet frame (STX … ETX) from a command and optional payload.
"""
packet = daikin_ac_utils.assemble_packet(daikin_ac_utils.DaikinQuery.POWER_MODE_TEMP_FAN.value)
print("Assembled packet:", packet)

"""
parse_packet(packet)
Parse a framed packet and return (command, payload).
"""
parsed_command, parsed_payload = daikin_ac_utils.parse_packet(packet)
print("Parsed packet:", parsed_command, parsed_payload)

"""
encode_temp(temp)
Convert a Celsius setpoint (18.0–30.0°C) to the S21 @‑based notation byte.
"""
encoded_temp = daikin_ac_utils.encode_temp(22)
print("Encoded temp for 22°C:", encoded_temp)

"""
decode_temp(temp_byte)
Convert an S21 @‑based notation byte back to a Celsius float.
"""
decoded_temp = daikin_ac_utils.decode_temp(encoded_temp)
print("Decoded temperature:", decoded_temp)

"""
turn_on(temp, fan=DaikinFanSpeed.AUTO, mode=DaikinMode.COOL, timeout=1000)
Send a power‑on command with the given target temperature, fan speed, and mode.
"""
ac.turn_on(temp=20, fan=daikin_ac_utils.DaikinFanSpeed.SPEED_3, mode=daikin_ac_utils.DaikinMode.COOL)
print("AC turned on: 20°C, fan speed 3, COOL mode")

"""
turn_off(timeout=1000)
Send a power‑off command (reverts to AUTO / 18°C / AUTO fan).
"""
ac.turn_off()
print("AC turned off")

"""
get_status(timeout=1000)
Query the current power, mode, target temperature, and fan speed.
Returns a dict with 'power', 'mode', 'target_temp', 'fan'.
"""
status = ac.get_status()
print("Status:", status)

"""
query_payload(DaikinQuery.XXX, timeout=1000)
Low‑level query – returns the raw payload bytes for the given query enum.
"""

"""
decode_protocol_version(payload)
Decode the protocol version payload (F8) into a string.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.PROTOCOL_VERSION)
print("Protocol version:", daikin_ac_utils.decode_protocol_version(payload))

"""
decode_model(payload)
Decode the model identifier payload (FC) into a string.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.MODEL)
print("Model:", daikin_ac_utils.decode_model(payload))

"""
decode_room_temp(payload)
Decode the RH room temperature payload (reversed numeric) → float °C.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.ROOM_TEMP)
print("Room temp:", daikin_ac_utils.decode_room_temp(payload), "°C")

"""
decode_outside_temp(payload)
Decode the Ra outside temperature payload (reversed numeric) → float °C.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.OUTSIDE_TEMP)
print("Outside temp:", daikin_ac_utils.decode_outside_temp(payload), "°C")

"""
decode_inlet_temp(payload)
Decode the RI inlet temperature payload (reversed numeric) → float °C.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.INLET_TEMP)
print("Inlet temp:", daikin_ac_utils.decode_inlet_temp(payload), "°C")

"""
decode_humidity(payload)
Decode the Re humidity payload (reversed integer) → int %.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.HUMIDITY)
print("Humidity:", daikin_ac_utils.decode_humidity(payload), "%")

"""
decode_fan_rpm(payload)
Decode the RL fan RPM payload (reversed decimal × 10) → int RPM.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.FAN_RPM)
print("Fan RPM:", daikin_ac_utils.decode_fan_rpm(payload))

"""
decode_compressor_rpm(payload)
Decode the Rd compressor RPM payload (reversed integer) → int RPM.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.COMPRESSOR_RPM)
print("Compressor RPM:", daikin_ac_utils.decode_compressor_rpm(payload))

"""
decode_louver_angle(payload)
Decode the RN louver angle payload (reversed integer) → int degrees.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.LOUVER_ANGLE)
print("Louver angle:", daikin_ac_utils.decode_louver_angle(payload))

"""
decode_power_consumption(payload)
Decode the FM energy consumption payload (reversed hex) → int Wh.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.POWER_CONSUMPTION)
print("Energy used:", daikin_ac_utils.decode_power_consumption(payload), "Wh")

"""
decode_temps_alt(payload)
Decode the G9 alternate temperatures payload (@‑based) → dict with
'home_temp' and 'outside_temp' floats.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.TEMPS_ALT)
temps = daikin_ac_utils.decode_temps_alt(payload)
print("Alt home temp:", temps['home_temp'], "°C, outside:", temps['outside_temp'], "°C")

"""
decode_f1_response(payload)
Decode the F1/G1 status payload into a dict (power, mode, target_temp, fan).
Already used by get_status(), but shown here for completeness.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.POWER_MODE_TEMP_FAN)
f1 = daikin_ac_utils.decode_f1_response(payload)
print("F1 decoded:", f1)

"""
decode_swing_humidity(payload)
Decode the G5 swing/humidity payload into vertical and horizontal swing booleans.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.SWING_HUMIDITY)
swing = daikin_ac_utils.decode_swing_humidity(payload)
print("Swing state:", swing)

"""
decode_powerful_quiet_led(payload)
Decode the G6 payload into powerful, quiet, comfort, streamer, sensor, led.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.POWERFUL_QUIET_LED)
pql = daikin_ac_utils.decode_powerful_quiet_led(payload)
print("Powerful/Quiet/LED state:", pql)

"""
decode_demand_eco(payload)
Decode the G7 payload into demand (0‑100) and eco boolean.
"""
payload = ac.query_payload(daikin_ac_utils.DaikinQuery.DEMAND_ECO)
de = daikin_ac_utils.decode_demand_eco(payload)
print("Demand/Eco state:", de)

"""
make_swing_payload(vertical=False, horizontal=False)
Return a single‑byte payload for D5 (swing/humidity) from boolean flags.
"""
swing_payload = daikin_ac_utils.make_swing_payload(vertical=True, horizontal=False)
ac.send_command(daikin_ac_utils.DaikinSetter.SWING_HUMIDITY, payload=swing_payload)
print("Swing set: vertical ON, horizontal OFF")

"""
make_powerful_quiet_led_payload(powerful=False, quiet=False, comfort=False,
                                streamer=False, sensor=False, led=0)
Build a 4‑byte payload for D6 (powerful/quiet/LED) using named arguments.
"""
pq_payload = daikin_ac_utils.make_powerful_quiet_led_payload(
    powerful=True, quiet=False, comfort=False,
    streamer=False, sensor=False, led=2   # 2 = bright
)
ac.send_command(daikin_ac_utils.DaikinSetter.POWERFUL_QUIET_LED, payload=pq_payload)
print("Powerful/Quiet/LED set")

"""
make_demand_eco_payload(demand=0, eco=False)
Build a 4‑byte payload for D7 (demand/eco). demand is 0‑100.
"""
de_payload = daikin_ac_utils.make_demand_eco_payload(demand=75, eco=True)
ac.send_command(daikin_ac_utils.DaikinSetter.DEMAND_ECO, payload=de_payload)
print("Demand/Eco set")

"""
send_command(command, payload=b"", read_response=False, timeout=1000)
Send a generic command or setter frame (low‑level).
"""
# (Already used above by the builder examples)

"""
query_features(timeout=1000)   – returns raw payload for F2
query_feature_bits(timeout=1000) – returns raw payload for FK
These are present in the library but may not have dedicated decoders yet.
"""
raw_features = ac.query_payload(daikin_ac_utils.DaikinQuery.FEATURES)
print("Features raw:", raw_features)

raw_fk = ac.query_payload(daikin_ac_utils.DaikinQuery.FEATURE_BITS)
print("Feature bits raw:", raw_fk)

"""
deinit_uart()
Release the UART hardware resources.
"""
ac.deinit_uart()
print("UART deinitialised. Done.")