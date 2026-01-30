"""Sensor data validation for safety-critical fertigation control"""

import math
from typing import Union


def is_valid_ec(ec_value: Union[float, int, None]) -> bool:
    """
    Validate EC sensor reading.

    Valid range: 0.01 - 3.0 mS/cm

    Args:
        ec_value: EC reading from sensor

    Returns:
        True if valid, False if invalid/dangerous
    """
    if ec_value is None or not isinstance(ec_value, (int, float)):
        return False

    if math.isnan(ec_value) or math.isinf(ec_value):
        return False

    if ec_value < 0.01 or ec_value > 3.0:
        return False

    return True
