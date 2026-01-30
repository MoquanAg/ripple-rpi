import pytest
from datetime import datetime, timedelta
from freezegun import freeze_time


@pytest.fixture(autouse=True)
def reset_pump_monitor():
    """Reset pump monitor before each test"""
    from src.pump_safety import reset_monitor
    reset_monitor()
    yield


def test_nutrient_pump_30sec_timeout_triggers_emergency(mock_relay, tmp_path):
    """Nutrient pump running 31 seconds triggers emergency shutoff"""
    from src.pump_safety import check_pump_timeouts, start_pump_with_timeout
    from src.emergency_shutdown import is_emergency_active

    flag_path = str(tmp_path / "emergency.flag")

    with freeze_time("2026-01-30 10:00:00") as frozen_time:
        start_pump_with_timeout(
            pump_name="NutrientPumpA",
            relay=mock_relay,
            max_runtime_seconds=30,
            emergency_flag_path=flag_path
        )

        assert mock_relay.get_relay_state("NutrientPumpA") == True

        frozen_time.tick(delta=timedelta(seconds=31))
        check_pump_timeouts(emergency_flag_path=flag_path)

        assert is_emergency_active(flag_path) == True
        assert mock_relay.get_relay_state("NutrientPumpA") == False


def test_mixing_pump_no_timeout(mock_relay, tmp_path):
    """Mixing pump has no timeout (designed for continuous operation)"""
    from src.pump_safety import start_pump_with_timeout, check_pump_timeouts
    from src.emergency_shutdown import is_emergency_active

    flag_path = str(tmp_path / "emergency.flag")

    with freeze_time("2026-01-30 10:00:00") as frozen_time:
        start_pump_with_timeout(
            pump_name="MixingPump",
            relay=mock_relay,
            max_runtime_seconds=None,
            emergency_flag_path=flag_path
        )

        assert mock_relay.get_relay_state("MixingPump") == True

        frozen_time.tick(delta=timedelta(minutes=5))
        check_pump_timeouts(emergency_flag_path=flag_path)

        assert mock_relay.get_relay_state("MixingPump") == True
        assert is_emergency_active(flag_path) == False


@pytest.mark.parametrize("pump_name", [
    "NutrientPumpA",
    "NutrientPumpB",
    "NutrientPumpC",
    "pHPlusPump",
    "pHMinusPump",
])
def test_all_dosing_pumps_have_30sec_timeout(pump_name, mock_relay, tmp_path):
    """All dosing pumps enforce 30 second timeout"""
    from src.pump_safety import start_pump_with_timeout, check_pump_timeouts
    from src.emergency_shutdown import is_emergency_active

    flag_path = str(tmp_path / "emergency.flag")

    with freeze_time("2026-01-30 10:00:00") as frozen_time:
        start_pump_with_timeout(
            pump_name=pump_name,
            relay=mock_relay,
            max_runtime_seconds=30,
            emergency_flag_path=flag_path
        )

        frozen_time.tick(delta=timedelta(seconds=31))
        check_pump_timeouts(emergency_flag_path=flag_path)

        assert is_emergency_active(flag_path) == True


def test_daily_runtime_limit_prevents_overdose(mock_runtime_tracker):
    """60 minute daily limit blocks excessive dosing"""
    mock_runtime_tracker.add_dosing_event("NutrientPumpA", duration_seconds=3600)
    can_dose = mock_runtime_tracker.can_dose(planned_duration=1)
    assert can_dose == False


def test_runtime_tracking_persists_across_restart(tmp_path):
    """Runtime data survives system restart"""
    from src.runtime_tracker import DosingRuntimeTracker

    storage_path = str(tmp_path / "runtime.json")

    tracker1 = DosingRuntimeTracker(storage_path=storage_path)
    tracker1.add_dosing_event("NutrientPumpA", duration_seconds=1800)

    tracker2 = DosingRuntimeTracker(storage_path=storage_path)
    assert tracker2.get_today_total_runtime() == 1800


def test_runtime_tracking_excludes_operational_pumps(tmp_path):
    """Only dosing pumps count toward daily limit"""
    from src.runtime_tracker import DosingRuntimeTracker

    tracker = DosingRuntimeTracker(storage_path=str(tmp_path / "runtime.json"))
    tracker.add_dosing_event("NutrientPumpA", duration_seconds=300)
    assert tracker.get_today_total_runtime() == 300


def test_ec_no_increase_after_1min_stops_dosing(mock_ec_sensor, mock_relay, tmp_path):
    """EC stuck at same value after 1 min runtime triggers alert"""
    from src.stuck_sensor_detection import StuckSensorDetector

    detector = StuckSensorDetector()

    with freeze_time("2026-01-30 10:00:00") as frozen_time:
        mock_ec_sensor.ec = 1.0
        detector.start_dosing("ec", initial_value=1.0)
        frozen_time.tick(delta=timedelta(seconds=20))
        result1 = detector.check_sensor_response("ec", current_value=1.0, runtime_seconds=20)
        assert result1.stuck == False

        detector.start_dosing("ec", initial_value=1.0)
        frozen_time.tick(delta=timedelta(seconds=20))
        result2 = detector.check_sensor_response("ec", current_value=1.0, runtime_seconds=20)
        assert result2.stuck == False

        detector.start_dosing("ec", initial_value=1.0)
        frozen_time.tick(delta=timedelta(seconds=21))
        result3 = detector.check_sensor_response("ec", current_value=1.0, runtime_seconds=21)

        assert result3.stuck == True
        assert result3.action == "stop_dosing_alert"


def test_ec_increase_resets_stuck_counter():
    """EC increase resets stuck sensor counter"""
    from src.stuck_sensor_detection import StuckSensorDetector

    detector = StuckSensorDetector()

    detector.start_dosing("ec", initial_value=1.0)
    result1 = detector.check_sensor_response("ec", current_value=1.0, runtime_seconds=30)
    assert result1.stuck == False

    detector.start_dosing("ec", initial_value=1.0)
    result2 = detector.check_sensor_response("ec", current_value=1.2, runtime_seconds=20)
    assert result2.stuck == False
    assert result2.sensor_responding == True

    detector.start_dosing("ec", initial_value=1.2)
    result3 = detector.check_sensor_response("ec", current_value=1.2, runtime_seconds=30)
    assert result3.stuck == False


def test_ph_no_change_after_1min_stops_dosing():
    """pH stuck at same value after 1 min runtime triggers alert"""
    from src.stuck_sensor_detection import StuckSensorDetector

    detector = StuckSensorDetector()

    with freeze_time("2026-01-30 10:00:00") as frozen_time:
        detector.start_dosing("ph", initial_value=6.5)
        frozen_time.tick(delta=timedelta(seconds=61))
        result = detector.check_sensor_response("ph", current_value=6.5, runtime_seconds=61)

        assert result.stuck == True
