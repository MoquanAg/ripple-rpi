"""Sensor data validation for safety-critical fertigation control"""

import math
from typing import Union


# EC Sensor Validation Constants
EC_MIN_VALID = 0.01  # mS/cm - below this indicates sensor failure/disconnection
EC_MAX_VALID = 3.0   # mS/cm - hardware sensor upper limit

# pH Sensor Validation Constants
PH_MIN_VALID = 4.0  # Below this indicates sensor failure
PH_MAX_VALID = 9.0  # Hardware sensor upper limit

# Water Level Validation Constants
WATER_LEVEL_MIN = 0    # 0% (empty)
WATER_LEVEL_MAX = 100  # 100% (full)


def is_valid_ec(ec_value: Union[float, int, None]) -> bool:
    """
    Validate EC sensor reading.

    Valid range: 0.01 - 3.0 mS/cm
    - Values below 0.01 indicate sensor disconnection or failure
    - Values above 3.0 exceed hardware sensor limit

    Args:
        ec_value: EC reading from sensor

    Returns:
        True if valid, False if invalid/dangerous

    Example:
        ec_reading = ec_sensor.read()
        if is_valid_ec(ec_reading):
            perform_dosing_decision(ec_reading)
        else:
            logger.error("Invalid EC reading, skipping dosing cycle")
    """
    if ec_value is None or not isinstance(ec_value, (int, float)):
        return False

    if math.isnan(ec_value) or math.isinf(ec_value):
        return False

    if ec_value < EC_MIN_VALID or ec_value > EC_MAX_VALID:
        return False

    return True


def is_valid_ph(ph_value: Union[float, int, None]) -> bool:
    """
    Validate pH sensor reading.

    Valid range: 4.0 - 9.0
    - Values below 4.0 indicate sensor failure
    - Values above 9.0 exceed hardware sensor limit

    Args:
        ph_value: pH reading from sensor

    Returns:
        True if valid, False if invalid/dangerous
    """
    if ph_value is None or not isinstance(ph_value, (int, float)):
        return False

    if math.isnan(ph_value):
        return False

    if ph_value < PH_MIN_VALID or ph_value > PH_MAX_VALID:
        return False

    return True


def is_valid_water_level(level: Union[float, int, None]) -> bool:
    """
    Validate water level sensor reading.

    Valid range: 0 - 100%

    Args:
        level: Water level percentage from sensor

    Returns:
        True if valid, False if invalid
    """
    if level is None or not isinstance(level, (int, float)):
        return False

    if math.isnan(level):
        return False

    if level < WATER_LEVEL_MIN or level > WATER_LEVEL_MAX:
        return False

    return True
