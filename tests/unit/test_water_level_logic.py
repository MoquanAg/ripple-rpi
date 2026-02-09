"""
Test water level monitoring and refill logic.

Critical tests:
- Low water level opens refill valve
- Adequate water level keeps valve closed
- Sensor failures prevent valve operation (safety)
- Enable toggle disables valve control
"""
import pytest
from unittest.mock import MagicMock, patch, call
import sys
from pathlib import Path
import configparser

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


@pytest.fixture
def mock_config_water_level(tmp_path, monkeypatch):
    """Config fixture specifically for water level tests with helper methods"""
    class ConfigHelper:
        def __init__(self, config_path):
            self.config_path = config_path

        def set_water_level_target(self, target, deadband=10.0, enabled=True):
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

    def test_no_refill_when_water_level_adequate(self, mock_relay, mock_config_water_level, monkeypatch):
        """Adequate water level should not trigger valve action"""
        # Arrange
        mock_config_water_level.set_water_level_target(80.0, 10.0)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        # Act
        from src.water_level_static import evaluate_water_level
        evaluate_water_level(85.0)  # 85% - between low_threshold (70) and max (100)

        # Assert - no valve action (hysteresis zone)
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

    def test_valve_closes_when_above_max(self, mock_relay, mock_config_water_level, monkeypatch):
        """Water above maximum should close the valve"""
        # Arrange
        mock_config_water_level.set_water_level_target(80.0, 10.0)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        # Act
        from src.water_level_static import evaluate_water_level
        evaluate_water_level(105.0)  # 105% - above max (100)

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
