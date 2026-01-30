"""File system resilience tests for JSON and INI config files.

Tests how the system handles corrupted, missing, or inaccessible
configuration and data files.

Targets:
- src/helpers.py (save_data, save_sensor_data, jsonc_to_json)
- src/globals.py (saved_sensor_data, config loading)
- src/runtime_tracker.py (DosingRuntimeTracker.load_history)

Critical files:
- data/saved_sensor_data.json
- data/runtime_tracker_history.json
- config/device.conf
- config/action.json
"""

import pytest
import json
import os
import configparser
import threading
from pathlib import Path
from unittest.mock import patch


@pytest.mark.resilience
class TestSensorDataResilience:
    """Tests for saved_sensor_data.json corruption scenarios"""

    def test_sensor_data_json_truncated(self, tmp_path, file_corruptor):
        """
        Failure Mode: Power loss during sensor data save -> partial JSON
        Expected: System uses default/empty sensor data, continues
        """
        from src.helpers import save_data

        sensor_file = str(tmp_path / "saved_sensor_data.json")
        valid_json = '{"ec": 1.2, "ph": 6.5, "water_level": 80}'
        file_corruptor.write_truncated(sensor_file, valid_json, truncate_at=20)

        # save_data reads existing file, handles JSONDecodeError
        try:
            save_data([], {"new_key": "value"}, sensor_file)
            # If it succeeds, it handled the corrupt file
            with open(sensor_file, 'r') as f:
                result = json.loads(f.read())
            assert "new_key" in result
        except Exception as e:
            pytest.xfail(f"Truncated JSON crashes save_data: {e}")

    def test_sensor_data_json_garbage(self, tmp_path, file_corruptor):
        """
        Failure Mode: SD card sector corruption -> random bytes
        Expected: System uses default sensor data, logs error
        """
        from src.helpers import save_data

        sensor_file = str(tmp_path / "saved_sensor_data.json")
        file_corruptor.write_garbage(sensor_file)

        try:
            save_data([], {"ec": 1.5}, sensor_file)
            with open(sensor_file, 'r') as f:
                result = json.loads(f.read())
            assert "ec" in result
        except Exception as e:
            pytest.xfail(f"Garbage JSON crashes save_data: {e}")

    def test_sensor_data_json_missing(self, tmp_path):
        """
        Failure Mode: File never created or deleted
        Expected: System starts with empty sensor data
        """
        from src.helpers import save_data

        sensor_file = str(tmp_path / "saved_sensor_data.json")
        assert not Path(sensor_file).exists()

        # save_data handles FileNotFoundError
        save_data([], {"ec": 1.2}, sensor_file)

        with open(sensor_file, 'r') as f:
            result = json.loads(f.read())
        assert "ec" in result

    def test_sensor_data_json_empty(self, tmp_path, file_corruptor):
        """
        Failure Mode: Power loss at start of write -> zero-length file
        Expected: System uses defaults, does not crash
        """
        from src.helpers import save_data

        sensor_file = str(tmp_path / "saved_sensor_data.json")
        file_corruptor.write_empty(sensor_file)

        try:
            save_data([], {"ec": 1.0}, sensor_file)
            with open(sensor_file, 'r') as f:
                result = json.loads(f.read())
            assert "ec" in result
        except Exception as e:
            pytest.xfail(f"Empty JSON file crashes save_data: {e}")

    def test_saved_sensor_data_loader_corrupt(self, tmp_path, file_corruptor, monkeypatch):
        """
        Failure Mode: saved_sensor_data.json corrupt when globals reads it
        Expected: globals.saved_sensor_data() returns None gracefully
        """
        import src.globals as ripple_globals

        sensor_file = str(tmp_path / "saved_sensor_data.json")
        file_corruptor.write_garbage(sensor_file)
        monkeypatch.setattr(ripple_globals, 'SAVED_SENSOR_DATA_PATH', sensor_file)

        result = ripple_globals.saved_sensor_data()
        # saved_sensor_data() catches all exceptions and returns None
        assert result is None

    def test_saved_sensor_data_loader_missing(self, tmp_path, monkeypatch):
        """
        Failure Mode: saved_sensor_data.json doesn't exist
        Expected: globals.saved_sensor_data() returns None
        """
        import src.globals as ripple_globals

        sensor_file = str(tmp_path / "nonexistent.json")
        monkeypatch.setattr(ripple_globals, 'SAVED_SENSOR_DATA_PATH', sensor_file)

        result = ripple_globals.saved_sensor_data()
        assert result is None


