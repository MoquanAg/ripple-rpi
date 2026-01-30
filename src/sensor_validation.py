"""Sensor data validation for safety-critical fertigation control"""

import math
from typing import Union


# EC Sensor Validation Constants
EC_MIN_VALID = 0.01  # mS/cm - below this indicates sensor failure/disconnection
EC_MAX_VALID = 3.0   # mS/cm - hardware sensor upper limit


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
