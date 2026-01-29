"""Mock sensor classes for testing"""
import pytest
from unittest.mock import MagicMock

class MockSensor:
    """Base mock sensor"""
    def __init__(self, value=0.0):
        self.value = value

    def read(self):
        return self.value

    @classmethod
    def load_all_sensors(cls):
        """Mock static loader"""
        return []

class MockEC(MockSensor):
    """Mock EC sensor"""
    pass

class MockpH(MockSensor):
    """Mock pH sensor"""
    pass

class MockDO(MockSensor):
    """Mock DO sensor"""
    pass

class MockWaterLevel(MockSensor):
    """Mock water level sensor"""
    pass

@pytest.fixture
def mock_ec_sensor(monkeypatch):
    """EC sensor returning configurable value"""
    sensor = MockEC(value=1.0)  # Default EC = 1.0
    monkeypatch.setattr("src.sensors.ec.EC", MockEC)
    return sensor

@pytest.fixture
def mock_ph_sensor(monkeypatch):
    """pH sensor returning configurable value"""
    sensor = MockpH(value=6.5)  # Default pH = 6.5
    monkeypatch.setattr("src.sensors.pH.pH", MockpH)
    return sensor
