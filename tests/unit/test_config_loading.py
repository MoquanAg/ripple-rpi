"""
Test configuration loading and parsing.

Critical tests:
- Dual-value format (server, operational) parsing
- Missing config sections return safe defaults
- Malformed values handle gracefully
- Config hot-reload via Watchdog
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
import os
import configparser

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


class TestConfigLoading:
    """Test configuration file parsing and validation"""

    def test_dual_value_config_parsing(self, setup_test_environment, monkeypatch):
        """Operational value (second) should be used, not server default"""
        # Arrange
        config_file = setup_test_environment["config_dir"] / "device.conf"
        config = configparser.ConfigParser()
        config.read(config_file)
        if "EC" not in config:
            config.add_section("EC")
        config.set("EC", "ec_target", "1.0, 1.2")
        config.set("EC", "ec_deadband", "0.1, 0.2")
        with open(config_file, "w") as f:
            config.write(f)

        # Mock __file__ to point to temp location
        import src.nutrient_static as nutrient_module
        fake_file_path = str(setup_test_environment["config_dir"].parent / "src" / "nutrient_static.py")
        monkeypatch.setattr(nutrient_module, "__file__", fake_file_path)

        # Act
        from src.nutrient_static import get_ec_targets
        target, deadband = get_ec_targets()

        # Assert
        assert target == 1.2  # Operational value
        assert deadband == 0.2

    def test_all_dual_value_configs(self, setup_test_environment, monkeypatch):
        """All config functions should parse operational values"""
        # Arrange
        config_file = setup_test_environment["config_dir"] / "device.conf"
        config = configparser.ConfigParser()
        config.read(config_file)

        if "NutrientPump" not in config:
            config.add_section("NutrientPump")
        config.set("NutrientPump", "nutrient_pump_on_duration", "00:00:03, 00:00:05")
        config.set("NutrientPump", "nutrient_pump_wait_duration", "00:03:00, 00:05:00")
        config.set("NutrientPump", "nutrient_abc_ratio", "1:1:1, 1:1:0")

        if "EC" not in config:
            config.add_section("EC")
        config.set("EC", "ec_target", "1.0, 1.2")
        config.set("EC", "ec_deadband", "0.1, 0.2")

        with open(config_file, "w") as f:
            config.write(f)

        # Mock __file__ to point to temp location
        import src.nutrient_static as nutrient_module
        fake_file_path = str(setup_test_environment["config_dir"].parent / "src" / "nutrient_static.py")
        monkeypatch.setattr(nutrient_module, "__file__", fake_file_path)

        # Act
        from src.nutrient_static import get_nutrient_config, get_ec_targets, get_abc_ratio_from_config
        on, wait = get_nutrient_config()
        target, deadband = get_ec_targets()
        ratio = get_abc_ratio_from_config()

        # Assert - all should return operational (second) values
        assert on == "00:00:05"
        assert wait == "00:05:00"
        assert target == 1.2
        assert ratio == [1, 1, 0]

    def test_missing_nutrient_section_returns_defaults(self, setup_test_environment, monkeypatch):
        """Missing config should return safe defaults (zeros)"""
        # Arrange - create minimal config without NutrientPump section
        config_file = setup_test_environment["config_dir"] / "device.conf"
        config_file.write_text("[SYSTEM]\nfertigation_model = v2\n")

        # Mock __file__ to point to temp location
        import src.nutrient_static as nutrient_module
        fake_file_path = str(setup_test_environment["config_dir"].parent / "src" / "nutrient_static.py")
        monkeypatch.setattr(nutrient_module, "__file__", fake_file_path)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Act
        from src.nutrient_static import get_nutrient_config
        on, wait = get_nutrient_config()

        # Assert
        assert on == "00:00:00"  # Disabled
        assert wait == "00:00:00"

    def test_malformed_duration_returns_zero(self):
        """Invalid duration string should parse to 0 seconds"""
        # Act
        from src.nutrient_static import parse_duration

        # Assert
        assert parse_duration("invalid") == 0
        assert parse_duration("") == 0
        assert parse_duration("abc:def:ghi") == 0

    def test_single_value_config_handles_gracefully(self, setup_test_environment, monkeypatch):
        """Config with no comma should handle IndexError"""
        # Arrange - create config with single values (no comma)
        config_file = setup_test_environment["config_dir"] / "device.conf"
        config_file.write_text("""
[EC]
ec_target = 1.2
ec_deadband = 0.1
""")

        # Mock __file__ to point to temp location
        import src.nutrient_static as nutrient_module
        fake_file_path = str(setup_test_environment["config_dir"].parent / "src" / "nutrient_static.py")
        monkeypatch.setattr(nutrient_module, "__file__", fake_file_path)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Act - should not crash
        from src.nutrient_static import get_ec_targets
        target, deadband = get_ec_targets()

        # Assert - returns defaults due to error
        assert target == 1.0  # Default fallback
        assert deadband == 0.1

    def test_config_reload_updates_values(self, setup_test_environment, monkeypatch):
        """Modifying device.conf should reload values on next read"""
        # Arrange - initial config
        config_file = setup_test_environment["config_dir"] / "device.conf"
        config = configparser.ConfigParser()
        config.read(config_file)
        if "EC" not in config:
            config.add_section("EC")
        config.set("EC", "ec_target", "1.0, 1.2")
        config.set("EC", "ec_deadband", "0.1, 0.1")
        with open(config_file, "w") as f:
            config.write(f)

        # Mock __file__ to point to temp location
        import src.nutrient_static as nutrient_module
        fake_file_path = str(setup_test_environment["config_dir"].parent / "src" / "nutrient_static.py")
        monkeypatch.setattr(nutrient_module, "__file__", fake_file_path)

        from src.nutrient_static import get_ec_targets

        # Initial read
        target, _ = get_ec_targets()
        assert target == 1.2

        # Modify config
        config = configparser.ConfigParser()
        config.read(config_file)
        config.set("EC", "ec_target", "1.0, 1.5")
        with open(config_file, "w") as f:
            config.write(f)

        # Act - re-read (simulates hot-reload)
        target, _ = get_ec_targets()

        # Assert
        assert target == 1.5  # Updated value