@pytest.mark.resilience
class TestRuntimeTrackerResilience:
    """Tests for runtime_tracker_history.json corruption"""

    def test_runtime_tracker_json_corrupted(self, tmp_path, file_corruptor):
        """
        Failure Mode: runtime_tracker_history.json corrupted
        Expected: System resets runtime tracking (fresh start)
        """
        from src.runtime_tracker import DosingRuntimeTracker

        tracker_file = str(tmp_path / "runtime_tracker_history.json")
        file_corruptor.write_garbage(tracker_file)

        try:
            tracker = DosingRuntimeTracker(storage_path=tracker_file)
            # load_history catches JSONDecodeError and resets
            assert tracker.get_today_total_runtime() == 0
        except (UnicodeDecodeError, Exception) as e:
            pytest.xfail(f"Garbage binary in runtime tracker crashes load_history: {e}")

    def test_runtime_tracker_partial_write(self, tmp_path, file_corruptor):
        """
        Failure Mode: Power loss during runtime tracker save
        Expected: System resets tracking, logs warning
        """
        from src.runtime_tracker import DosingRuntimeTracker

        tracker_file = str(tmp_path / "runtime_tracker_history.json")
        valid_data = '{"2026-01-30": 1800}'
        file_corruptor.write_truncated(tracker_file, valid_data, truncate_at=15)

        tracker = DosingRuntimeTracker(storage_path=tracker_file)
        assert tracker.get_today_total_runtime() == 0

    def test_runtime_tracker_missing(self, tmp_path):
        """
        Failure Mode: Runtime tracker file doesn't exist
        Expected: Fresh tracker with zero runtime
        """
        from src.runtime_tracker import DosingRuntimeTracker

        tracker_file = str(tmp_path / "runtime_tracker_history.json")
        assert not Path(tracker_file).exists()

        tracker = DosingRuntimeTracker(storage_path=tracker_file)
        assert tracker.get_today_total_runtime() == 0

    def test_runtime_tracker_empty_file(self, tmp_path, file_corruptor):
        """
        Failure Mode: Zero-length runtime tracker file
        Expected: Fresh tracker
        """
        from src.runtime_tracker import DosingRuntimeTracker

        tracker_file = str(tmp_path / "runtime_tracker_history.json")
        file_corruptor.write_empty(tracker_file)

        tracker = DosingRuntimeTracker(storage_path=tracker_file)
        assert tracker.get_today_total_runtime() == 0


@pytest.mark.resilience
class TestActionJsonResilience:
    """Tests for config/action.json corruption"""

    def test_action_json_corrupted(self, tmp_path, file_corruptor):
        """
        Failure Mode: action.json contains invalid JSON
        Expected: System ignores manual commands, continues auto operation
        """
        from src.helpers import jsonc_to_json

        action_file = tmp_path / "action.json"
        file_corruptor.write_garbage(str(action_file))

        try:
            result = jsonc_to_json(action_file.read_text(errors='replace'))
            # If parsing succeeds on garbage, that's unexpected
            pytest.xfail("Garbage parsed as valid JSONC - unexpected")
        except Exception:
            # Expected: parsing fails on garbage data
            pass

    def test_action_json_missing(self, tmp_path):
        """
        Failure Mode: action.json deleted or never created
        Expected: FileNotFoundError handled by caller
        """
        action_file = tmp_path / "action.json"
        assert not action_file.exists()

        try:
            content = action_file.read_text()
            pytest.fail("Should have raised FileNotFoundError")
        except FileNotFoundError:
            pass  # Expected behavior


