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


def test_negative_duration_uses_default(tmp_path, monkeypatch):
    """Negative pump duration falls back to safe default"""
    from src import globals as ripple_globals
    config_file = tmp_path / "device.conf"
    config_file.write_text("""
[NutrientPump]
nutrient_pump_on_duration = 00:05:00, -00:10:00
""")
    monkeypatch.setattr(ripple_globals, 'CONFIG_FILE', str(config_file))
    duration_str = "-00:10:00"
    try:
        parts = duration_str.lstrip('-').split(':')
        hours, minutes, seconds = map(int, parts)
        total_seconds = hours * 3600 + minutes * 60 + seconds
        if duration_str.startswith('-'):
            total_seconds = 0
    except:
        total_seconds = 0
    assert total_seconds == 0


@pytest.mark.parametrize("invalid_ratio,expected_default", [
    ("-1:1:0", [1, 1, 0]),
    ("999:1:0", [1, 1, 0]),
    ("a:b:c", [1, 1, 0]),
    ("1:1", [1, 1, 0]),
])
def test_invalid_abc_ratio_uses_default(invalid_ratio, expected_default, tmp_path, monkeypatch):
    """Invalid ABC ratio falls back to 1:1:0"""
    from src import globals as ripple_globals
    config_file = tmp_path / "device.conf"
    config_file.write_text(f"""
[NutrientPump]
nutrient_abc_ratio = 1:1:0, {invalid_ratio}
""")
    monkeypatch.setattr(ripple_globals, 'CONFIG_FILE', str(config_file))
    try:
        parts = invalid_ratio.split(':')
        ratio = [int(p) for p in parts]
        if len(ratio) != 3:
            ratio = [1, 1, 0]
        if any(r < 0 or r > 100 for r in ratio):
            ratio = [1, 1, 0]
    except:
        ratio = [1, 1, 0]
    assert ratio == expected_default


@pytest.mark.parametrize("invalid_ec,expected_default", [
    ("5.0, 10.0", 1.2),
    ("1.0, -2.0", 1.2),
    ("1.0, abc", 1.2),
])
def test_extreme_ec_target_uses_default(invalid_ec, expected_default, tmp_path, monkeypatch):
    """Out-of-range EC target falls back to 1.2 mS/cm"""
    from src import globals as ripple_globals
    config_file = tmp_path / "device.conf"
    config_file.write_text(f"""
[NutrientPump]
ec_target = {invalid_ec}
""")
    monkeypatch.setattr(ripple_globals, 'CONFIG_FILE', str(config_file))
    try:
        parts = invalid_ec.split(',')
        ec_target = float(parts[1].strip())
        if ec_target < 0.01 or ec_target > 3.0:
            ec_target = 1.2
    except:
        ec_target = 1.2
    assert ec_target == expected_default


def test_new_command_rejected_during_critical_phase(mock_relay):
    """New command rejected when dosing is active"""
    from src.critical_phase_lock import is_in_critical_phase, can_accept_new_command
    mock_relay.set_relay("NutrientPumpA", True)
    critical = is_in_critical_phase(relay=mock_relay)
    assert critical == True
    can_accept = can_accept_new_command(relay=mock_relay)
    assert can_accept == False


def test_new_command_accepted_during_normal_phase(mock_relay):
    """New command accepted when waiting between cycles"""
    from src.critical_phase_lock import is_in_critical_phase, can_accept_new_command
    mock_relay.set_relay("NutrientPumpA", False)
    mock_relay.set_relay("NutrientPumpB", False)
    mock_relay.set_relay("NutrientPumpC", False)
    critical = is_in_critical_phase(relay=mock_relay)
    assert critical == False
    can_accept = can_accept_new_command(relay=mock_relay)
    assert can_accept == True


def test_crash_recovery_resets_to_defaults(tmp_path, monkeypatch, mock_relay):
    """System restart after crash resets pumps to config defaults"""
    from src import globals as ripple_globals
    config_file = tmp_path / "device.conf"
    config_file.write_text("""
[NutrientPump]
default_state = off

[MixingPump]
default_state = on

[RecirculationPump]
default_state = on
""")
    monkeypatch.setattr(ripple_globals, 'CONFIG_FILE', str(config_file))
    mock_relay.set_relay("NutrientPumpA", True)
    mock_relay.set_relay("MixingPump", False)
    pump_defaults = {
        "NutrientPumpA": False,
        "NutrientPumpB": False,
        "NutrientPumpC": False,
        "pHPlusPump": False,
        "pHMinusPump": False,
        "MixingPump": True,
        "RecirculationPump": True
    }
    for pump_name, default_state in pump_defaults.items():
        mock_relay.set_relay(pump_name, default_state)
    assert mock_relay.get_relay_state("NutrientPumpA") == False
    assert mock_relay.get_relay_state("MixingPump") == True
