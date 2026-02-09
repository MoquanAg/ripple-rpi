"""
Test water level monitoring and refill logic.

Critical tests:
- Low water level opens refill valve
- Adequate water level keeps valve closed
- Sensor failures prevent valve operation (safety)
- Enable toggle disables valve control
- Drain/flush/full_drain operations
"""
import pytest
from unittest.mock import MagicMock, patch, call
import sys
from pathlib import Path
import configparser
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


@pytest.fixture
def mock_config_water_level(tmp_path, monkeypatch):
    """Config fixture specifically for water level tests with helper methods"""
    class ConfigHelper:
        def __init__(self, config_path):
            self.config_path = config_path

        def set_water_level_target(self, target, deadband=10.0, enabled=True,
                                   safety_floor=30.0, max_duration=1800):
            """Update water level target and deadband in config"""
            config = configparser.ConfigParser()
            config.read(self.config_path)
            if "WaterLevel" not in config:
                config.add_section("WaterLevel")
            config.set("WaterLevel", "water_level_control_enabled", f"true, {'true' if enabled else 'false'}")
            config.set("WaterLevel", "water_level_target", f"80.0, {target}")
            config.set("WaterLevel", "water_level_deadband", f"10.0, {deadband}")
            config.set("WaterLevel", "water_level_min", f"50.0, 50.0")
            config.set("WaterLevel", "water_level_max", f"100.0, 100.0")
            config.set("WaterLevel", "tank_dump_safety_floor", f"30.0, {safety_floor}")
            config.set("WaterLevel", "tank_dump_max_duration_seconds", f"1800, {max_duration}")
            with open(self.config_path, "w") as f:
                config.write(f)

    # Create config directory and device.conf
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    device_conf = config_dir / "device.conf"

    # Write minimal device.conf with water level settings
    device_conf.write_text("""
[SYSTEM]
fertigation_model = v2

[WaterLevel]
water_level_control_enabled = true, true
water_level_target = 80.0, 80.0
water_level_deadband = 10.0, 10.0
water_level_min = 50.0, 50.0
water_level_max = 100.0, 100.0
tank_dump_safety_floor = 30.0, 30.0
tank_dump_max_duration_seconds = 1800, 1800
""")

    # Patch os.path.join to return our test paths
    original_join = __import__('os').path.join
    def patched_join(*args):
        result = original_join(*args)
        if result.endswith('device.conf'):
            return str(device_conf)
        return result

    monkeypatch.setattr("os.path.join", patched_join)

    return ConfigHelper(str(device_conf))


@pytest.fixture(autouse=True)
def reset_drain_state():
    """Reset drain state before each test to avoid cross-test pollution."""
    import src.water_level_static as wls
    wls._drain_state = {
        'active': False,
        'target_level': None,
        'reason': None,
        'started_at': None,
        'max_duration': None,
        'inhibit_refill': True,
        'mode': None,
    }
    yield
    # Also reset after test
    wls._drain_state = {
        'active': False,
        'target_level': None,
        'reason': None,
        'started_at': None,
        'max_duration': None,
        'inhibit_refill': True,
        'mode': None,
    }


