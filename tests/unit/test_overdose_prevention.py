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
