# Phase 2 Testing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement 34 comprehensive tests for sensor-driven control logic, configuration parsing, and scheduler persistence to achieve 60-70% coverage of critical paths.

**Architecture:** Build on Phase 1 test infrastructure with enhanced fixtures for configurable sensors and config files. Tests validate EC/pH/water-level decision logic, pump control, APScheduler job persistence, and dual-value config parsing. All tests run without hardware dependencies using mocks.

**Tech Stack:** pytest, pytest-mock, freezegun (time mocking), APScheduler, configparser

---

## Task 1: Enhance Mock Fixtures

**Files:**
- Modify: `tests/fixtures/mock_sensors.py`
- Modify: `tests/conftest.py`

**Step 1: Add configurable EC sensor to mock_sensors.py**

Add after the existing MockWaterLevel class:

```python
class MockECConfigurable(MockSensor):
    """Mock EC sensor with configurable value"""
    def __init__(self, sensor_id):
        super().__init__(value=1.0)
        self.ec = 1.0  # Default EC value

    def read(self):
        return self.ec
```

**Step 2: Add configurable pH sensor to mock_sensors.py**

```python
class MockpHConfigurable(MockSensor):
    """Mock pH sensor with configurable value"""
    def __init__(self, sensor_id):
        super().__init__(value=6.5)
        self.ph = 6.5  # Default pH value

    def read(self):
        return self.ph
```

**Step 3: Add configurable water level sensor to mock_sensors.py**

```python
class MockWaterLevelConfigurable(MockSensor):
    """Mock water level sensor with configurable value"""
    def __init__(self, sensor_id):
        super().__init__(value=80.0)
        self.level = 80.0  # Default level %

    def read(self):
        return self.level
```

**Step 4: Add new fixtures to conftest.py**

Add after existing fixtures:

```python
from tests.fixtures.mock_sensors import MockECConfigurable, MockpHConfigurable, MockWaterLevelConfigurable

@pytest.fixture
def mock_ec_sensor_configurable(monkeypatch):
    """EC sensor with configurable value"""
    sensor = MockECConfigurable("ec_main")
    monkeypatch.setattr("src.sensors.ec.EC", lambda sensor_id: sensor)
    return sensor

@pytest.fixture
def mock_ph_sensor_configurable(monkeypatch):
    """pH sensor with configurable value"""
    sensor = MockpHConfigurable("ph_main")
    monkeypatch.setattr("src.sensors.pH.pH", lambda sensor_id: sensor)
    return sensor

@pytest.fixture
def mock_water_level_sensor_configurable(monkeypatch):
    """Water level sensor with configurable value"""
    sensor = MockWaterLevelConfigurable("water_level_main")
    monkeypatch.setattr("src.sensors.water_level.WaterLevel", lambda sensor_id: sensor)
    return sensor

@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Configurable device.conf for testing"""
    config_file = tmp_path / "device.conf"

    class ConfigHelper:
        def __init__(self, config_path):
            self.config_path = config_path

        def set_ec_target(self, target, deadband):
            """Set EC target and deadband"""
            self.config_path.write_text(f"""
[EC]
ec_target = 1.0, {target}
ec_deadband = 0.1, {deadband}

[NutrientPump]
nutrient_pump_on_duration = 00:00:05, 00:00:05
nutrient_pump_wait_duration = 00:05:00, 00:05:00
abc_ratio = 1:1:0, 1:1:0
""")

        def set_ph_target(self, target, deadband):
            """Set pH target and deadband"""
            self.config_path.write_text(f"""
[pH]
ph_target = 6.5, {target}
ph_deadband = 0.3, {deadband}
""")

        def set_water_level_target(self, target):
            """Set water level target"""
            self.config_path.write_text(f"""
[WaterLevel]
target_level = 80, {target}
""")

        def set_abc_ratio(self, ratio):
            """Set ABC nutrient ratio"""
            content = self.config_path.read_text() if self.config_path.exists() else ""
            if "[NutrientPump]" in content:
                # Update existing
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if line.startswith('abc_ratio'):
                        lines[i] = f"abc_ratio = 1:1:0, {ratio}"
                self.config_path.write_text('\n'.join(lines))
            else:
                self.config_path.write_text(f"""
[NutrientPump]
abc_ratio = 1:1:0, {ratio}
nutrient_pump_on_duration = 00:00:05, 00:00:05
nutrient_pump_wait_duration = 00:05:00, 00:05:00

[EC]
ec_target = 1.0, 1.2
ec_deadband = 0.1, 0.1
""")

        def set_nutrient_duration(self, on, wait):
            """Set nutrient pump durations"""
            self.config_path.write_text(f"""
[NutrientPump]
nutrient_pump_on_duration = 00:00:05, {on}
nutrient_pump_wait_duration = 00:05:00, {wait}
abc_ratio = 1:1:0, 1:1:1

[EC]
ec_target = 1.0, 1.2
ec_deadband = 0.1, 0.1
""")

    helper = ConfigHelper(config_file)
    monkeypatch.setattr("src.globals.DEVICE_CONF_PATH", str(config_file))

    # Set default config
    helper.set_ec_target(1.2, 0.1)

    return helper
```

