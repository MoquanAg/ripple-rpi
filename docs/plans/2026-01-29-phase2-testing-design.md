# Phase 2 Testing Design: Core Logic Tests

**Date:** 2026-01-29
**Issue:** MOQ-79 Phase 2
**Goal:** Implement sensor-driven cycle tests, configuration loading tests, and scheduler persistence tests

## Overview

Phase 2 extends the test suite with 34 tests covering:
- **Sensor-driven decision logic** (EC, pH, water level)
- **Pump control & ABC ratio** configuration
- **End-to-end cycle timing** (start → stop → next cycle)
- **Configuration loading** (dual-value format, hot-reload)
- **Scheduler persistence** (SQLite jobstore, restart survival)

Target coverage: **60-70%** of critical paths

## Test File Structure

```
tests/
├── unit/
│   ├── test_startup_initialization.py  ✅ (Phase 1 - 10 tests)
│   ├── test_nutrient_logic.py          🆕 (17 tests)
│   ├── test_config_loading.py          🆕 (6 tests)
│   ├── test_ph_logic.py                🆕 (4 tests)
│   ├── test_water_level_logic.py       🆕 (3 tests)
│   └── test_scheduler_persistence.py   🆕 (5 tests)
├── fixtures/
│   ├── mock_relay.py                   ✅ (Phase 1)
│   ├── mock_sensors.py                 📝 (enhance for configurable values)
│   └── mock_modbus.py                  ✅ (Phase 1)
└── conftest.py                         📝 (add config fixtures)
```

## Section 1: Fixture Enhancements

### Enhanced Mock EC Sensor
```python
@pytest.fixture
def mock_ec_sensor(monkeypatch):
    """EC sensor with configurable value"""
    class MockEC:
        def __init__(self, sensor_id):
            self.ec = 1.0  # Default value

    monkeypatch.setattr("src.sensors.ec.EC", MockEC)
    return MockEC("ec_main")
```

### Mock Config Fixture
```python
@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Configurable device.conf for testing"""
    config_file = tmp_path / "device.conf"

    def set_ec_target(target, deadband):
        # Write dual-value format: server, operational
        config_file.write_text(f"""
[EC]
ec_target = 1.0, {target}
ec_deadband = 0.1, {deadband}
""")

    monkeypatch.setattr("src.globals.DEVICE_CONF_PATH", str(config_file))
    return type('Config', (), {'set_ec_target': set_ec_target})()
```

## Section 2: EC Decision Logic (6 tests)

**File:** `test_nutrient_logic.py`

### Test 1: EC Below Threshold → Dose
```python
def test_dosing_needed_when_ec_below_threshold(mock_ec_sensor, mock_config):
    """EC below (target - deadband) should trigger dosing"""
    mock_ec_sensor.ec = 0.8
    mock_config.set_ec_target(1.2, 0.1)  # threshold = 1.1

    result = check_if_nutrient_dosing_needed()
    assert result == True
```

### Test 2: EC At Threshold → Don't Dose
```python
def test_no_dosing_when_ec_at_threshold(mock_ec_sensor, mock_config):
    """EC exactly at threshold should NOT dose"""
    mock_ec_sensor.ec = 1.1
    mock_config.set_ec_target(1.2, 0.1)

    result = check_if_nutrient_dosing_needed()
    assert result == False
```

### Test 3: EC Above Threshold → Don't Dose
```python
def test_no_dosing_when_ec_above_threshold(mock_ec_sensor, mock_config):
    """EC above threshold is safe, no dosing needed"""
    mock_ec_sensor.ec = 1.5
    mock_config.set_ec_target(1.2, 0.1)

    result = check_if_nutrient_dosing_needed()
    assert result == False
```

### Test 4: EC Sensor Unavailable → Don't Dose (Safety)
```python
def test_no_dosing_when_ec_sensor_unavailable(monkeypatch):
    """Sensor failure should prevent dosing (safe default)"""
    def mock_ec_init(sensor_id):
        return None

    monkeypatch.setattr("src.sensors.ec.EC", mock_ec_init)

    result = check_if_nutrient_dosing_needed()
    assert result == False
```

### Test 5: EC Sensor Returns None → Don't Dose
```python
def test_no_dosing_when_ec_reading_none(mock_ec_sensor):
    """Failed sensor read should prevent dosing"""
    mock_ec_sensor.ec = None

    result = check_if_nutrient_dosing_needed()
    assert result == False
```

