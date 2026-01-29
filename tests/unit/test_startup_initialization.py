"""
Test startup initialization sequence to prevent MOQ-77 type issues.

Critical tests:
- Verify all controller schedules initialize on startup
- Verify pumps are OFF before activation
- Verify config enable/disable flags are respected
- Verify nutrient auto-dosing initializes (MOQ-77)
"""
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime
import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


class TestNutrientInitialization:
    """Test nutrient system initialization - MOQ-77 fix verification"""

    def test_initialize_nutrient_schedule_called_on_startup(self, monkeypatch):
        """MOQ-77: Verify initialize_nutrient_schedule is called on system boot"""
        # Mock the function to track if it's called
        mock_init = MagicMock(return_value=True)
        monkeypatch.setattr(
            "src.nutrient_static.initialize_nutrient_schedule",
            mock_init
        )

        # Mock dependencies
        mock_relay = MagicMock()
        monkeypatch.setattr("src.sensors.Relay.Relay", lambda: mock_relay)
        monkeypatch.setattr("main.Relay", lambda: mock_relay)

        # Import after patching
        from main import RippleController

        # Create minimal controller
        controller = RippleController()

        # Call the activation method
        controller._activate_nutrient_pumps_on_startup()

        # Assert initialize_nutrient_schedule was called
        assert mock_init.call_count >= 1, "initialize_nutrient_schedule not called on startup"

    def test_nutrient_pumps_set_off_before_schedule_init(self, monkeypatch):
        """Verify pumps are explicitly set OFF before schedule initialization"""
        # Track relay calls
        relay_calls = []
        mock_relay = MagicMock()
        mock_relay.set_nutrient_pump = lambda pump_id, state: relay_calls.append((pump_id, state))

        monkeypatch.setattr("src.sensors.Relay.Relay", lambda: mock_relay)
        monkeypatch.setattr("main.Relay", lambda: mock_relay)

        # Mock initialize to not actually run
        monkeypatch.setattr("src.nutrient_static.initialize_nutrient_schedule", lambda: True)

        from main import RippleController
        controller = RippleController()
        controller._activate_nutrient_pumps_on_startup()

        # Verify pumps A, B, C were set to OFF
        assert ("A", False) in relay_calls, "Nutrient pump A not set OFF"
        assert ("B", False) in relay_calls, "Nutrient pump B not set OFF"
        assert ("C", False) in relay_calls, "Nutrient pump C not set OFF"

    def test_nutrient_disabled_when_duration_zero(self, monkeypatch):
        """Verify nutrient system disabled when duration = 0"""
        # Mock config functions to return zero duration
        def mock_get_nutrient_config():
            return ("00:00:00", "00:05:00")

        def mock_parse_duration(duration_str):
            if duration_str == "00:00:00":
                return 0
            return 300

        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", mock_get_nutrient_config)
        monkeypatch.setattr("src.nutrient_static.parse_duration", mock_parse_duration)

        # Mock logger to prevent errors
        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        from src.nutrient_static import initialize_nutrient_schedule
        result = initialize_nutrient_schedule()

        # Should return False (system disabled)
        assert result == False, "Nutrient system should be disabled when duration = 0"


class TestpHInitialization:
    """Test pH system initialization"""

    def test_ph_pumps_set_off_at_startup(self, monkeypatch):
        """Verify pH pumps are explicitly OFF after startup"""
        # Track relay calls
        ph_plus_calls = []
        ph_minus_calls = []

        mock_relay = MagicMock()
        mock_relay.set_ph_plus_pump = lambda state: ph_plus_calls.append(state)
        mock_relay.set_ph_minus_pump = lambda state: ph_minus_calls.append(state)

        monkeypatch.setattr("src.sensors.Relay.Relay", lambda: mock_relay)
        monkeypatch.setattr("main.Relay", lambda: mock_relay)

        from main import RippleController
        controller = RippleController()
        controller._activate_ph_pumps_on_startup()

        # Verify both pH pumps were set to OFF
        assert False in ph_plus_calls, "pH plus pump not set OFF"
        assert False in ph_minus_calls, "pH minus pump not set OFF"


class TestWaterLevelInitialization:
    """Test water level monitoring initialization"""

    def test_water_level_monitoring_activation_method_exists(self):
        """Verify _activate_water_level_monitoring_on_startup method exists"""
        from main import RippleController

        # Verify the activation method exists
        assert hasattr(RippleController, '_activate_water_level_monitoring_on_startup')
        assert callable(getattr(RippleController, '_activate_water_level_monitoring_on_startup'))


class TestMixingInitialization:
    """Test mixing pump initialization"""

    def test_mixing_activation_method_exists(self):
        """Verify _activate_mixing_pumps_on_startup method exists"""
        from main import RippleController

        # Verify the activation method exists
        assert hasattr(RippleController, '_activate_mixing_pumps_on_startup')
        assert callable(getattr(RippleController, '_activate_mixing_pumps_on_startup'))


class TestSprinklerInitialization:
    """Test sprinkler system initialization"""

    def test_sprinkler_activation_method_exists(self):
        """Verify _activate_sprinklers_on_startup method exists"""
        from main import RippleController

        # Verify the activation method exists
        assert hasattr(RippleController, '_activate_sprinklers_on_startup')
        assert callable(getattr(RippleController, '_activate_sprinklers_on_startup'))


class TestConfigRespect:
    """Test that config enable/disable flags are respected"""

    def test_nutrient_disabled_when_duration_zero(self, monkeypatch):
        """Verify nutrient system disabled when duration = 0"""
        # Mock config functions to return zero duration
        def mock_get_nutrient_config():
            return ("00:00:00", "00:05:00")

        def mock_parse_duration(duration_str):
            if duration_str == "00:00:00":
                return 0
            return 300

        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", mock_get_nutrient_config)
        monkeypatch.setattr("src.nutrient_static.parse_duration", mock_parse_duration)

        # Mock logger to prevent errors
        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        from src.nutrient_static import initialize_nutrient_schedule
        result = initialize_nutrient_schedule()

        # Should return False (system disabled)
        assert result == False


class TestSafetyMechanisms:
    """Test safety mechanisms at startup"""

    def test_nutrient_dosing_function_exists(self):
        """Verify nutrient dosing safety check function exists"""
        from src.nutrient_static import start_nutrient_pumps_static

        # The function should exist and be callable
        assert callable(start_nutrient_pumps_static)

    def test_initialize_nutrient_schedule_function_exists(self):
        """Verify initialize_nutrient_schedule function exists (MOQ-77)"""
        from src.nutrient_static import initialize_nutrient_schedule

        # The function should exist and be callable
        assert callable(initialize_nutrient_schedule)
