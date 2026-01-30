import pytest
import math


def test_ec_zero_rejected():
    """EC = 0.0 indicates disconnected sensor"""
    from src.sensor_validation import is_valid_ec
    assert is_valid_ec(0.0) == False


def test_ec_below_min_rejected():
    """EC < 0.01 indicates sensor failure or empty tank"""
    from src.sensor_validation import is_valid_ec
    assert is_valid_ec(0.005) == False


def test_ec_above_max_rejected():
    """EC > 3.0 exceeds hardware sensor limit"""
    from src.sensor_validation import is_valid_ec
    assert is_valid_ec(5.0) == False


@pytest.mark.parametrize("invalid_value", [
    float('nan'),
    float('inf'),
    float('-inf'),
    -1.5,
    None,
])
def test_ec_invalid_values_rejected(invalid_value):
    """EC must be valid number in range"""
    from src.sensor_validation import is_valid_ec
    assert is_valid_ec(invalid_value) == False


def test_ec_valid_range_accepted():
    """EC in 0.01-3.0 range is valid"""
    from src.sensor_validation import is_valid_ec
    assert is_valid_ec(0.01) == True
    assert is_valid_ec(1.5) == True
    assert is_valid_ec(3.0) == True