**Step 5: Run existing tests to verify fixtures don't break**

Run: `pytest tests/unit/test_startup_initialization.py -v`
Expected: All 10 tests PASS

**Step 6: Commit fixture enhancements**

```bash
git add tests/fixtures/mock_sensors.py tests/conftest.py
git commit -m "test: add configurable sensor and config fixtures for Phase 2

- Add MockECConfigurable, MockpHConfigurable, MockWaterLevelConfigurable
- Add mock_config fixture with helper methods for EC, pH, water level
- Support dual-value config format testing

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 2: EC Decision Logic Tests (6 tests)

**Files:**
- Create: `tests/unit/test_nutrient_logic.py`

**Step 1: Create test file with imports**

```python
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
        mock_config.set_ec_target(1.2, 0.1)  # threshold = 1.1

        # Mock logger
        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Act
        from src.nutrient_static import check_if_nutrient_dosing_needed
        result = check_if_nutrient_dosing_needed()

        # Assert
        assert result == True

    def test_no_dosing_when_ec_at_threshold(self, mock_ec_sensor_configurable, mock_config, monkeypatch):
        """EC exactly at threshold should NOT dose"""
        # Arrange
        mock_ec_sensor_configurable.ec = 1.1
        mock_config.set_ec_target(1.2, 0.1)  # threshold = 1.1

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Act
        from src.nutrient_static import check_if_nutrient_dosing_needed
        result = check_if_nutrient_dosing_needed()

        # Assert
        assert result == False

    def test_no_dosing_when_ec_above_threshold(self, mock_ec_sensor_configurable, mock_config, monkeypatch):
        """EC above threshold is safe, no dosing needed"""
        # Arrange
        mock_ec_sensor_configurable.ec = 1.5
        mock_config.set_ec_target(1.2, 0.1)  # threshold = 1.1

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

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
        mock_config.set_ec_target(1.2, 0.1)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

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
        mock_config.set_ec_target(target, deadband)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Act
        from src.nutrient_static import check_if_nutrient_dosing_needed
        result = check_if_nutrient_dosing_needed()

        # Assert
        assert result == expected
```

**Step 2: Run tests to verify they work**

Run: `pytest tests/unit/test_nutrient_logic.py::TestECDecisionLogic -v`
Expected: 6 tests PASS

**Step 3: Commit EC decision tests**

```bash
git add tests/unit/test_nutrient_logic.py
git commit -m "test: add EC decision logic tests (6 tests)

Validates EC-driven nutrient dosing decisions:
- Dose when EC below threshold
- Skip when EC at/above threshold
- Safety: skip when sensor fails
- Deadband calculation with parametrized tests

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Pump Control & ABC Ratio Tests (5 tests)

**Files:**
- Modify: `tests/unit/test_nutrient_logic.py`

**Step 1: Add pump control test class**

Add to test_nutrient_logic.py after TestECDecisionLogic:

```python
class TestPumpControlABCRatio:
    """Test pump activation based on ABC ratio configuration"""

    def test_pumps_start_with_ratio_1_1_0(self, mock_ec_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """ABC ratio 1:1:0 should activate pumps A and B only"""
        # Arrange
        mock_ec_sensor_configurable.ec = 0.8  # Low EC
        mock_config.set_abc_ratio("1:1:0")

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Mock scheduler to prevent actual scheduling
        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

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

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

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

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

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

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

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
```

