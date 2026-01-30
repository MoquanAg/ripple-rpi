"""
Test pH dosing decision logic based on pH sensor readings.

Critical tests:
- pH too high triggers pH down pump
- pH too low triggers pH up pump
- pH in range skips dosing
- Sensor failures prevent dosing (safety)
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
def mock_config_ph(tmp_path, monkeypatch):
    """Config fixture specifically for pH tests with helper methods"""
    class ConfigHelper:
        def __init__(self, config_path, data_dir):
            self.config_path = config_path
            self.data_dir = data_dir

        def set_ph_target(self, target, deadband):
            """Update pH target and deadband in config"""
            config = configparser.ConfigParser()
            config.read(self.config_path)
            if "pH" not in config:
                config.add_section("pH")
            config.set("pH", "ph_target", f"6.0, {target}")
            config.set("pH", "ph_deadband", f"0.2, {deadband}")
            config.set("pH", "ph_min", f"4.0, 4.0")
            config.set("pH", "ph_max", f"8.0, 8.0")
            with open(self.config_path, "w") as f:
                config.write(f)

        def set_ph_pump_config(self, on_duration="00:00:02", wait_duration="00:02:00"):
            """Update pH pump on and wait durations in config"""
            config = configparser.ConfigParser()
            config.read(self.config_path)
            if "NutrientPump" not in config:
                config.add_section("NutrientPump")
            config.set("NutrientPump", "ph_pump_on_duration", f"00:00:02, {on_duration}")
            config.set("NutrientPump", "ph_pump_wait_duration", f"00:02:00, {wait_duration}")
            with open(self.config_path, "w") as f:
                config.write(f)

        def write_ph_log(self, ph_value):
            """Write pH value to the log file that ph_static.py reads"""
            log_path = self.data_dir / "sensor_data.data.water_metrics.ph.log"
            timestamp = datetime.now().isoformat() + "Z"
            data = {
                "measurements": {
                    "points": [{
                        "fields": {
                            "value": ph_value
                        }
                    }]
                }
            }
            log_line = f"{timestamp}\tINFO\t{json.dumps(data)}\n"
            log_path.write_text(log_line)

    # Create config directory and device.conf
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    device_conf = config_dir / "device.conf"

    # Create data directory for log files
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)

    # Write minimal device.conf with pH settings
    device_conf.write_text("""
[SYSTEM]
fertigation_model = v2

[NutrientPump]
ph_pump_on_duration = 00:00:02, 00:00:02
ph_pump_wait_duration = 00:02:00, 00:02:00

[pH]
ph_target = 6.0, 6.5
ph_deadband = 0.2, 0.3
ph_min = 4.0, 4.0
ph_max = 8.0, 8.0
""")

    # Patch os.path.join to return our test paths
    original_join = __import__('os').path.join
    def patched_join(*args):
        result = original_join(*args)
        if result.endswith('device.conf'):
            return str(device_conf)
        elif result.endswith('sensor_data.data.water_metrics.ph.log'):
            return str(data_dir / "sensor_data.data.water_metrics.ph.log")
        return result

    monkeypatch.setattr("os.path.join", patched_join)

    return ConfigHelper(str(device_conf), data_dir)


class TestpHLogic:
    """Test pH-driven dosing decisions"""

    def test_ph_down_when_ph_too_high(self, mock_relay, mock_config_ph, monkeypatch):
        """pH above upper threshold should activate pH down pump"""
        # Arrange
        mock_config_ph.set_ph_target(6.5, 0.3)  # Range: [6.2, 6.8]
        mock_config_ph.set_ph_pump_config()
        mock_config_ph.write_ph_log(7.5)  # pH too high

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up = check_if_ph_adjustment_needed()

        # Assert
        # Should need adjustment and should NOT use pH up (meaning use pH down)
        assert needs_adjustment == True
        assert use_ph_up == False

    def test_ph_up_when_ph_too_low(self, mock_relay, mock_config_ph, monkeypatch):
        """pH below lower threshold should activate pH up pump"""
        # Arrange
        mock_config_ph.set_ph_target(6.5, 0.3)  # Range: [6.2, 6.8]
        mock_config_ph.set_ph_pump_config()
        mock_config_ph.write_ph_log(5.8)  # pH too low

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up = check_if_ph_adjustment_needed()

        # Assert
        # Should need adjustment and should use pH up
        assert needs_adjustment == True
        assert use_ph_up == True

    def test_no_ph_dosing_when_in_range(self, mock_relay, mock_config_ph, monkeypatch):
        """pH within range should skip dosing"""
        # Arrange
        mock_config_ph.set_ph_target(6.5, 0.3)  # Range: [6.2, 6.8]
        mock_config_ph.set_ph_pump_config()
        mock_config_ph.write_ph_log(6.5)  # pH perfect

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up = check_if_ph_adjustment_needed()

        # Assert - no adjustment needed
        assert needs_adjustment == False
        assert use_ph_up == None

    def test_no_ph_dosing_when_sensor_fails(self, monkeypatch, mock_config_ph):
        """pH sensor failure should prevent any dosing"""
        # Arrange - no log file = sensor failure
        mock_config_ph.set_ph_target(6.5, 0.3)
        mock_config_ph.set_ph_pump_config()
        # Don't write pH log - simulates sensor failure

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        # Act
        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up = check_if_ph_adjustment_needed()

        # Assert - should return (False, None) or similar safe default
        assert needs_adjustment == False
        assert use_ph_up == None
