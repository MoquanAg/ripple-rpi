"""Shared pytest configuration and fixtures"""
import pytest
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# Import all fixtures
from tests.fixtures.mock_relay import mock_relay
from tests.fixtures.mock_sensors import (
    mock_ec_sensor,
    mock_ph_sensor,
    MockECConfigurable,
    MockpHConfigurable,
    MockWaterLevelConfigurable
)
from tests.fixtures.mock_modbus import mock_modbus_client

@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path, monkeypatch):
    """Setup clean test environment for each test"""
    # Create temporary directories
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    log_dir = tmp_path / "log"

    config_dir.mkdir()
    data_dir.mkdir()
    log_dir.mkdir()

    # Patch globals to use temp directories
    monkeypatch.setattr("src.globals.BASE_DIR", str(tmp_path / "src"))
    monkeypatch.setattr("src.globals.DATA_FOLDER_PATH", str(data_dir))
    monkeypatch.setattr("src.globals.LOG_FOLDER_PATH", str(log_dir))

    # Create minimal device.conf
    device_conf = config_dir / "device.conf"
    device_conf.write_text("""
[SYSTEM]
fertigation_model = v2

[NutrientPump]
nutrient_pump_on_duration = 00:00:05, 00:00:05
nutrient_pump_wait_duration = 00:05:00, 00:05:00
target_ec = 1.0, 1.2

[Sprinkler]
sprinkler_scheduling_enabled = true
sprinkler_on_at_startup = false

[WaterLevel]
check_interval = 00:05:00, 00:05:00

[Mixing]
mixing_duration = 00:00:10, 00:00:10
""")

    monkeypatch.setattr("src.globals.DEVICE_CONF_PATH", str(device_conf))

    # Disable actual scheduler to prevent background jobs
    monkeypatch.setattr("src.globals._scheduler_running", False)

    yield {
        "config_dir": config_dir,
        "data_dir": data_dir,
        "log_dir": log_dir
    }

@pytest.fixture
def mock_ec_sensor_configurable(monkeypatch):
    """Configurable EC sensor fixture"""
    sensor = MockECConfigurable(sensor_id=3)
    monkeypatch.setattr("src.sensors.ec.EC", lambda *args, **kwargs: sensor)
    return sensor

@pytest.fixture
def mock_ph_sensor_configurable(monkeypatch):
    """Configurable pH sensor fixture"""
    sensor = MockpHConfigurable(sensor_id=2)
    monkeypatch.setattr("src.sensors.pH.pH", lambda *args, **kwargs: sensor)
    return sensor

@pytest.fixture
def mock_water_level_sensor_configurable(monkeypatch):
    """Configurable water level sensor fixture"""
    sensor = MockWaterLevelConfigurable(sensor_id=5)
    monkeypatch.setattr("src.sensors.water_level.WaterLevel", lambda *args, **kwargs: sensor)
    return sensor

@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Config fixture with helper methods for modifying device.conf"""
    class ConfigHelper:
        def __init__(self, config_path):
            self.config_path = config_path

        def set_ec_target(self, target_ec, deadband=0.1):
            """Update target EC and deadband in config"""
            import configparser
            config = configparser.ConfigParser()
            config.read(self.config_path)
            if "EC" not in config:
                config.add_section("EC")
            config.set("EC", "ec_target", f"1.0, {target_ec}")
            config.set("EC", "ec_deadband", f"0.1, {deadband}")
            with open(self.config_path, "w") as f:
                config.write(f)

        def set_ph_target(self, min_ph, max_ph):
            """Update pH target range in config"""
            import configparser
            config = configparser.ConfigParser()
            config.read(self.config_path)
            if "pH" not in config:
                config.add_section("pH")
            config.set("pH", "ph_minimum_threshold", f"6.0, {min_ph}")
            config.set("pH", "ph_maximum_threshold", f"7.0, {max_ph}")
            with open(self.config_path, "w") as f:
                config.write(f)

        def set_water_level_target(self, min_level, max_level):
            """Update water level thresholds in config"""
            import configparser
            config = configparser.ConfigParser()
            config.read(self.config_path)
            if "WaterLevel" not in config:
                config.add_section("WaterLevel")
            config.set("WaterLevel", "minimum_level", f"20.0, {min_level}")
            config.set("WaterLevel", "maximum_level", f"90.0, {max_level}")
            with open(self.config_path, "w") as f:
                config.write(f)

        def set_abc_ratio(self, ratio):
            """Update nutrient ABC ratio in config"""
            import configparser
            config = configparser.ConfigParser()
            config.read(self.config_path)
            if "NutrientPump" not in config:
                config.add_section("NutrientPump")
            config.set("NutrientPump", "nutrient_abc_ratio", f"1:1:1, {ratio}")
            with open(self.config_path, "w") as f:
                config.write(f)

        def set_nutrient_duration(self, on, wait):
            """Update nutrient pump on and wait durations in config"""
            import configparser
            config = configparser.ConfigParser()
            config.read(self.config_path)
            if "NutrientPump" not in config:
                config.add_section("NutrientPump")
            config.set("NutrientPump", "nutrient_pump_on_duration", f"00:00:05, {on}")
            config.set("NutrientPump", "nutrient_pump_wait_duration", f"00:05:00, {wait}")
            with open(self.config_path, "w") as f:
                config.write(f)

    # Create config directory and device.conf
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    device_conf = config_dir / "device.conf"

    # Write minimal device.conf
    device_conf.write_text("""
[SYSTEM]
fertigation_model = v2

[NutrientPump]
nutrient_pump_on_duration = 00:00:05, 00:00:05
nutrient_pump_wait_duration = 00:05:00, 00:05:00
target_ec = 1.0, 1.2
nutrient_abc_ratio = 1:1:1, 1:1:1

[EC]
ec_target = 1.0, 1.2
ec_deadband = 0.1, 0.1

[Sprinkler]
sprinkler_scheduling_enabled = true
sprinkler_on_at_startup = false

[WaterLevel]
check_interval = 00:05:00, 00:05:00

[Mixing]
mixing_duration = 00:00:10, 00:00:10
""")

    monkeypatch.setattr("src.globals.DEVICE_CONF_PATH", str(device_conf))

    return ConfigHelper(str(device_conf))

@pytest.fixture
def mock_runtime_tracker(tmp_path):
    """Mock runtime tracker for testing"""
    from src.runtime_tracker import DosingRuntimeTracker
    tracker = DosingRuntimeTracker(storage_path=str(tmp_path / "runtime.json"))
    return tracker