**Step 2: Run pump control tests**

Run: `pytest tests/unit/test_nutrient_logic.py::TestPumpControlABCRatio -v`
Expected: 5 tests PASS

**Step 3: Commit pump control tests**

```bash
git add tests/unit/test_nutrient_logic.py
git commit -m "test: add pump control and ABC ratio tests (5 tests)

Validates nutrient pump activation logic:
- ABC ratio 1:1:0 activates A and B
- ABC ratio 1:1:1 activates all three
- ABC ratio uses >0 as boolean flag
- High EC skips all pump activation
- Stop turns off all pumps

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 4: End-to-End Cycle Flow Tests (6 tests)

**Files:**
- Modify: `tests/unit/test_nutrient_logic.py`

**Step 1: Add cycle timing test class**

Add to test_nutrient_logic.py:

```python
from freezegun import freeze_time
from datetime import datetime, timedelta


class TestEndToEndCycleFlow:
    """Test complete nutrient dosing cycles with timing"""

    def test_pumps_run_for_configured_duration(self, mock_ec_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """Stop job should be scheduled at start + on_duration"""
        # Arrange
        mock_ec_sensor_configurable.ec = 0.8
        mock_config.set_nutrient_duration(on="00:00:05", wait="00:05:00")

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Act
        with freeze_time("2026-01-29 12:00:00") as frozen_time:
            from src.nutrient_static import start_nutrient_pumps_static
            start_nutrient_pumps_static()

            # Assert - stop should be scheduled 5 seconds later
            expected_time = datetime(2026, 1, 29, 12, 0, 5)
            mock_scheduler.add_job.assert_called()
            call_args = mock_scheduler.add_job.call_args
            assert call_args[1]['id'] == 'nutrient_stop'
            # Verify run_date is approximately 5 seconds from now
            run_date = call_args[1]['run_date']
            assert abs((run_date - expected_time).total_seconds()) < 1

    def test_next_cycle_scheduled_after_wait(self, mock_relay, mock_config, monkeypatch):
        """After stop, next start should be scheduled at stop + wait_duration"""
        # Arrange
        mock_config.set_nutrient_duration(on="00:00:05", wait="00:05:00")

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Act
        with freeze_time("2026-01-29 12:00:00") as frozen_time:
            from src.nutrient_static import stop_nutrient_pumps_static
            stop_nutrient_pumps_static()

            # Assert - start should be scheduled 5 minutes later
            expected_time = datetime(2026, 1, 29, 12, 5, 0)
            mock_scheduler.add_job.assert_called()
            call_args = mock_scheduler.add_job.call_args
            assert call_args[1]['id'] == 'nutrient_start'
            run_date = call_args[1]['run_date']
            assert abs((run_date - expected_time).total_seconds()) < 1

    def test_skip_dosing_when_ec_adequate_schedule_next(self, mock_ec_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """When EC adequate, skip dosing but schedule next check"""
        # Arrange
        mock_ec_sensor_configurable.ec = 1.5  # High EC
        mock_config.set_nutrient_duration(on="00:00:05", wait="00:05:00")

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        # Assert - pumps should not start
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        pump_on_calls = [call for call in relay_calls if call[1] == True]
        assert len(pump_on_calls) == 0

        # But next cycle should be scheduled
        mock_scheduler.add_job.assert_called()

    def test_complete_nutrient_cycle(self, mock_ec_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """Test full cycle: start → stop → next start"""
        # Arrange
        mock_ec_sensor_configurable.ec = 0.8
        mock_config.set_nutrient_duration(on="00:00:05", wait="00:05:00")

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Act
        with freeze_time("2026-01-29 12:00:00") as frozen_time:
            from src.nutrient_static import start_nutrient_pumps_static, stop_nutrient_pumps_static

            # 1. Start cycle
            start_nutrient_pumps_static()
            relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
            assert ("NutrientPumpA", True) in relay_calls

            # 2. Advance time and stop
            mock_relay.reset_mock()
            frozen_time.tick(delta=timedelta(seconds=5))
            stop_nutrient_pumps_static()
            relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
            assert ("NutrientPumpA", False) in relay_calls

            # 3. Verify next cycle scheduled
            call_args = mock_scheduler.add_job.call_args
            assert call_args[1]['id'] == 'nutrient_start'

    def test_no_scheduling_when_duration_zero(self, mock_ec_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """on_duration=0 should disable the system"""
        # Arrange
        mock_ec_sensor_configurable.ec = 0.8
        mock_config.set_nutrient_duration(on="00:00:00", wait="00:05:00")

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        # Assert - no jobs should be scheduled
        assert mock_scheduler.add_job.call_count == 0

    def test_wait_duration_zero_no_next_cycle(self, mock_relay, mock_config, monkeypatch):
        """wait_duration=0 should not schedule next cycle"""
        # Arrange
        mock_config.set_nutrient_duration(on="00:00:05", wait="00:00:00")

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.nutrient_static import stop_nutrient_pumps_static
        stop_nutrient_pumps_static()

        # Assert - no next cycle scheduled
        assert mock_scheduler.add_job.call_count == 0
```

**Step 2: Run cycle flow tests**

Run: `pytest tests/unit/test_nutrient_logic.py::TestEndToEndCycleFlow -v`
Expected: 6 tests PASS

**Step 3: Commit cycle flow tests**

```bash
git add tests/unit/test_nutrient_logic.py
git commit -m "test: add end-to-end cycle flow tests (6 tests)

Validates complete nutrient dosing cycles:
- Stop scheduled at start + on_duration
- Next start scheduled at stop + wait_duration
- EC adequate skips dosing but schedules next check
- Complete cycle with time advancement
- Duration=0 disables scheduling

Uses freezegun for time mocking.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Configuration Loading Tests (6 tests)

**Files:**
- Create: `tests/unit/test_config_loading.py`

**Step 1: Create config loading test file**

```python
"""
Test configuration loading and parsing.

Critical tests:
- Dual-value format (server, operational) parsing
- Missing config sections return safe defaults
- Malformed values handle gracefully
- Config hot-reload via Watchdog
"""
import pytest
from unittest.mock import MagicMock
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


class TestConfigLoading:
    """Test configuration file parsing and validation"""

    def test_dual_value_config_parsing(self, tmp_path, monkeypatch):
        """Operational value (second) should be used, not server default"""
        # Arrange
        config_file = tmp_path / "device.conf"
        config_file.write_text("""
[EC]
ec_target = 1.0, 1.2
ec_deadband = 0.1, 0.2
""")
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config.__globals__['__file__']",
                           str(config_file.parent.parent / "src" / "nutrient_static.py"))

        # Mock the config path
        import os
        original_abspath = os.path.abspath
        def mock_abspath(path):
            if "nutrient_static.py" in path:
                return str(config_file.parent.parent / "src" / "nutrient_static.py")
            return original_abspath(path)
        monkeypatch.setattr("os.path.abspath", mock_abspath)

        # Act
        from src.nutrient_static import get_ec_targets
        target, deadband = get_ec_targets()

        # Assert
        assert target == 1.2  # Operational value
        assert deadband == 0.2

    def test_all_dual_value_configs(self, tmp_path, monkeypatch):
        """All config functions should parse operational values"""
        # Arrange
        config_file = tmp_path / "device.conf"
        config_file.write_text("""
[NutrientPump]
nutrient_pump_on_duration = 00:00:03, 00:00:05
nutrient_pump_wait_duration = 00:03:00, 00:05:00
abc_ratio = 1:1:1, 1:1:0

[EC]
ec_target = 1.0, 1.2
ec_deadband = 0.1, 0.2
""")

        import os
        original_abspath = os.path.abspath
        def mock_abspath(path):
            if "nutrient_static.py" in path:
                return str(config_file.parent.parent / "src" / "nutrient_static.py")
            return original_abspath(path)
        monkeypatch.setattr("os.path.abspath", mock_abspath)

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

    def test_missing_nutrient_section_returns_defaults(self, tmp_path, monkeypatch):
        """Missing config should return safe defaults (zeros)"""
        # Arrange
        config_file = tmp_path / "device.conf"
        config_file.write_text("[SYSTEM]\n")  # No NutrientPump section

        import os
        original_abspath = os.path.abspath
        def mock_abspath(path):
            if "nutrient_static.py" in path:
                return str(config_file.parent.parent / "src" / "nutrient_static.py")
            return original_abspath(path)
        monkeypatch.setattr("os.path.abspath", mock_abspath)

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
        assert parse_duration("99:99:99") == 0
        assert parse_duration("") == 0
        assert parse_duration("abc:def:ghi") == 0

    def test_single_value_config_handles_gracefully(self, tmp_path, monkeypatch):
        """Config with no comma should handle IndexError"""
        # Arrange
        config_file = tmp_path / "device.conf"
        config_file.write_text("""
[EC]
ec_target = 1.2
ec_deadband = 0.1
""")

        import os
        original_abspath = os.path.abspath
        def mock_abspath(path):
            if "nutrient_static.py" in path:
                return str(config_file.parent.parent / "src" / "nutrient_static.py")
            return original_abspath(path)
        monkeypatch.setattr("os.path.abspath", mock_abspath)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)

        # Act - should not crash
        from src.nutrient_static import get_ec_targets
        target, deadband = get_ec_targets()

        # Assert - returns defaults due to error
        assert target == 1.0  # Default fallback
        assert deadband == 0.1

    def test_config_reload_updates_values(self, tmp_path, monkeypatch):
        """Modifying device.conf should reload values on next read"""
        # Arrange
        config_file = tmp_path / "device.conf"
        config_file.write_text("""
[EC]
ec_target = 1.0, 1.2
ec_deadband = 0.1, 0.1
""")

        import os
        original_abspath = os.path.abspath
        def mock_abspath(path):
            if "nutrient_static.py" in path:
                return str(config_file.parent.parent / "src" / "nutrient_static.py")
            return original_abspath(path)
        monkeypatch.setattr("os.path.abspath", mock_abspath)

        from src.nutrient_static import get_ec_targets

        # Initial read
        target, _ = get_ec_targets()
        assert target == 1.2

        # Modify config
        config_file.write_text("""
[EC]
ec_target = 1.0, 1.5
ec_deadband = 0.1, 0.1
""")

        # Act - re-read (simulates hot-reload)
        target, _ = get_ec_targets()

        # Assert
        assert target == 1.5  # Updated value
```

**Step 2: Run config loading tests**

Run: `pytest tests/unit/test_config_loading.py -v`
Expected: 6 tests PASS

**Step 3: Commit config loading tests**

```bash
git add tests/unit/test_config_loading.py
git commit -m "test: add configuration loading tests (6 tests)

Validates config parsing and error handling:
- Dual-value format extracts operational value
- Multiple config functions parse correctly
- Missing sections return safe defaults
- Malformed durations return 0 (safe)
- Single-value configs handle gracefully
- Config hot-reload updates values

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Scheduler Persistence Tests (5 tests)

**Files:**
- Create: `tests/unit/test_scheduler_persistence.py`

**Step 1: Create scheduler persistence test file**

```python
"""
Test APScheduler job persistence via SQLite jobstore.

Critical tests:
- Jobs written to SQLite file
- Jobs survive scheduler restart
- Job replacement with replace_existing
- Multiple job types coexist
- Scheduling lock prevents race conditions
"""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
import sys
from pathlib import Path
import threading

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


def create_scheduler_with_sqlite(jobstore_path):
    """Helper to create scheduler with SQLite jobstore"""
    jobstores = {
        'default': SQLAlchemyJobStore(url=f'sqlite:///{jobstore_path}')
    }
    scheduler = BackgroundScheduler(jobstores=jobstores)
    scheduler.start()
    return scheduler


class TestSchedulerPersistence:
    """Test APScheduler SQLite persistence"""

    def test_jobs_persist_to_sqlite(self, tmp_path, monkeypatch):
        """Scheduled jobs should be written to SQLite file"""
        # Arrange
        jobstore_path = tmp_path / "jobs.sqlite"
        scheduler = create_scheduler_with_sqlite(jobstore_path)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: scheduler)

        # Act
        from src.nutrient_static import schedule_next_nutrient_cycle_static
        schedule_next_nutrient_cycle_static()

        # Assert - job exists in scheduler
        job = scheduler.get_job('nutrient_start')
        assert job is not None

        # SQLite file was created
        assert jobstore_path.exists()

        # Cleanup
        scheduler.shutdown()

    def test_jobs_reload_after_restart(self, tmp_path):
        """Jobs should be restored from SQLite after restart"""
        # Arrange
        jobstore_path = tmp_path / "jobs.sqlite"

        # 1. Create scheduler, add job
        scheduler1 = create_scheduler_with_sqlite(jobstore_path)
        scheduler1.add_job(
            lambda: None,  # Dummy function
            'date',
            run_date=datetime(2026, 1, 29, 15, 0, 0),
            id='nutrient_start'
        )
        scheduler1.shutdown()

        # 2. Create new scheduler (simulates restart)
        scheduler2 = create_scheduler_with_sqlite(jobstore_path)

        # 3. Job should be restored
        job = scheduler2.get_job('nutrient_start')
        assert job is not None
        assert job.id == 'nutrient_start'

        # Cleanup
        scheduler2.shutdown()

    def test_job_replacement_updates_existing(self, tmp_path):
        """replace_existing=True should update job, not duplicate"""
        # Arrange
        jobstore_path = tmp_path / "jobs.sqlite"
        scheduler = create_scheduler_with_sqlite(jobstore_path)

        # Schedule nutrient_stop at T1
        scheduler.add_job(
            lambda: None,
            'date',
            run_date=datetime(2026, 1, 29, 12, 0, 5),
            id='nutrient_stop',
            replace_existing=True
        )

        # Schedule nutrient_stop at T2 (should replace)
        scheduler.add_job(
            lambda: None,
            'date',
            run_date=datetime(2026, 1, 29, 12, 0, 10),
            id='nutrient_stop',
            replace_existing=True
        )

        # Assert - only one job should exist
        jobs = [j for j in scheduler.get_jobs() if j.id == 'nutrient_stop']
        assert len(jobs) == 1
        assert jobs[0].next_run_time == datetime(2026, 1, 29, 12, 0, 10)

        # Cleanup
        scheduler.shutdown()

    def test_multiple_jobs_persist_independently(self, tmp_path):
        """Different job types should persist without interference"""
        # Arrange
        jobstore_path = tmp_path / "jobs.sqlite"
        scheduler = create_scheduler_with_sqlite(jobstore_path)

        # Add multiple jobs
        scheduler.add_job(
            lambda: None,
            'date',
            run_date=datetime.now() + timedelta(minutes=5),
            id='nutrient_start'
        )
        scheduler.add_job(
            lambda: None,
            'date',
            run_date=datetime.now() + timedelta(minutes=10),
            id='ph_start'
        )

        scheduler.shutdown()

        # Restart and verify all jobs restored
        scheduler2 = create_scheduler_with_sqlite(jobstore_path)
        assert scheduler2.get_job('nutrient_start') is not None
        assert scheduler2.get_job('ph_start') is not None

        # Cleanup
        scheduler2.shutdown()

    def test_scheduling_lock_prevents_duplicates(self, tmp_path, monkeypatch):
        """Concurrent scheduling calls should not create duplicate jobs"""
        # Arrange
        jobstore_path = tmp_path / "jobs.sqlite"
        scheduler = create_scheduler_with_sqlite(jobstore_path)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: scheduler)

        # Act - rapidly call from threads
        from src.nutrient_static import schedule_next_nutrient_cycle_static

        threads = []
        for i in range(10):
            t = threading.Thread(target=schedule_next_nutrient_cycle_static)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Assert - only one nutrient_start job should exist
        jobs = [j for j in scheduler.get_jobs() if j.id == 'nutrient_start']
        assert len(jobs) == 1

        # Cleanup
        scheduler.shutdown()
```

**Step 2: Run scheduler persistence tests**

Run: `pytest tests/unit/test_scheduler_persistence.py -v`
Expected: 5 tests PASS

**Step 3: Commit scheduler persistence tests**

```bash
git add tests/unit/test_scheduler_persistence.py
git commit -m "test: add scheduler persistence tests (5 tests)

Validates APScheduler SQLite jobstore:
- Jobs written to SQLite file
- Jobs survive scheduler restart
- Job replacement with replace_existing
- Multiple job types coexist independently
- Scheduling lock prevents race conditions

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 7: pH Logic Tests (4 tests)

**Files:**
- Create: `tests/unit/test_ph_logic.py`

**Step 1: Create pH logic test file**

```python
"""
Test pH dosing decision logic based on pH sensor readings.

Critical tests:
- pH too high triggers pH down pump
- pH too low triggers pH up pump
- pH in range skips dosing
- Sensor failures prevent dosing (safety)
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


class TestpHLogic:
    """Test pH-driven dosing decisions"""

    def test_ph_down_when_ph_too_high(self, mock_ph_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """pH above upper threshold should activate pH down pump"""
        # Arrange
        mock_ph_sensor_configurable.ph = 7.5
        mock_config.set_ph_target(6.5, 0.3)  # Range: [6.2, 6.8]

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import start_ph_pumps_static
        start_ph_pumps_static()

        # Assert
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        assert ("pHMinusPump", True) in relay_calls or ("PHMinusPump", True) in relay_calls

        # pH plus should not be activated
        ph_plus_on = [call for call in relay_calls if "Plus" in call[0] and call[1] == True]
        assert len(ph_plus_on) == 0

    def test_ph_up_when_ph_too_low(self, mock_ph_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """pH below lower threshold should activate pH up pump"""
        # Arrange
        mock_ph_sensor_configurable.ph = 5.8
        mock_config.set_ph_target(6.5, 0.3)  # Range: [6.2, 6.8]

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import start_ph_pumps_static
        start_ph_pumps_static()

        # Assert
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        assert ("pHPlusPump", True) in relay_calls or ("PHPlusPump", True) in relay_calls

        # pH minus should not be activated
        ph_minus_on = [call for call in relay_calls if "Minus" in call[0] and call[1] == True]
        assert len(ph_minus_on) == 0

    def test_no_ph_dosing_when_in_range(self, mock_ph_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """pH within range should skip dosing"""
        # Arrange
        mock_ph_sensor_configurable.ph = 6.5
        mock_config.set_ph_target(6.5, 0.3)  # Range: [6.2, 6.8]

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.ph_static.get_scheduler", lambda: mock_scheduler)

        # Act
        from src.ph_static import start_ph_pumps_static
        start_ph_pumps_static()

        # Assert - no pumps should be activated
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        pump_on_calls = [call for call in relay_calls if call[1] == True]
        assert len(pump_on_calls) == 0

    def test_no_ph_dosing_when_sensor_fails(self, monkeypatch):
        """pH sensor failure should prevent any dosing"""
        # Arrange
        monkeypatch.setattr("src.sensors.pH.pH", lambda sensor_id: None)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.ph_static.logger", mock_logger)

        # Act
        from src.ph_static import check_if_ph_dosing_needed
        result = check_if_ph_dosing_needed()

        # Assert - should return (False, None) or similar safe default
        if isinstance(result, tuple):
            assert result[0] == False
        else:
            assert result == False
```

**Step 2: Run pH logic tests**

Run: `pytest tests/unit/test_ph_logic.py -v`
Expected: 4 tests PASS (may need adjustment based on actual ph_static.py implementation)

**Step 3: Commit pH logic tests**

```bash
git add tests/unit/test_ph_logic.py
git commit -m "test: add pH logic tests (4 tests)

Validates pH-driven dosing decisions:
- pH too high activates pH down pump
- pH too low activates pH up pump
- pH in range skips all dosing
- Sensor failure prevents dosing (safety)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Water Level Logic Tests (3 tests)

**Files:**
- Create: `tests/unit/test_water_level_logic.py`

**Step 1: Create water level test file**

```python
"""
Test water level monitoring and refill logic.

Critical tests:
- Low water level opens refill valve
- Adequate water level keeps valve closed
- Sensor failures prevent valve operation (safety)
"""
import pytest
from unittest.mock import MagicMock
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


class TestWaterLevelLogic:
    """Test water level monitoring and refill decisions"""

    def test_refill_when_water_level_low(self, mock_water_level_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """Low water level should open refill valve"""
        # Arrange
        mock_water_level_sensor_configurable.level = 30  # 30%
        mock_config.set_water_level_target(80)  # Target 80%

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        # Act
        from src.water_level_static import check_and_refill_water_static
        check_and_refill_water_static()

        # Assert - refill valve should open
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        refill_on = [call for call in relay_calls if "Refill" in call[0] or "Water" in call[0] and call[1] == True]
        assert len(refill_on) > 0

    def test_no_refill_when_water_level_adequate(self, mock_water_level_sensor_configurable, mock_relay, mock_config, monkeypatch):
        """Adequate water level should keep valve closed"""
        # Arrange
        mock_water_level_sensor_configurable.level = 85  # 85%
        mock_config.set_water_level_target(80)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        # Act
        from src.water_level_static import check_and_refill_water_static
        check_and_refill_water_static()

        # Assert - valve should remain closed
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        refill_on = [call for call in relay_calls if "Refill" in call[0] or "Water" in call[0] and call[1] == True]
        assert len(refill_on) == 0

    def test_no_refill_when_sensor_unavailable(self, monkeypatch, mock_relay):
        """Sensor failure should prevent valve operation (safety)"""
        # Arrange
        monkeypatch.setattr("src.sensors.water_level.WaterLevel", lambda sensor_id: None)

        mock_logger = MagicMock()
        monkeypatch.setattr("src.water_level_static.logger", mock_logger)

        # Act
        from src.water_level_static import check_and_refill_water_static
        check_and_refill_water_static()

        # Assert - valve should remain in safe state (closed)
        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        refill_on = [call for call in relay_calls if "Refill" in call[0] or "Water" in call[0] and call[1] == True]
        assert len(refill_on) == 0
```

**Step 2: Run water level tests**

Run: `pytest tests/unit/test_water_level_logic.py -v`
Expected: 3 tests PASS (may need adjustment based on actual water_level_static.py implementation)

**Step 3: Commit water level tests**

```bash
git add tests/unit/test_water_level_logic.py
git commit -m "test: add water level logic tests (3 tests)

Validates water level monitoring and refill:
- Low level opens refill valve
- Adequate level keeps valve closed
- Sensor failure prevents valve operation (safety)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Run Full Test Suite and Update Linear

**Step 1: Run complete Phase 2 test suite**

Run: `pytest tests/ -v --tb=short`
Expected: 44 tests total (10 Phase 1 + 34 Phase 2) PASS

**Step 2: Generate coverage report**

Run: `pytest tests/ --cov=src --cov-report=term-missing`
Expected: ~60-70% coverage on critical paths

**Step 3: Update Linear issue with progress**

Update MOQ-79 with:
- Phase 2 complete: 34 tests implemented
- Total test count: 44 tests
- Coverage: ~60-70%
- All tests passing

**Step 4: Final commit**

```bash
git add -A
git commit -m "test: complete Phase 2 testing suite (34 tests)

Phase 2 deliverables:
- 6 EC decision logic tests
- 5 pump control & ABC ratio tests
- 6 end-to-end cycle flow tests
- 6 configuration loading tests
- 5 scheduler persistence tests
- 4 pH logic tests
- 3 water level logic tests

Total: 44 tests (Phase 1: 10, Phase 2: 34)
Coverage: ~60-70% of critical paths
All tests pass without hardware dependencies

Closes MOQ-79 Phase 2

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Execution Strategy

**Recommended:** Subagent-driven development in this session
- Each task dispatched to fresh subagent
- Code review between tasks
- Fast iteration on failures
- Immediate debugging

**Alternative:** Parallel session with executing-plans
- Batch execution with checkpoints
- Good for long-running implementations
- Less interactive

---

## Notes

- Some tests may need adjustment based on actual implementation details in `ph_static.py` and `water_level_static.py`
- If those files don't exist, tests will need to be adapted or implementation created
- Mock relay fixture needs to support both `set_relay()` and pump-specific methods
- Config fixtures use temporary paths to avoid interfering with actual device.conf