### Test 6: Deadband Calculation
```python
@pytest.mark.parametrize("target,deadband,expected", [
    (1.2, 0.1, 1.1),
    (1.5, 0.2, 1.3),
    (1.0, 0.05, 0.95),
])
def test_deadband_calculation(target, deadband, expected):
    """Verify threshold = target - deadband"""
    threshold = target - deadband
    assert threshold == expected
```

## Section 3: Pump Control & ABC Ratio (5 tests)

### Test 7: ABC Ratio 1:1:0 → Start A and B Only
```python
def test_pumps_start_with_ratio_1_1_0(mock_ec_sensor, mock_relay, mock_config):
    """ABC ratio 1:1:0 should activate pumps A and B"""
    mock_ec_sensor.ec = 0.8  # Low EC
    mock_config.set_abc_ratio("1:1:0")

    start_nutrient_pumps_static()

    assert mock_relay.get_relay_state("NutrientPumpA") == True
    assert mock_relay.get_relay_state("NutrientPumpB") == True
    assert mock_relay.get_relay_state("NutrientPumpC") == False
```

### Test 8: ABC Ratio 1:1:1 → Start All Three
```python
def test_pumps_start_with_ratio_1_1_1(mock_ec_sensor, mock_relay, mock_config):
    """ABC ratio 1:1:1 should activate all pumps"""
    mock_ec_sensor.ec = 0.8
    mock_config.set_abc_ratio("1:1:1")

    start_nutrient_pumps_static()

    assert mock_relay.get_relay_state("NutrientPumpA") == True
    assert mock_relay.get_relay_state("NutrientPumpB") == True
    assert mock_relay.get_relay_state("NutrientPumpC") == True
```

### Test 9: ABC Ratio 2:1:0 → Only A and B
```python
def test_abc_ratio_2_1_0_activates_correct_pumps(mock_ec_sensor, mock_relay, mock_config):
    """Ratio uses >0 as boolean, not duration multiplier"""
    mock_ec_sensor.ec = 0.8
    mock_config.set_abc_ratio("2:1:0")

    start_nutrient_pumps_static()

    assert mock_relay.get_relay_state("NutrientPumpA") == True
    assert mock_relay.get_relay_state("NutrientPumpB") == True
    assert mock_relay.get_relay_state("NutrientPumpC") == False
```

### Test 10: EC Adequate → No Pumps Start
```python
def test_no_pumps_start_when_ec_adequate(mock_ec_sensor, mock_relay, mock_config):
    """High EC should skip dosing even with valid ABC ratio"""
    mock_ec_sensor.ec = 1.5  # High EC
    mock_config.set_abc_ratio("1:1:1")

    start_nutrient_pumps_static()

    assert mock_relay.get_relay_state("NutrientPumpA") == False
    assert mock_relay.get_relay_state("NutrientPumpB") == False
    assert mock_relay.get_relay_state("NutrientPumpC") == False
```

### Test 11: Pump Stop → All Three Off
```python
def test_all_pumps_stop():
    """Stop should turn off all pumps regardless of which were on"""
    # Pre-start some pumps
    mock_relay.set_relay("NutrientPumpA", True)
    mock_relay.set_relay("NutrientPumpC", True)

    stop_nutrient_pumps_static()

    assert mock_relay.get_relay_state("NutrientPumpA") == False
    assert mock_relay.get_relay_state("NutrientPumpB") == False
    assert mock_relay.get_relay_state("NutrientPumpC") == False
```

## Section 4: End-to-End Cycle Flow (5 tests)

**Uses:** `freezegun` for time mocking

### Test 12: Pump Duration Respected
```python
def test_pumps_run_for_configured_duration(freezegun, mock_config):
    """Stop job should be scheduled at start + on_duration"""
    mock_config.set_nutrient_duration(on="00:00:05", wait="00:05:00")

    with freeze_time("2026-01-29 12:00:00") as frozen_time:
        start_nutrient_pumps_static()

        stop_job = scheduler.get_job('nutrient_stop')
        expected_time = datetime(2026, 1, 29, 12, 0, 5)
        assert stop_job.next_run_time == expected_time
```

### Test 13: Next Cycle Scheduled After Wait
```python
def test_next_cycle_scheduled_after_wait(freezegun, mock_config):
    """After stop, next start should be scheduled at stop + wait_duration"""
    mock_config.set_nutrient_duration(on="00:00:05", wait="00:05:00")

    with freeze_time("2026-01-29 12:00:00") as frozen_time:
        stop_nutrient_pumps_static()

        start_job = scheduler.get_job('nutrient_start')
        expected_time = datetime(2026, 1, 29, 12, 5, 0)
        assert start_job.next_run_time == expected_time
```

