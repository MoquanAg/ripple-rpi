"""
Test nutrient dosing decision logic based on EC sensor readings.

Critical tests:
- EC below threshold triggers dosing
- EC at/above threshold skips dosing
- Sensor failures prevent dosing (safety)
- Deadband calculations
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


class TestECDecisionLogic:
    """Test EC-driven nutrient dosing decisions"""

    def test_dosing_needed_when_ec_below_threshold(self, mock_ec_sensor_configurable, mock_config, monkeypatch):
        """EC below (target - deadband) should trigger dosing"""
        # Arrange
        mock_ec_sensor_configurable.ec = 0.8

        # Mock logger
        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Mock get_ec_targets to return our test values
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.2, 0.1))

        # Act
        from src.nutrient_static import check_if_nutrient_dosing_needed
        result = check_if_nutrient_dosing_needed()

        # Assert
        assert result == True

    def test_no_dosing_when_ec_at_threshold(self, mock_ec_sensor_configurable, mock_config, monkeypatch):
        """EC exactly at threshold should NOT dose"""
        # Arrange
        mock_ec_sensor_configurable.ec = 1.1

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Mock get_ec_targets to return our test values
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.2, 0.1))

        # Act
        from src.nutrient_static import check_if_nutrient_dosing_needed
        result = check_if_nutrient_dosing_needed()

        # Assert
        assert result == False

    def test_no_dosing_when_ec_above_threshold(self, mock_ec_sensor_configurable, mock_config, monkeypatch):
        """EC above threshold is safe, no dosing needed"""
        # Arrange
        mock_ec_sensor_configurable.ec = 1.5

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Mock get_ec_targets to return our test values
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.2, 0.1))

        # Act
        from src.nutrient_static import check_if_nutrient_dosing_needed
        result = check_if_nutrient_dosing_needed()

        # Assert
        assert result == False

    def test_no_dosing_when_ec_sensor_unavailable(self, monkeypatch):
        """Sensor failure should prevent dosing (safe default)"""
        # Arrange: EC sensor returns None
        monkeypatch.setattr("src.sensors.ec.EC", lambda sensor_id: None)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Act
        from src.nutrient_static import check_if_nutrient_dosing_needed
        result = check_if_nutrient_dosing_needed()

        # Assert
        assert result == False

    def test_no_dosing_when_ec_reading_none(self, mock_ec_sensor_configurable, mock_config, monkeypatch):
        """Failed sensor read should prevent dosing"""
        # Arrange
        mock_ec_sensor_configurable.ec = None

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Mock get_ec_targets to return our test values
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.2, 0.1))

        # Act
        from src.nutrient_static import check_if_nutrient_dosing_needed
        result = check_if_nutrient_dosing_needed()

        # Assert
        assert result == False

    @pytest.mark.parametrize("target,deadband,ec_value,expected", [
        (1.2, 0.1, 0.8, True),   # EC < threshold
        (1.2, 0.1, 1.1, False),  # EC == threshold
        (1.2, 0.1, 1.5, False),  # EC > threshold
        (1.5, 0.2, 1.2, True),   # Different deadband, low
        (1.0, 0.05, 0.94, True), # Small deadband, low
    ])
    def test_deadband_calculation(self, mock_ec_sensor_configurable, mock_config, monkeypatch,
                                   target, deadband, ec_value, expected):
        """Verify threshold = target - deadband"""
        # Arrange
        mock_ec_sensor_configurable.ec = ec_value

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Mock get_ec_targets to return our test values
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (target, deadband))

        # Act
        from src.nutrient_static import check_if_nutrient_dosing_needed
        result = check_if_nutrient_dosing_needed()

        # Assert
        assert result == expected


class TestPumpControlABCRatio:
    """Test pump activation based on ABC ratio configuration"""

    def test_pumps_start_with_ratio_1_1_0(self, mock_ec_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """ABC ratio 1:1:0 should activate pumps A and B only"""
        # Arrange
        mock_ec_sensor_configurable.ec = 0.8  # Low EC
        mock_config.set_abc_ratio("1:1:0")
        mock_config.set_ec_target(1.2, 0.1)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Mock scheduler to prevent actual scheduling
        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Mock config functions
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.2, 0.1))
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [1, 1, 0])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        # Act
        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        # Assert
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        assert ("NutrientPumpA", True) in relay_calls
        assert ("NutrientPumpB", True) in relay_calls
        # Pump C should not be turned on
        pump_c_on_calls = [call for call in relay_calls if call == ("NutrientPumpC", True)]
        assert len(pump_c_on_calls) == 0

    def test_pumps_start_with_ratio_1_1_1(self, mock_ec_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """ABC ratio 1:1:1 should activate all three pumps"""
        # Arrange
        mock_ec_sensor_configurable.ec = 0.8
        mock_config.set_abc_ratio("1:1:1")
        mock_config.set_ec_target(1.2, 0.1)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Mock config functions
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.2, 0.1))
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [1, 1, 1])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        # Act
        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        # Assert
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        assert ("NutrientPumpA", True) in relay_calls
        assert ("NutrientPumpB", True) in relay_calls
        assert ("NutrientPumpC", True) in relay_calls

    def test_abc_ratio_2_1_0_activates_correct_pumps(self, mock_ec_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """Ratio uses >0 as boolean, not duration multiplier"""
        # Arrange
        mock_ec_sensor_configurable.ec = 0.8
        mock_config.set_abc_ratio("2:1:0")
        mock_config.set_ec_target(1.2, 0.1)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Mock config functions
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.2, 0.1))
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [2, 1, 0])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        # Act
        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        # Assert
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        assert ("NutrientPumpA", True) in relay_calls
        assert ("NutrientPumpB", True) in relay_calls
        pump_c_on_calls = [call for call in relay_calls if call == ("NutrientPumpC", True)]
        assert len(pump_c_on_calls) == 0

    def test_no_pumps_start_when_ec_adequate(self, mock_ec_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """High EC should skip dosing even with valid ABC ratio"""
        # Arrange
        mock_ec_sensor_configurable.ec = 1.5  # High EC
        mock_config.set_abc_ratio("1:1:1")
        mock_config.set_ec_target(1.2, 0.1)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Mock config functions
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.2, 0.1))
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [1, 1, 1])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        # Act
        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        # Assert - no pumps should have been turned ON
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        pump_on_calls = [call for call in relay_calls if call[1] == True]
        assert len(pump_on_calls) == 0

    def test_all_pumps_stop(self, mock_relay, monkeypatch):
        """Stop should turn off all pumps regardless of which were on"""
        # Arrange
        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Pre-start some pumps
        mock_relay.set_relay("NutrientPumpA", True)
        mock_relay.set_relay("NutrientPumpC", True)

        # Act
        from src.nutrient_static import stop_nutrient_pumps_static
        stop_nutrient_pumps_static()

        # Assert
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        # Should see all three pumps set to False
        assert ("NutrientPumpA", False) in relay_calls
        assert ("NutrientPumpB", False) in relay_calls
        assert ("NutrientPumpC", False) in relay_calls
