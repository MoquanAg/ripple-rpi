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