class TestWaterLevelLogic:
    """Test water level monitoring and refill decisions"""

    def test_refill_when_water_level_low(self, mock_relay, mock_config_water_level, monkeypatch):
        """Low water level should open refill valve"""
        # Arrange
        mock_config_water_level.set_water_level_target(80.0, 10.0)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        # Act
        from src.water_level_static import evaluate_water_level
        evaluate_water_level(30.0)  # 30% - well below minimum (50%)

        # Assert - valve should have been opened (emergency refill)
        mock_relay.set_valve_outside_to_tank.assert_called_with(True)

    def test_no_action_in_hysteresis_zone(self, mock_relay, mock_config_water_level, monkeypatch):
        """Level between low_threshold and target should not trigger valve action"""
        # Arrange: target=80, deadband=10 → low_threshold=70, hysteresis zone is 70-80
        mock_config_water_level.set_water_level_target(80.0, 10.0)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        # Act
        from src.water_level_static import evaluate_water_level
        evaluate_water_level(75.0)  # 75 cm - in hysteresis zone (70-80)

        # Assert - no valve action
        mock_relay.set_valve_outside_to_tank.assert_not_called()

    def test_no_refill_when_sensor_unavailable(self, monkeypatch, mock_relay, mock_config_water_level):
        """Sensor failure should prevent valve operation (safety)"""
        # Arrange
        mock_config_water_level.set_water_level_target(80.0, 10.0)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        # Act
        from src.water_level_static import evaluate_water_level
        evaluate_water_level(None)  # No sensor data

        # Assert - no valve action
        mock_relay.set_valve_outside_to_tank.assert_not_called()

    def test_valve_closes_at_target(self, mock_relay, mock_config_water_level, monkeypatch):
        """Water at or above target should close the valve"""
        # Arrange: target=80, deadband=10
        mock_config_water_level.set_water_level_target(80.0, 10.0)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        # Act
        from src.water_level_static import evaluate_water_level
        evaluate_water_level(80.0)  # Exactly at target

        # Assert - valve closed
        mock_relay.set_valve_outside_to_tank.assert_called_with(False)

    def test_no_action_when_disabled(self, mock_relay, mock_config_water_level, monkeypatch):
        """Disabled control should not trigger any valve action"""
        # Arrange
        mock_config_water_level.set_water_level_target(80.0, 10.0, enabled=False)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        # Act
        from src.water_level_static import evaluate_water_level
        evaluate_water_level(30.0)  # Would normally trigger emergency refill

        # Assert - no valve action because control is disabled
        mock_relay.set_valve_outside_to_tank.assert_not_called()