### Test 14: EC Adequate → Skip Dosing, Schedule Next Check
```python
def test_skip_dosing_when_ec_adequate_schedule_next(mock_ec_sensor, mock_relay):
    """When EC adequate, skip dosing but schedule next check"""
    mock_ec_sensor.ec = 1.5  # High EC

    start_nutrient_pumps_static()

    # Pumps should not start
    assert mock_relay.get_relay_state("NutrientPumpA") == False

    # But next cycle should be scheduled
    start_job = scheduler.get_job('nutrient_start')
    assert start_job is not None
```

### Test 15: Complete Cycle Flow
```python
def test_complete_nutrient_cycle(freezegun, mock_ec_sensor, mock_relay, mock_config):
    """Test full cycle: start → stop → next start"""
    mock_config.set_nutrient_duration(on="00:00:05", wait="00:05:00")
    mock_ec_sensor.ec = 0.8  # Low EC

    with freeze_time("2026-01-29 12:00:00") as frozen_time:
        # 1. Start cycle
        start_nutrient_pumps_static()
        assert mock_relay.get_relay_state("NutrientPumpA") == True

        # 2. Advance to stop time
        frozen_time.tick(delta=timedelta(seconds=5))
        stop_nutrient_pumps_static()
        assert mock_relay.get_relay_state("NutrientPumpA") == False

        # 3. Verify next cycle scheduled
        start_job = scheduler.get_job('nutrient_start')
        assert start_job.next_run_time == datetime(2026, 1, 29, 12, 5, 5)
```

### Test 16: Duration Zero → No Scheduling
```python
def test_no_scheduling_when_duration_zero(mock_config):
    """on_duration=0 should disable the system"""
    mock_config.set_nutrient_duration(on="00:00:00", wait="00:05:00")

    start_nutrient_pumps_static()

    # No stop job should be scheduled
    stop_job = scheduler.get_job('nutrient_stop')
    assert stop_job is None
```

## Section 5: Configuration Loading (6 tests)

**File:** `test_config_loading.py`

### Test 17: Dual-Value Format Parsing
```python
def test_dual_value_config_parsing(tmp_path, monkeypatch):
    """Operational value (second) should be used, not server default"""
    config_file = tmp_path / "device.conf"
    config_file.write_text("""
[EC]
ec_target = 1.0, 1.2
ec_deadband = 0.1, 0.2
""")
    monkeypatch.setattr("src.globals.DEVICE_CONF_PATH", str(config_file))

    target, deadband = get_ec_targets()
    assert target == 1.2  # Operational value
    assert deadband == 0.2
```

### Test 18: Multiple Dual-Value Configs
```python
def test_all_dual_value_configs():
    """All config functions should parse operational values"""
    on, wait = get_nutrient_config()
    target, deadband = get_ec_targets()
    ratio = get_abc_ratio_from_config()

    # All should return second (operational) values
    assert on == "00:00:05"
    assert target == 1.2
```

### Test 19: Missing Config Section → Safe Defaults
```python
def test_missing_nutrient_section_returns_defaults(tmp_path, monkeypatch):
    """Missing config should return safe defaults (zeros)"""
    config_file = tmp_path / "device.conf"
    config_file.write_text("[SYSTEM]\n")  # No NutrientPump section
    monkeypatch.setattr("src.globals.DEVICE_CONF_PATH", str(config_file))

    on, wait = get_nutrient_config()
    assert on == "00:00:00"  # Disabled
    assert wait == "00:00:00"
```

### Test 20: Malformed Config → Safe Defaults
```python
def test_malformed_duration_returns_zero():
    """Invalid duration string should parse to 0 seconds"""
    assert parse_duration("invalid") == 0
    assert parse_duration("99:99:99") == 0
    assert parse_duration("") == 0
```

### Test 21: Missing Comma in Dual-Value
```python
def test_single_value_config_handles_gracefully(tmp_path, monkeypatch):
    """Config with no comma should handle IndexError"""
    config_file = tmp_path / "device.conf"
    config_file.write_text("""
[EC]
ec_target = 1.2
""")
    monkeypatch.setattr("src.globals.DEVICE_CONF_PATH", str(config_file))

    # Should not crash, returns defaults
    target, deadband = get_ec_targets()
    assert target == 1.0  # Default fallback
```