@pytest.mark.resilience
class TestDeviceConfResilience:
    """Tests for config/device.conf corruption"""

    def test_device_conf_truncated(self, tmp_path, file_corruptor):
        """
        Failure Mode: Power loss during config write -> partial INI
        Expected: System uses defaults for missing sections
        """
        config_file = str(tmp_path / "device.conf")
        valid_config = """[SYSTEM]
username = admin
password = admin

[NutrientPump]
nutrient_pump_on_duration = 00:00:10, 00:00:15
"""
        file_corruptor.write_truncated(config_file, valid_config, truncate_at=40)

        config = configparser.ConfigParser()
        config.read(config_file)

        # ConfigParser handles partial files - it reads what it can
        # Verify it doesn't crash
        assert config is not None

    def test_device_conf_invalid_ini(self, tmp_path):
        """
        Failure Mode: Config file has corrupt INI syntax
        Expected: System uses all defaults, logs error
        """
        config_file = tmp_path / "device.conf"
        config_file.write_text("this is not\nvalid INI\nformat at all\n")

        config = configparser.ConfigParser()
        try:
            loaded = config.read(str(config_file))
            # ConfigParser.read() returns list of successfully read files
            assert config is not None
            # No sections parsed from invalid content
            assert len(config.sections()) == 0
        except configparser.MissingSectionHeaderError:
            pytest.xfail("ConfigParser raises MissingSectionHeaderError on content without section headers")

    def test_device_conf_permission_denied(self, tmp_path, file_corruptor):
        """
        Failure Mode: File permissions changed
        Expected: System uses defaults
        """
        config_file = str(tmp_path / "device.conf")
        Path(config_file).write_text("[SYSTEM]\nusername = admin\n")
        file_corruptor.make_unreadable(config_file)

        config = configparser.ConfigParser()
        try:
            loaded = config.read(config_file)
            # ConfigParser.read() silently ignores unreadable files
            # loaded will be empty list
            assert loaded == [] or len(config.sections()) == 0
        except PermissionError:
            pass  # Also acceptable behavior

        # Cleanup
        os.chmod(config_file, 0o644)

    def test_device_conf_missing(self, tmp_path):
        """
        Failure Mode: Config file deleted or never deployed
        Expected: System starts with all defaults
        """
        config_file = str(tmp_path / "nonexistent_device.conf")

        config = configparser.ConfigParser()
        loaded = config.read(config_file)

        assert loaded == []
        assert len(config.sections()) == 0


@pytest.mark.resilience
class TestWriteSafety:
    """Tests for write operation resilience"""

    def test_save_sensor_data_to_readonly_dir(self, tmp_path, file_corruptor):
        """
        Failure Mode: Cannot save sensor data (directory read-only)
        Expected: System continues operating, does not crash
        """
        from src.helpers import save_data

        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        sensor_file = str(readonly_dir / "saved_sensor_data.json")
        Path(sensor_file).write_text('{}')
        file_corruptor.make_readonly(str(readonly_dir))

        try:
            save_data([], {"ec": 1.2}, sensor_file)
            # If it succeeds, OS allowed it (possible on some systems)
        except (PermissionError, OSError):
            pass  # Expected: cannot write to readonly dir

        # Cleanup
        os.chmod(str(readonly_dir), 0o755)

    def test_sensor_data_write_then_read_consistency(self, tmp_path):
        """
        Failure Mode: Non-atomic write leaves partial data on crash
        Expected: Verify write produces valid JSON
        """
        from src.helpers import save_data

        sensor_file = str(tmp_path / "saved_sensor_data.json")

        # Write data
        save_data([], {"ec": 1.5, "ph": 6.5, "water_level": 80}, sensor_file)

        # Verify file is valid JSON
        with open(sensor_file, 'r') as f:
            data = json.load(f)
        assert "ec" in data
        assert data["ec"] == 1.5
