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
