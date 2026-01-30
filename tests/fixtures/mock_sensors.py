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

class MockECConfigurable(MockSensor):
    """Mock EC sensor with configurable value"""
    def __init__(self, sensor_id):
        super().__init__(value=1.0)
        self.ec = 1.0  # Default EC value

    def read(self):
        return self.ec

class MockpHConfigurable(MockSensor):
    """Mock pH sensor with configurable value"""
    def __init__(self, sensor_id):
        super().__init__(value=6.5)
        self.ph = 6.5  # Default pH value

    def read(self):
        return self.ph

class MockWaterLevelConfigurable(MockSensor):
    """Mock water level sensor with configurable value"""
    def __init__(self, sensor_id):
        super().__init__(value=80.0)
        self.level = 80.0  # Default level %

    def read(self):
        return self.level

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
