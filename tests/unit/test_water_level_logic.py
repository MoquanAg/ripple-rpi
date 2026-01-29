"""
Test water level monitoring and refill logic.

Critical tests:
- Low water level opens refill valve
- Adequate water level keeps valve closed
- Sensor failures prevent valve operation (safety)
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
import configparser
import json
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


@pytest.fixture
def mock_config_water_level(tmp_path, monkeypatch):
    """Config fixture specifically for water level tests with helper methods"""
    class ConfigHelper:
        def __init__(self, config_path, data_dir):
            self.config_path = config_path
            self.data_dir = data_dir

        def set_water_level_target(self, target, deadband=10.0):
            """Update water level target and deadband in config"""
            config = configparser.ConfigParser()
            config.read(self.config_path)
            if "WaterLevel" not in config:
                config.add_section("WaterLevel")
            config.set("WaterLevel", "water_level_target", f"80.0, {target}")
            config.set("WaterLevel", "water_level_deadband", f"10.0, {deadband}")
            config.set("WaterLevel", "water_level_min", f"50.0, 50.0")
            config.set("WaterLevel", "water_level_max", f"100.0, 100.0")
            with open(self.config_path, "w") as f:
                config.write(f)

        def write_water_level_data(self, level_value):
            """Write water level value to the sensor data file that water_level_static.py reads"""
            sensor_data_path = self.data_dir / "saved_sensor_data.json"
            timestamp = datetime.now().isoformat() + "Z"
            data = {
                "data": {
                    "water_metrics": {
                        "water_level": {
                            "measurements": {
                                "points": [{
                                    "timestamp": timestamp,
                                    "fields": {
                                        "value": level_value
                                    }
                                }]
                            }
                        }
                    }
                }
            }
            sensor_data_path.write_text(json.dumps(data, indent=2))

    # Create config directory and device.conf
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    device_conf = config_dir / "device.conf"

    # Create data directory for sensor data files
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)

    # Write minimal device.conf with water level settings
    device_conf.write_text("""
[SYSTEM]
fertigation_model = v2

[WaterLevel]
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
        elif result.endswith('saved_sensor_data.json'):
            return str(data_dir / "saved_sensor_data.json")
        return result

    monkeypatch.setattr("os.path.join", patched_join)

    return ConfigHelper(str(device_conf), data_dir)


class TestWaterLevelLogic:
    """Test water level monitoring and refill decisions"""

    def test_refill_when_water_level_low(self, mock_relay, mock_config_water_level, monkeypatch):
        """Low water level should open refill valve"""
        # Arrange
        mock_config_water_level.set_water_level_target(80.0, 10.0)  # Target 80%, deadband 10%
        mock_config_water_level.write_water_level_data(30.0)  # 30% - well below threshold

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.water_level_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.water_level_static import check_water_level_and_determine_action
        action_needed, is_emergency = check_water_level_and_determine_action()

        # Assert - should need refill action
        assert action_needed == True
        # 30% is below minimum (50%), so should be emergency
        assert is_emergency == True

    def test_no_refill_when_water_level_adequate(self, mock_relay, mock_config_water_level, monkeypatch):
        """Adequate water level should keep valve closed"""
        # Arrange
        mock_config_water_level.set_water_level_target(80.0, 10.0)  # Target 80%, deadband 10%
        mock_config_water_level.write_water_level_data(85.0)  # 85% - above target

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.water_level_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.water_level_static import check_water_level_and_determine_action
        action_needed, is_emergency = check_water_level_and_determine_action()

        # Assert - no action needed
        assert action_needed == False
        assert is_emergency == None

    def test_no_refill_when_sensor_unavailable(self, monkeypatch, mock_relay, mock_config_water_level):
        """Sensor failure should prevent valve operation (safety)"""
        # Arrange
        mock_config_water_level.set_water_level_target(80.0, 10.0)
        # Don't write sensor data - simulates sensor failure

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.water_level_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.water_level_static import check_water_level_and_determine_action
        action_needed, is_emergency = check_water_level_and_determine_action()

        # Assert - should return safe defaults (no action)
        assert action_needed == False
        assert is_emergency == None