### Test 22: Config Hot-Reload (Watchdog)
```python
def test_config_reload_updates_values(tmp_path, monkeypatch):
    """Modifying device.conf should reload values"""
    config_file = tmp_path / "device.conf"
    config_file.write_text("""
[EC]
ec_target = 1.0, 1.2
""")
    monkeypatch.setattr("src.globals.DEVICE_CONF_PATH", str(config_file))

    # Initial read
    target, _ = get_ec_targets()
    assert target == 1.2

    # Modify config
    config_file.write_text("""
[EC]
ec_target = 1.0, 1.5
""")

    # Trigger Watchdog reload (or re-read)
    target, _ = get_ec_targets()
    assert target == 1.5  # Updated value
```

## Section 6: Scheduler Persistence (5 tests)

**File:** `test_scheduler_persistence.py`

### Test 23: Jobs Written to SQLite Jobstore
```python
def test_jobs_persist_to_sqlite(tmp_path):
    """Scheduled jobs should be written to SQLite file"""
    jobstore_path = tmp_path / "jobs.sqlite"
    scheduler = create_scheduler_with_sqlite(jobstore_path)

    schedule_next_nutrient_cycle_static()

    # Job exists in scheduler
    assert scheduler.get_job('nutrient_start') is not None

    # SQLite file was created
    assert jobstore_path.exists()
```

### Test 24: Jobs Survive Scheduler Restart
```python
def test_jobs_reload_after_restart(tmp_path):
    """Jobs should be restored from SQLite after restart"""
    jobstore_path = tmp_path / "jobs.sqlite"

    # 1. Create scheduler, add job
    scheduler1 = create_scheduler_with_sqlite(jobstore_path)
    scheduler1.add_job('src.nutrient_static:start_nutrient_pumps_static',
                       'date', run_date=datetime(2026, 1, 29, 15, 0, 0),
                       id='nutrient_start')
    scheduler1.shutdown()

    # 2. Create new scheduler (simulates restart)
    scheduler2 = create_scheduler_with_sqlite(jobstore_path)

    # 3. Job should be restored
    job = scheduler2.get_job('nutrient_start')
    assert job is not None
    assert job.id == 'nutrient_start'
```

### Test 25: Job Replacement with replace_existing
```python
def test_job_replacement_updates_existing():
    """replace_existing=True should update job, not duplicate"""
    # Schedule nutrient_stop at T1
    scheduler.add_job('src.nutrient_static:stop_nutrient_pumps_static',
                      'date', run_date=datetime(2026, 1, 29, 12, 0, 5),
                      id='nutrient_stop', replace_existing=True)

    # Schedule nutrient_stop at T2 (should replace)
    scheduler.add_job('src.nutrient_static:stop_nutrient_pumps_static',
                      'date', run_date=datetime(2026, 1, 29, 12, 0, 10),
                      id='nutrient_stop', replace_existing=True)

    # Only one job should exist
    jobs = [j for j in scheduler.get_jobs() if j.id == 'nutrient_stop']
    assert len(jobs) == 1
    assert jobs[0].next_run_time == datetime(2026, 1, 29, 12, 0, 10)
```

### Test 26: Multiple Job Types Coexist
```python
def test_multiple_jobs_persist_independently(tmp_path):
    """Different job types should persist without interference"""
    jobstore_path = tmp_path / "jobs.sqlite"
    scheduler = create_scheduler_with_sqlite(jobstore_path)

    # Add multiple jobs
    scheduler.add_job('src.nutrient_static:start_nutrient_pumps_static',
                      'date', run_date=datetime.now() + timedelta(minutes=5),
                      id='nutrient_start')
    scheduler.add_job('src.ph_static:start_ph_pumps_static',
                      'date', run_date=datetime.now() + timedelta(minutes=10),
                      id='ph_start')

    scheduler.shutdown()

    # Restart and verify all jobs restored
    scheduler2 = create_scheduler_with_sqlite(jobstore_path)
    assert scheduler2.get_job('nutrient_start') is not None
    assert scheduler2.get_job('ph_start') is not None
```

### Test 27: Scheduling Lock Prevents Race Conditions
```python
def test_scheduling_lock_prevents_duplicates():
    """Concurrent scheduling calls should not create duplicate jobs"""
    import threading

    threads = []
    for i in range(10):
        t = threading.Thread(target=schedule_next_nutrient_cycle_static)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Only one nutrient_start job should exist
    jobs = [j for j in scheduler.get_jobs() if j.id == 'nutrient_start']
    assert len(jobs) == 1
```

