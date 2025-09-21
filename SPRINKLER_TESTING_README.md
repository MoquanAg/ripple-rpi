# Sprinkler Timing Test Suite

## Overview

This test suite validates that `sprinkler_on_duration` and `sprinkler_wait_duration` from `device.conf` are executed correctly by the Ripple system.

## Current Configuration Status

**⚠️ CRITICAL FINDING**: Your sprinkler system is currently **DISABLED** because the operational values (second values) are set to `00:00:00`.

```ini
[Sprinkler]
sprinkler_on_duration = 01:10:00, 00:00:00    # API value: 1h10m, Operational: DISABLED
sprinkler_wait_duration = 03:00:00, 00:00:00   # API value: 3h, Operational: DISABLED
```

## How the System Works

The Ripple system uses a **dual-value configuration format**:
- **First value**: Used by API/web interface for display and updates
- **Second value**: Used by the actual system for operation

The scheduler and control systems read the **second value** for actual timing execution.

## Test Files

### 1. Quick Configuration Test
```bash
./quick_sprinkler_test.py
```
- **Purpose**: Instantly validate your current configuration
- **Runtime**: < 1 second
- **Output**: Shows parsed values, analysis, and recommendations

### 2. Comprehensive Timing Test
```bash
./test_sprinkler_timing.py
```
- **Purpose**: Full validation of timing accuracy and system behavior
- **Runtime**: ~30 seconds
- **Output**: Detailed JSON report with timing measurements

### 3. Test Runner Script
```bash
./run_sprinkler_test.sh
```
- **Purpose**: Easy-to-use wrapper that shows config and runs tests
- **Runtime**: ~30 seconds
- **Output**: Summary with report file location

## Test Results Interpretation

### Configuration Parsing Test
✅ **PASS**: Configuration file is readable and parseable
❌ **FAIL**: Syntax errors or missing sections in device.conf

### Scheduler Initialization Test
✅ **PASS**: Scheduler correctly sets up timing intervals
❌ **FAIL**: Scheduler not initializing or wrong intervals

### Timing Accuracy Test
✅ **PASS**: Actual execution matches configured durations (within 10% tolerance)
❌ **FAIL**: Significant timing drift or execution errors

### Production Configuration Validation
✅ **PASS**: Configuration values are reasonable for production use
❌ **FAIL**: Values are too extreme or will cause system issues

## How to Fix Your Configuration

To enable the sprinkler system, you need to set the **second values** to match your desired operational timing:

### Option 1: Enable with Current API Values
```ini
[Sprinkler]
sprinkler_on_duration = 01:10:00, 01:10:00    # Both values: 1h 10m
sprinkler_wait_duration = 03:00:00, 03:00:00   # Both values: 3h
```

### Option 2: Set Different Operational Values
```ini
[Sprinkler]
sprinkler_on_duration = 01:10:00, 00:05:00    # API: 1h10m, Operational: 5min
sprinkler_wait_duration = 03:00:00, 00:30:00   # API: 3h, Operational: 30min
```

### Recommended Values for Testing
```ini
[Sprinkler]
sprinkler_on_duration = 01:10:00, 00:00:30    # API: 1h10m, Test: 30sec
sprinkler_wait_duration = 03:00:00, 00:01:00   # API: 3h, Test: 1min
```

## Running Tests After Configuration Changes

1. **Update device.conf** with your desired operational values
2. **Run quick test**: `python3 quick_sprinkler_test.py`
3. **If enabled, run full test**: `python3 test_sprinkler_timing.py`
4. **Monitor logs** during actual system operation

## Understanding Test Output

### Timing Events Log
```
🔧 Mock Relay: Sprinklers ON at 14:23:45.123 (T+0.00s)
🔧 Mock Relay: Sprinklers OFF at 14:23:50.125 (T+5.00s)
```
- Shows exact timing of sprinkler activation/deactivation
- `T+X.XXs` shows time since test start
- Used to calculate timing accuracy

### Validation Checks
- **ON duration reasonable**: 1 minute to 2 hours
- **WAIT > ON duration**: Wait should be longer than run time
- **Total cycle reasonable**: Complete cycle should be < 8 hours
- **Non-zero durations**: Both values must be > 0 for operation

## Troubleshooting

### "Sprinkler system is DISABLED"
- **Cause**: Second values in device.conf are `00:00:00`
- **Fix**: Set second values to desired operational timing

### "Timing accuracy test FAILED"
- **Cause**: System timing drift or scheduler issues
- **Check**: System load, scheduler conflicts, hardware timing

### "No sprinkler jobs found in scheduler"
- **Cause**: Scheduler not initializing sprinkler jobs
- **Check**: Configuration syntax, scheduler startup, dependencies

### "Mock relay not responding"
- **Cause**: Test setup issues with relay mocking
- **Check**: Import paths, dependency installation

## Production Monitoring

After fixing configuration and passing tests:

1. **Monitor system logs** for sprinkler cycle messages
2. **Check actual hardware activation** (sprinkler relays)
3. **Verify timing accuracy** over multiple cycles
4. **Watch for scheduler conflicts** with other system jobs

## Files Created by Tests

- `sprinkler_timing_test_report_YYYYMMDD_HHMMSS.json`: Detailed test results
- `config/device.conf.backup`: Backup created during timing tests
- Test logs in console output

## Safety Notes

- Tests use **mock relays** - no actual hardware activation during testing
- Configuration backups are created before modifications
- Original config is restored after timing tests
- Production config validation prevents dangerous settings

---

**Next Steps**: 
1. Fix your device.conf operational values (second values)
2. Run `python3 quick_sprinkler_test.py` to verify
3. Run full test suite with `./run_sprinkler_test.sh`
4. Monitor actual system operation
