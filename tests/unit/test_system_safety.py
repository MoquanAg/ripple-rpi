import pytest


def test_multi_sensor_failure_triggers_shutdown(mock_ec_sensor, mock_ph_sensor, mock_relay, tmp_path):
    """EC + pH both invalid triggers fail-safe shutdown"""
    from src.sensor_validation import is_valid_ec, is_valid_ph
    from src.emergency_shutdown import is_emergency_active, trigger_emergency_shutdown

    flag_path = str(tmp_path / "emergency.flag")

    mock_ec_sensor.ec = 0.0
    mock_ph_sensor.ph = None

    ec_valid = is_valid_ec(mock_ec_sensor.ec)
    ph_valid = is_valid_ph(mock_ph_sensor.ph)

    invalid_count = sum([not ec_valid, not ph_valid])

    if invalid_count >= 2:
        trigger_emergency_shutdown(
            reason="multi_sensor_failure",
            flag_path=flag_path,
            relay=mock_relay
        )

    assert is_emergency_active(flag_path) == True


def test_emergency_flag_blocks_auto_restart(tmp_path):
    """Emergency shutdown requires manual intervention"""
    from src.emergency_shutdown import trigger_emergency_shutdown, is_emergency_active

    flag_path = str(tmp_path / "emergency.flag")

    trigger_emergency_shutdown(
        reason="multi_sensor_failure",
        flag_path=flag_path,
        relay=None
    )

    can_auto_restart = not is_emergency_active(flag_path)
    assert can_auto_restart == False


def test_ec_and_water_level_failure_shutdown(mock_ec_sensor, mock_water_level_sensor_configurable, tmp_path):
    """EC + Water level invalid triggers shutdown"""
    from src.sensor_validation import is_valid_ec, is_valid_water_level
    from src.emergency_shutdown import is_emergency_active, trigger_emergency_shutdown

    flag_path = str(tmp_path / "emergency.flag")

    mock_ec_sensor.ec = -1.0
    mock_water_level_sensor_configurable.level = 150

    invalid_count = sum([
        not is_valid_ec(mock_ec_sensor.ec),
        not is_valid_water_level(mock_water_level_sensor_configurable.level)
    ])

    if invalid_count >= 2:
        trigger_emergency_shutdown(
            reason="multi_sensor_failure",
            flag_path=flag_path,
            relay=None
        )

    assert is_emergency_active(flag_path) == True


def test_all_sensors_invalid_complete_shutdown(mock_ec_sensor, mock_ph_sensor,
                                                mock_water_level_sensor_configurable, tmp_path):
    """All three sensors invalid triggers complete shutdown"""
    from src.sensor_validation import is_valid_ec, is_valid_ph, is_valid_water_level
    from src.emergency_shutdown import is_emergency_active, trigger_emergency_shutdown

    flag_path = str(tmp_path / "emergency.flag")

    mock_ec_sensor.ec = float('nan')
    mock_ph_sensor.ph = None
    mock_water_level_sensor_configurable.level = -50

    invalid_count = sum([
        not is_valid_ec(mock_ec_sensor.ec),
        not is_valid_ph(mock_ph_sensor.ph),
        not is_valid_water_level(mock_water_level_sensor_configurable.level)
    ])

    if invalid_count >= 2:
        trigger_emergency_shutdown(
            reason=f"multi_sensor_failure_{invalid_count}_sensors",
            flag_path=flag_path,
            relay=None
        )

    assert is_emergency_active(flag_path) == True
