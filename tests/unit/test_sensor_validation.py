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


def test_ph_below_min_rejected():
    """pH < 4.0 indicates sensor failure"""
    from src.sensor_validation import is_valid_ph
    assert is_valid_ph(3.5) == False


def test_ph_above_max_rejected():
    """pH > 9.0 exceeds sensor limit"""
    from src.sensor_validation import is_valid_ph
    assert is_valid_ph(10.0) == False


@pytest.mark.parametrize("invalid_value", [
    float('nan'),
    None,
    -1.0,
])
def test_ph_invalid_values_rejected(invalid_value):
    """pH must be valid number in range"""
    from src.sensor_validation import is_valid_ph
    assert is_valid_ph(invalid_value) == False


def test_ph_valid_range_accepted():
    """pH in 4.0-9.0 range is valid"""
    from src.sensor_validation import is_valid_ph
    assert is_valid_ph(4.0) == True
    assert is_valid_ph(6.5) == True
    assert is_valid_ph(9.0) == True


def test_water_level_negative_rejected():
    """Water level cannot be negative"""
    from src.sensor_validation import is_valid_water_level
    assert is_valid_water_level(-10) == False


def test_water_level_above_max_rejected():
    """Water level cannot exceed 100%"""
    from src.sensor_validation import is_valid_water_level
    assert is_valid_water_level(150) == False


def test_water_level_valid_range_accepted():
    """Water level 0-100% is valid"""
    from src.sensor_validation import is_valid_water_level
    assert is_valid_water_level(0) == True
    assert is_valid_water_level(50) == True
    assert is_valid_water_level(100) == True
