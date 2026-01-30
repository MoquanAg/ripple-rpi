import pytest
from pathlib import Path


def test_emergency_shutdown_triggers(tmp_path, mock_relay):
    """Emergency shutdown stops all dosing pumps"""
    from src.emergency_shutdown import trigger_emergency_shutdown, is_emergency_active

    flag_path = tmp_path / "emergency.flag"

    # Arrange: pumps running
    mock_relay.set_relay("NutrientPumpA", True)
    mock_relay.set_relay("NutrientPumpB", True)

    # Act: trigger emergency
    trigger_emergency_shutdown(
        reason="test_timeout",
        flag_path=str(flag_path),
        relay=mock_relay
    )

    # Assert: all dosing pumps stopped
    assert mock_relay.get_relay_state("NutrientPumpA") == False
    assert mock_relay.get_relay_state("NutrientPumpB") == False

    # Assert: flag file created
    assert flag_path.exists()
    assert is_emergency_active(str(flag_path)) == True


def test_emergency_flag_persists(tmp_path):
    """Emergency flag survives restart"""
    from src.emergency_shutdown import trigger_emergency_shutdown, is_emergency_active

    flag_path = tmp_path / "emergency.flag"

    # Set flag
    trigger_emergency_shutdown(
        reason="multi_sensor_failure",
        flag_path=str(flag_path),
        relay=None
    )

    # Simulate restart - create new instance
    assert is_emergency_active(str(flag_path)) == True


def test_clear_emergency_flag(tmp_path):
    """Manual clear removes emergency flag"""
    from src.emergency_shutdown import (
        trigger_emergency_shutdown,
        clear_emergency_shutdown,
        is_emergency_active
    )

    flag_path = tmp_path / "emergency.flag"

    # Set flag
    trigger_emergency_shutdown(
        reason="test",
        flag_path=str(flag_path),
        relay=None
    )
    assert is_emergency_active(str(flag_path)) == True

    # Clear flag
    clear_emergency_shutdown(str(flag_path))
    assert is_emergency_active(str(flag_path)) == False


def test_emergency_shutdown_logs_reason(tmp_path, mock_relay, caplog):
    """Emergency shutdown logs the reason"""
    from src.emergency_shutdown import trigger_emergency_shutdown
    import logging

    flag_path = tmp_path / "emergency.flag"

    with caplog.at_level(logging.ERROR):
        trigger_emergency_shutdown(
            reason="pump_timeout_30sec",
            flag_path=str(flag_path),
            relay=mock_relay
        )

    assert "EMERGENCY SHUTDOWN" in caplog.text
    assert "pump_timeout_30sec" in caplog.text