class TestDrainLogic:
    """Test drain/flush/full_drain operations"""

    def test_drain_to_target_level_stops_at_target(self, mock_relay, mock_config_water_level, monkeypatch):
        """Drain should stop when level reaches target"""
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain, evaluate_water_level, _drain_state

        result = start_drain(target_level=60.0)
        assert result['status'] == 'ok'
        mock_relay.set_valve_tank_to_outside.assert_called_with(True)

        # Simulate sensor reading at target
        mock_relay.set_valve_tank_to_outside.reset_mock()
        evaluate_water_level(60.0)

        # Drain should have stopped — outlet valve closed
        mock_relay.set_valve_tank_to_outside.assert_called_with(False)

    def test_drain_by_amount_calculates_correct_target(self, mock_relay, mock_config_water_level, monkeypatch):
        """drain_amount should compute target = current - amount"""
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        # Mock WaterLevel sensor to report current level of 80
        mock_sensor = MagicMock()
        mock_sensor.level = 80.0
        monkeypatch.setattr("src.sensors.water_level.WaterLevel._instances", {'main': mock_sensor})

        from src.water_level_static import start_drain, _drain_state
        import src.water_level_static as wls

        result = start_drain(drain_amount=20.0)
        assert result['status'] == 'ok'
        # Target should be 80 - 20 = 60, but clamped to safety_floor (30) since 60 > 30
        assert wls._drain_state['target_level'] == 60.0

    def test_timed_drain_stops_after_duration(self, mock_relay, mock_config_water_level, monkeypatch):
        """Drain with duration_seconds should stop when time exceeds duration"""
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain, evaluate_water_level
        import src.water_level_static as wls

        result = start_drain(duration_seconds=10)
        assert result['status'] == 'ok'

        # Simulate time having passed beyond duration
        wls._drain_state['started_at'] = datetime.now() - timedelta(seconds=15)

        mock_relay.set_valve_tank_to_outside.reset_mock()
        evaluate_water_level(70.0)  # Level still above target (safety_floor=30)

        # Drain should have stopped due to duration exceeded
        mock_relay.set_valve_tank_to_outside.assert_called_with(False)

    def test_safety_floor_clamps_target_in_drain_mode(self, mock_relay, mock_config_water_level, monkeypatch):
        """Target level should be clamped to safety floor in drain mode"""
        mock_config_water_level.set_water_level_target(80.0, 10.0, safety_floor=40.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain
        import src.water_level_static as wls

        result = start_drain(target_level=20.0)  # Below safety floor of 40
        assert result['status'] == 'ok'
        assert wls._drain_state['target_level'] == 40.0  # Clamped to safety floor

    def test_full_drain_bypasses_safety_floor(self, mock_relay, mock_config_water_level, monkeypatch):
        """Full drain mode should set target to 0, bypassing safety floor"""
        mock_config_water_level.set_water_level_target(80.0, 10.0, safety_floor=40.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain
        import src.water_level_static as wls

        result = start_drain(mode='full_drain')
        assert result['status'] == 'ok'
        assert wls._drain_state['target_level'] == 0.0
        assert wls._drain_state['inhibit_refill'] is True

    def test_flush_mode_allows_refill(self, mock_relay, mock_config_water_level, monkeypatch):
        """Flush mode should NOT inhibit refill — inlet stays active"""
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain, evaluate_water_level
        import src.water_level_static as wls

        result = start_drain(mode='flush', duration_seconds=600)
        assert result['status'] == 'ok'
        assert wls._drain_state['inhibit_refill'] is False

        # Simulate reading where level is below minimum — refill should run during flush
        mock_relay.set_valve_outside_to_tank.reset_mock()
        evaluate_water_level(30.0)  # Below water_min (50)

        # Refill valve should have been opened (flush doesn't inhibit refill)
        mock_relay.set_valve_outside_to_tank.assert_called_with(True)

    def test_drain_mode_inhibits_refill(self, mock_relay, mock_config_water_level, monkeypatch):
        """Drain mode should inhibit refill — only outlet active"""
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain, evaluate_water_level

        start_drain(target_level=40.0)

        # Simulate reading where level is below minimum — refill should NOT run during drain
        mock_relay.set_valve_outside_to_tank.reset_mock()
        evaluate_water_level(45.0)  # Below water_min (50) but drain is active

        # Refill valve should NOT have been opened (drain inhibits refill)
        mock_relay.set_valve_outside_to_tank.assert_not_called()

    def test_stop_drain_closes_outlet_valve(self, mock_relay, mock_config_water_level, monkeypatch):
        """Stopping a drain should close the outlet valve"""
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain, stop_drain
        import src.water_level_static as wls

        start_drain(target_level=40.0)
        mock_relay.set_valve_tank_to_outside.reset_mock()

        stop_drain("test stop")
        mock_relay.set_valve_tank_to_outside.assert_called_with(False)
        assert wls._drain_state['active'] is False

    def test_cannot_start_drain_when_already_draining(self, mock_relay, mock_config_water_level, monkeypatch):
        """Starting a drain while one is active should return error"""
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain

        result1 = start_drain(target_level=40.0)
        assert result1['status'] == 'ok'

        result2 = start_drain(target_level=30.0)
        assert result2['status'] == 'error'
        assert 'already active' in result2['message']

    def test_null_level_during_drain_does_not_crash(self, mock_relay, mock_config_water_level, monkeypatch):
        """Null sensor reading during an active drain should not crash"""
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain, evaluate_water_level
        import src.water_level_static as wls

        start_drain(target_level=40.0)

        # Should not raise — None level returns early
        evaluate_water_level(None)

        # Drain should still be active
        assert wls._drain_state['active'] is True

    def test_flush_requires_duration(self, mock_relay, mock_config_water_level, monkeypatch):
        """Flush mode without duration_seconds should return error"""
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain

        result = start_drain(mode='flush')
        assert result['status'] == 'error'
        assert 'duration_seconds' in result['message']

    def test_get_drain_status_when_inactive(self, mock_config_water_level, monkeypatch):
        """get_drain_status should return inactive state when no drain"""
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import get_drain_status

        status = get_drain_status()
        assert status['active'] is False
        assert status['elapsed_seconds'] == 0

    def test_get_drain_status_when_active(self, mock_relay, mock_config_water_level, monkeypatch):
        """get_drain_status should return active state with elapsed time"""
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        monkeypatch.setattr("src.water_level_static.logger", MagicMock())

        from src.water_level_static import start_drain, get_drain_status

        start_drain(target_level=40.0)
        status = get_drain_status()
        assert status['active'] is True
        assert status['target_level'] == 40.0
        assert status['mode'] == 'drain'
        assert 'elapsed_seconds' in status
