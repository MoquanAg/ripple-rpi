"""Mock LuminaModbusClient for testing"""
import pytest
from unittest.mock import MagicMock

class MockModbusClient:
    """Mock Modbus client that simulates TCP connection"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.connected = False
            cls._instance.responses = {}
        return cls._instance

    def connect(self, host='127.0.0.1', port=8888):
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False

    def read_holding_registers(self, address, count, unit):
        """Return mock sensor data"""
        return self.responses.get((address, count, unit), [0] * count)

    def write_coil(self, address, value, unit):
        """Mock relay control"""
        return True

@pytest.fixture
def mock_modbus_client(monkeypatch):
    """Fixture that mocks LuminaModbusClient singleton"""
    mock = MockModbusClient()
    monkeypatch.setattr("src.lumina_modbus_client.LuminaModbusClient", lambda: mock)
    return mock
