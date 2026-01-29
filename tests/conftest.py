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
from tests.fixtures.mock_sensors import mock_ec_sensor, mock_ph_sensor
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
