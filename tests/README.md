# Ripple Test Suite

Test suite for the Ripple fertigation control system. All tests run without hardware dependencies using mock fixtures.

## Quick Start

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/unit/test_startup_initialization.py -v

# Run with coverage
pip install pytest-cov
pytest tests/ --cov=src --cov-report=term --cov-report=html
```

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and pytest config
├── fixtures/
│   ├── mock_modbus.py       # Mock LuminaModbusClient
│   ├── mock_sensors.py      # Mock pH, EC, DO, WaterLevel
│   └── mock_relay.py        # Mock Relay singleton
└── unit/
    └── test_startup_initialization.py  # Startup sequence tests
```

## Test Categories

### Unit Tests (`tests/unit/`)

Fast tests with no external dependencies. Currently includes:

#### Startup Initialization Tests
- **MOQ-77 Fix Verification**: Nutrient schedule initialization on startup
- **Pump Safety**: All pumps OFF at reboot before activation
- **Config Respect**: Enable/disable flags honored
- **Controller Activation**: All subsystems initialize correctly

**Test Coverage:**
- `test_initialize_nutrient_schedule_called_on_startup` - MOQ-77 regression prevention
- `test_nutrient_pumps_set_off_before_schedule_init` - Safety verification
- `test_nutrient_disabled_when_duration_zero` - Config flag respect
- `test_ph_pumps_set_off_at_startup` - pH safety
- `test_water_level_monitoring_activation_method_exists` - Water level init
- `test_mixing_activation_method_exists` - Mixing pump init
- `test_sprinkler_activation_method_exists` - Sprinkler init

## Mock Fixtures

### MockRelay
Simulates relay board without hardware. Tracks relay states in memory.

```python
def test_example(mock_relay):
    mock_relay.set_nutrient_pump("A", True)
    assert mock_relay.get_relay_state("NutrientPumpA") == True
```

### MockEC / MockpH / MockDO / MockWaterLevel
Configurable sensor mocks returning fixed values.

```python
def test_example(mock_ec_sensor):
    mock_ec_sensor.value = 1.5  # Set EC to 1.5
    assert mock_ec_sensor.read() == 1.5
```

### MockModbusClient
Mock Modbus TCP client (no actual serial communication).

```python
def test_example(mock_modbus_client):
    mock_modbus_client.connect()
    assert mock_modbus_client.connected == True
```

## Test Environment

Tests use temporary directories for config, data, and logs (created via `setup_test_environment` fixture). No pollution of actual project directories.

## Notes

- All tests pass on Mac without RPi hardware
- Tests complete in ~6 seconds
- No actual Modbus server required (mocked)
- APScheduler disabled during tests to prevent background jobs
- Each test is independent with clean state

## Adding New Tests

1. Create test file in `tests/unit/` (name it `test_*.py`)
2. Import fixtures from `conftest.py`
3. Use `monkeypatch` to mock dependencies
4. Run `pytest` to verify

Example:

```python
def test_my_feature(mock_relay, monkeypatch):
    """Test description"""
    # Mock dependencies
    monkeypatch.setattr("module.function", mock_function)

    # Test your feature
    assert expected == actual
```

## CI/CD Integration

Tests are designed to run in CI environments:

```yaml
# .github/workflows/test.yml example
- name: Run tests
  run: |
    pip install -r requirements.txt
    pip install -r requirements-test.txt
    pytest tests/ -v
```

## Phase 1 Complete

✅ pytest infrastructure setup
✅ Mock fixtures for Relay, sensors, Modbus
✅ 10 startup initialization tests
✅ Config enable/disable flag tests
✅ Test coverage: ~35% of critical paths

Next: Phase 2 will add sensor-driven cycle tests, configuration parsing tests, and scheduler persistence tests.