## Section 7: pH & Water Level Logic (7 tests)

**File:** `test_ph_logic.py` (4 tests)

### Test 28: pH Too High → pH Down Pump Activates
```python
def test_ph_down_when_ph_too_high(mock_ph_sensor, mock_relay, mock_config):
    """pH above upper threshold should activate pH down pump"""
    mock_ph_sensor.ph = 7.5
    mock_config.set_ph_target(6.5, 0.3)  # Range: [6.2, 6.8]

    start_ph_pumps_static()

    assert mock_relay.get_relay_state("pHMinusPump") == True
    assert mock_relay.get_relay_state("pHPlusPump") == False
```

### Test 29: pH Too Low → pH Up Pump Activates
```python
def test_ph_up_when_ph_too_low(mock_ph_sensor, mock_relay, mock_config):
    """pH below lower threshold should activate pH up pump"""
    mock_ph_sensor.ph = 5.8
    mock_config.set_ph_target(6.5, 0.3)  # Range: [6.2, 6.8]

    start_ph_pumps_static()

    assert mock_relay.get_relay_state("pHPlusPump") == True
    assert mock_relay.get_relay_state("pHMinusPump") == False
```

### Test 30: pH In Range → No Pumps Activate
```python
def test_no_ph_dosing_when_in_range(mock_ph_sensor, mock_relay, mock_config):
    """pH within range should skip dosing"""
    mock_ph_sensor.ph = 6.5
    mock_config.set_ph_target(6.5, 0.3)  # Range: [6.2, 6.8]

    start_ph_pumps_static()

    assert mock_relay.get_relay_state("pHPlusPump") == False
    assert mock_relay.get_relay_state("pHMinusPump") == False
```

### Test 31: pH Sensor Unavailable → No Dosing (Safety)
```python
def test_no_ph_dosing_when_sensor_fails(monkeypatch):
    """pH sensor failure should prevent any dosing"""
    monkeypatch.setattr("src.sensors.pH.pH", lambda id: None)

    result = check_if_ph_dosing_needed()
    assert result == (False, None)  # No dosing, no direction
```

**File:** `test_water_level_logic.py` (3 tests)

### Test 32: Water Level Low → Refill Valve Opens
```python
def test_refill_when_water_level_low(mock_water_level_sensor, mock_relay, mock_config):
    """Low water level should open refill valve"""
    mock_water_level_sensor.level = 30  # 30%
    mock_config.set_water_level_target(80)  # Target 80%

    check_and_refill_water_static()

    assert mock_relay.get_relay_state("WaterRefillValve") == True
```

### Test 33: Water Level Adequate → Valve Closed
```python
def test_no_refill_when_water_level_adequate(mock_water_level_sensor, mock_relay):
    """Adequate water level should keep valve closed"""
    mock_water_level_sensor.level = 85  # 85%
    mock_config.set_water_level_target(80)

    check_and_refill_water_static()

    assert mock_relay.get_relay_state("WaterRefillValve") == False
```

### Test 34: Water Level Sensor Fails → No Action
```python
def test_no_refill_when_sensor_unavailable(monkeypatch):
    """Sensor failure should prevent valve operation (safety)"""
    monkeypatch.setattr("src.sensors.water_level.WaterLevel", lambda id: None)

    check_and_refill_water_static()

    # Valve should remain in safe state (closed)
    assert mock_relay.get_relay_state("WaterRefillValve") == False
```

## Implementation Order

1. **Fixture enhancements** (`conftest.py`, `mock_sensors.py`)
2. **Nutrient logic tests** (Tests 1-16) - largest section
3. **Config loading tests** (Tests 17-22)
4. **Scheduler persistence tests** (Tests 23-27)
5. **pH & water level tests** (Tests 28-34)

## Success Criteria

- ✅ All 34 tests pass independently
- ✅ Tests run in < 5 minutes
- ✅ No hardware dependencies (fully mocked)
- ✅ Coverage estimate: 60-70% of critical paths
- ✅ Tests prevent MOQ-77-type regressions

## Dependencies

Already in `requirements-test.txt`:
- pytest
- pytest-mock
- pytest-asyncio
- freezegun (for time mocking)
- responses (for API tests in Phase 3)

## Notes

- Use `freezegun` for all time-dependent tests (cycle timing)
- Mock `src.globals.scheduler` to prevent background jobs during tests
- Each test should be independent (no shared state)
- Test files mirror the source structure (nutrient_static.py → test_nutrient_logic.py)
