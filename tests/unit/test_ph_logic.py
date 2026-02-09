"""
Test pH dosing decision logic based on pH sensor readings.

Critical tests:
- pH above upper threshold triggers pH down pump
- pH below safety minimum triggers pH up pump
- pH at or below target stops dosing
- Sensor failures prevent dosing (safety)
- Hysteresis: dosing continues between target and upper threshold when active
- Proportional dosing: dose factor scales with distance from target
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

        def set_ph_target(self, target, deadband, ph_min=4.0, ph_max=8.0):
            """Update pH target and deadband in config"""
            config = configparser.ConfigParser()
            config.read(self.config_path)
            if "pH" not in config:
                config.add_section("pH")
            config.set("pH", "ph_target", f"6.0, {target}")
            config.set("pH", "ph_deadband", f"0.2, {deadband}")
            config.set("pH", "ph_min", f"4.0, {ph_min}")
            config.set("pH", "ph_max", f"8.0, {ph_max}")
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


@pytest.fixture(autouse=True)
def reset_ph_hysteresis():
    """Reset hysteresis flag before each test to ensure isolation"""
    import src.ph_static as ph_mod
    ph_mod._ph_dosing_active = False
    yield
    ph_mod._ph_dosing_active = False


class TestpHLogic:
    """Test pH-driven dosing decisions"""

    def test_ph_down_when_ph_above_upper_threshold(self, mock_relay, mock_config_ph, monkeypatch):
        """pH above upper threshold (target + deadband) should activate pH down pump"""
        # Arrange: target=5.5, deadband=1.0 → upper threshold=6.5
        mock_config_ph.set_ph_target(5.5, 1.0)
        mock_config_ph.set_ph_pump_config()
        mock_config_ph.write_ph_log(7.0)  # pH above 6.5 upper threshold

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up, dose_factor = check_if_ph_adjustment_needed()

        # Assert
        assert needs_adjustment == True
        assert use_ph_up == False  # pH DOWN
        # pH=7.0, target=5.5, deadband=1.0 → distance=1.5, factor=0.5+0.5*(1.5/1.0)=1.25
        assert dose_factor == pytest.approx(1.25, abs=0.01)  # Above threshold = more than base

    def test_ph_up_only_at_safety_limit(self, mock_relay, mock_config_ph, monkeypatch):
        """pH UP only triggers at ph_min safety limit, not at target - deadband"""
        # Arrange: target=5.5, deadband=1.0, ph_min=4.0
        mock_config_ph.set_ph_target(5.5, 1.0)
        mock_config_ph.set_ph_pump_config()
        mock_config_ph.write_ph_log(3.5)  # Below ph_min=4.0

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up, dose_factor = check_if_ph_adjustment_needed()

        # Assert
        assert needs_adjustment == True
        assert use_ph_up == True  # pH UP (safety)
        assert dose_factor == 1.0  # Safety = always full dose

    def test_no_ph_dosing_when_at_target(self, mock_relay, mock_config_ph, monkeypatch):
        """pH at or below target should not dose (hysteresis inactive after reaching target)"""
        import src.ph_static as ph_mod

        # Arrange: target=5.5, deadband=1.0, pH=5.5 (at target)
        # Set hysteresis inactive (simulates having just completed a dosing cycle)
        ph_mod._ph_dosing_active = False
        mock_config_ph.set_ph_target(5.5, 1.0)
        mock_config_ph.set_ph_pump_config()
        mock_config_ph.write_ph_log(5.5)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up, _ = check_if_ph_adjustment_needed()

        # Assert - no adjustment needed
        assert needs_adjustment == False
        assert use_ph_up == None

    def test_no_ph_dosing_when_sensor_fails(self, monkeypatch, mock_config_ph):
        """pH sensor failure should prevent any dosing"""
        # Arrange - no log file = sensor failure
        mock_config_ph.set_ph_target(5.5, 1.0)
        mock_config_ph.set_ph_pump_config()
        # Don't write pH log - simulates sensor failure

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        # Act
        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up, _ = check_if_ph_adjustment_needed()

        # Assert - should return safe default
        assert needs_adjustment == False
        assert use_ph_up == None

    def test_ph_hysteresis_full_cycle(self, mock_relay, mock_config_ph, monkeypatch):
        """Full hysteresis cycle: trigger → continue in recovery → stop at target → no dose when inactive"""
        import src.ph_static as ph_mod

        mock_config_ph.set_ph_target(5.5, 1.0)  # upper threshold = 6.5
        mock_config_ph.set_ph_pump_config()

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)
        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        from src.ph_static import check_if_ph_adjustment_needed

        # Phase 1: pH above upper threshold → triggers dosing, sets _ph_dosing_active=True
        ph_mod._ph_dosing_active = False
        mock_config_ph.write_ph_log(6.8)
        needs, up, factor = check_if_ph_adjustment_needed()
        assert needs == True
        assert up == False
        assert factor > 1.0  # Above threshold = factor exceeds 1.0
        assert ph_mod._ph_dosing_active == True

        # Phase 2: pH dropping, still above target → continues dosing (hysteresis recovery)
        mock_config_ph.write_ph_log(6.0)  # between target (5.5) and upper (6.5)
        needs, up, factor = check_if_ph_adjustment_needed()
        assert needs == True
        assert up == False
        assert 0.5 < factor < 1.0  # Proportional: 0.5 + 0.5*(0.5/1.0) = 0.75
        assert ph_mod._ph_dosing_active == True

        # Phase 3: pH reaches target → stops dosing
        mock_config_ph.write_ph_log(5.5)
        needs, up, _ = check_if_ph_adjustment_needed()
        assert needs == False
        assert up == None
        assert ph_mod._ph_dosing_active == False

        # Phase 4: pH between target and upper threshold, but inactive → no dose
        mock_config_ph.write_ph_log(6.0)
        needs, up, _ = check_if_ph_adjustment_needed()
        assert needs == False
        assert up == None
        assert ph_mod._ph_dosing_active == False

    def test_ph_hysteresis_continues_above_target(self, mock_relay, mock_config_ph, monkeypatch):
        """When _ph_dosing_active=True and pH is between target and upper threshold, should continue dosing"""
        import src.ph_static as ph_mod

        # Arrange: active dosing sequence, pH between target and upper threshold
        ph_mod._ph_dosing_active = True
        mock_config_ph.set_ph_target(5.5, 1.0)  # upper threshold = 6.5
        mock_config_ph.set_ph_pump_config()
        mock_config_ph.write_ph_log(6.0)  # between 5.5 and 6.5

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)
        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up, dose_factor = check_if_ph_adjustment_needed()

        # Assert - should continue dosing DOWN with proportional factor
        assert needs_adjustment == True
        assert use_ph_up == False
        assert ph_mod._ph_dosing_active == True
        # pH=6.0, target=5.5, deadband=1.0 → distance=0.5, factor=0.5+0.5*(0.5/1.0)=0.75
        assert dose_factor == pytest.approx(0.75, abs=0.01)

    def test_ph_no_up_dosing_between_target_and_threshold(self, mock_relay, mock_config_ph, monkeypatch):
        """pH between target and upper threshold with inactive hysteresis should NOT trigger pH UP"""
        import src.ph_static as ph_mod

        ph_mod._ph_dosing_active = False
        mock_config_ph.set_ph_target(5.5, 1.0)  # upper=6.5
        mock_config_ph.set_ph_pump_config()
        mock_config_ph.write_ph_log(6.0)  # between target and upper, inactive

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)
        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up, _ = check_if_ph_adjustment_needed()

        # Assert - no dosing at all, definitely NOT pH UP
        assert needs_adjustment == False
        assert use_ph_up == None

    def test_ph_emergency_down_at_max(self, mock_relay, mock_config_ph, monkeypatch):
        """pH above ph_max safety limit should trigger emergency pH DOWN"""
        import src.ph_static as ph_mod
        ph_mod._ph_dosing_active = False

        mock_config_ph.set_ph_target(5.5, 1.0, ph_max=8.0)
        mock_config_ph.set_ph_pump_config()
        mock_config_ph.write_ph_log(8.5)  # above ph_max

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)
        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        from src.ph_static import check_if_ph_adjustment_needed
        needs_adjustment, use_ph_up, dose_factor = check_if_ph_adjustment_needed()

        assert needs_adjustment == True
        assert use_ph_up == False  # pH DOWN (emergency)
        assert dose_factor == 1.0  # Emergency = full dose

    def test_ph_proportional_dose_factor(self, mock_relay, mock_config_ph, monkeypatch):
        """Dose factor scales linearly: 1.0 at upper threshold, 0.5 at target"""
        import src.ph_static as ph_mod
        ph_mod._ph_dosing_active = True

        mock_config_ph.set_ph_target(5.5, 1.0)  # upper threshold = 6.5
        mock_config_ph.set_ph_pump_config()

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)
        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        from src.ph_static import check_if_ph_adjustment_needed

        # At upper threshold (6.5): factor = 1.0
        mock_config_ph.write_ph_log(6.5)
        _, _, factor = check_if_ph_adjustment_needed()
        assert factor == pytest.approx(1.0, abs=0.01)

        # Midpoint (6.0): factor = 0.75
        mock_config_ph.write_ph_log(6.0)
        _, _, factor = check_if_ph_adjustment_needed()
        assert factor == pytest.approx(0.75, abs=0.01)

        # Near target (5.6): factor ≈ 0.55
        mock_config_ph.write_ph_log(5.6)
        _, _, factor = check_if_ph_adjustment_needed()
        assert factor == pytest.approx(0.55, abs=0.01)

        # Just above target (5.51): factor ≈ 0.505
        mock_config_ph.write_ph_log(5.51)
        _, _, factor = check_if_ph_adjustment_needed()
        assert factor == pytest.approx(0.505, abs=0.01)

        # Above threshold (7.0): factor = 0.5 + 0.5*(1.5/1.0) = 1.25
        mock_config_ph.write_ph_log(7.0)
        _, _, factor = check_if_ph_adjustment_needed()
        assert factor == pytest.approx(1.25, abs=0.01)
