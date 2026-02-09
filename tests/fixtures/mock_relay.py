"""Mock Relay singleton for testing"""
from unittest.mock import MagicMock
import pytest

class MockRelay:
    """Mock relay board that tracks state without hardware"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.relay_states = {}
        return cls._instance

    def set_relay(self, device_name, state):
        """Set relay state (tracked in memory)"""
        self.relay_states[device_name] = state
        return True

    def get_relay_state(self, device_name):
        """Get relay state (check for stuck override first)"""
        stuck_relays = getattr(self, '_stuck_relays', {})
        if device_name in stuck_relays:
            return stuck_relays[device_name]
        return self.relay_states.get(device_name, False)

    def _force_stuck_state(self, device_name: str, stuck_state: bool):
        """Force relay to stay in specific state (for testing stuck relays)"""
        self._stuck_relays = getattr(self, '_stuck_relays', {})
        self._stuck_relays[device_name] = stuck_state

    # Add methods for specific devices
    def set_nutrient_pump(self, pump_id, state):
        device_name = f"NutrientPump{pump_id}"
        return self.set_relay(device_name, state)

    def set_ph_plus_pump(self, state):
        return self.set_relay("pHPlusPump", state)

    def set_ph_minus_pump(self, state):
        return self.set_relay("pHMinusPump", state)

    def set_sprinklers(self, state):
        return self.set_relay("Sprinkler", state)

    def set_valve_outside_to_tank(self, state):
        return self.set_relay("ValveOutsideToTank", state)

    def reset(self):
        """Reset all relay states (for test cleanup)"""
        self.relay_states = {}
        self._stuck_relays = {}

@pytest.fixture
def mock_relay(monkeypatch):
    """Fixture that mocks Relay singleton"""
    mock = MockRelay()
    mock.reset()

    # Wrap methods in MagicMock to track calls
    original_set_relay = mock.set_relay
    mock.set_relay = MagicMock(side_effect=original_set_relay)

    original_set_valve = mock.set_valve_outside_to_tank
    mock.set_valve_outside_to_tank = MagicMock(side_effect=original_set_valve)

    # Patch the Relay import wherever it's used
    monkeypatch.setattr("src.sensors.Relay.Relay", lambda: mock)

    return mock
