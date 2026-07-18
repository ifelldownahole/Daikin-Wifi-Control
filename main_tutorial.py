# this file is painful, but this file will help out.

from enum import Enum

# Enum lets me have a bunch of constants in a human readable list. 

"""
By the way, these are ALL hexadecimal values. I have a fear of them and that's why we will NEVER, NEVER use hardcoded decimals.

This has the sole exception of 0xFF 
"""

# Define control characters as bytes objects
START_BIT = b'\x02' # Start of message!
END_BIT   = b'\x03' # Over!
ACK       = b'\x06' # Copy!
NAK       = b'\x15' # Do not copy!



class DaikinQuery(bytes, Enum):
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
    ACTUAL_TARGET_TEMP  = b'RN'
    LOUVER_ANGLE        = b'RX'

class DaikinMode(bytes, Enum):
    AUTO = b'0'
    HEAT = b'1'
    COOL = b'2'
    DRY  = b'7'
    FAN  = b'6'

class DaikinFanSpeed(bytes, Enum):
    AUTO  = b'A'
    QUIET = b'B'
    SPEED_1 = b'3'
    SPEED_2 = b'4'
    SPEED_3 = b'5'
    SPEED_4 = b'6'
    SPEED_5 = b'7'

class DaikinSetter(bytes, Enum):
    POWER_MODE_TEMP_FAN = b'D1'
    SWING_HUMIDITY      = b'D5'
    POWERFUL_QUIET_LED  = b'D6'
    DEMAND_ECO          = b'D7'

class DaikinPower(bytes, Enum):
    ON = b'1'
    OFF = b'0'

"""
Let me break it down for you Noelle.

The problem with a python dictionary is that vs code won't actually autocomplete the keys because a dictionary looks like this:

dictionary = {
    "key" = value
}

See how those keys MUST be strings? Well, we don't like that. It makes the  convenience of not using a bunch of constants poof away.

An enum class, as you can see, has 2 things. the thing is set to both be a byte value, and also an enum. If we only declare it like

class MyEnum(Enum):
    EXAMPLE = False

Then to get the value, I must grab it like this:

variable = MyEnum.EXAMPLE.value

You see, I need to prefix everything with .value to actually grab its contents. By adding bytes, or in this case boolean, it's like:

variable = MyEnum.EXAMPLE

Much cleaner, especially when we're only using one data type, which is bytes. You can see why I'm using it. 

And also, if you ever put your own here:
    - Please only use CONSTANTS. The entire point is to make it more human readable and fool proof. Using normal variables is dumb.
    - To seperate these from functions, we do NOT_use_snake_case. WeUsePascalCaseInstead!
    - Please semantically seperate enums, some constants don't need to be grouped into this. It's for long, related constants.
    - Finally, while you *can* assign different data types to enums, such as:

        class MyEnum(Enum):
            EXAMPLE = False
            EXAMPLE2 = 10
            EXAMPLE3 = "hi!"

     It's better if you just don't do that. It forces us to append with .value, but its not banned. Just reconsider, unless it's clean.
"""


def calculate_checksum(data: bytes) -> bytes:
    """
    I don't get why we'd need a checksum for serial but fine...
    This function gets the checksum of anything put in.
    You should ONLY use the checksum of the command and payload bytes! 
    The AC doesn't want anything else!
    """
    # Sum the integer values of the bytes
    chk_sum_int = sum(data) & 0xFF
    
    # Check against reserved control characters (as integers)
    reserved = {START_BIT[0], END_BIT[0], ACK[0], NAK[0]}
    
    if chk_sum_int in reserved:
        chk_sum_int = (chk_sum_int + 2) & 0xFF
        
    # Return as a single-byte object
    return bytes([chk_sum_int])

def assemble_packet(command: bytes, payload: bytes = b"") -> bytes:
    """Adds all the little bytes together so you can send it right to the AC."""
    # Calculate checksum based on the combined data
    checksum = calculate_checksum(command + payload)
    
    # Everything here is already a bytes object, so we can just add them
    return START_BIT + command + payload + checksum + END_BIT

def encode_temp(temp: int) -> bytes:
    """
    The bloody temp is stored in a formula! For what purpose???
    We must now encode and decode it because of this... what nonsense...
    """
    # Added safety clamp so we actually don't cool to extreme temperatures
    clamped_temp = max(18, min(temp, 30))
    return bytes([int((clamped_temp - 18.0) * 2 + 64)])

def decode_temp(temp_byte: int) -> float:
    """Reverse of encode_temp: convert a byte value back to temperature in Celsius."""
    return (temp_byte - 64) / 2 + 18

def turn_ac_on(mode: DaikinMode, temp: int, fan: DaikinFanSpeed) -> bytes:
    """
    What do you think this does???
    Okay, that aside, you should know something important about this function.
    As you can see, when we assemble this packet, we must specify:
        - The fan value (fanspeed)
        - The target temp (I clamp these, but you can accidentally set heating mode to 18 degrees. that's a bit bad.)
        - The mode (heat, cool, auto, dehumidify)
    The little bits on the parameters lock it so the mode parameter MUST be from the enums that I set. 
    
    btw the payload order MUST be Power -> Mode -> Temp -> Fan. 
    If you swap Mode and Temp, the AC will NAK because it can't find a mode called 'I' (or whatever the temp byte is).
    """
    payload = DaikinPower.ON.value
    payload += mode.value
    payload += encode_temp(temp)
    payload += fan.value
    return assemble_packet(DaikinSetter.POWER_MODE_TEMP_FAN.value, payload)

def turn_ac_off() -> bytes:
    """Send power off command. Mode and fan are set to defaults (auto)."""
    payload = DaikinPower.OFF.value
    payload += encode_temp(18)  # default temp doesn't matter but fine i'll do it anyway
    payload += DaikinMode.AUTO.value
    payload += DaikinFanSpeed.AUTO.value
    return assemble_packet(DaikinSetter.POWER_MODE_TEMP_FAN.value, payload)
