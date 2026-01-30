import pytest
from datetime import datetime, timedelta
from freezegun import freeze_time


def test_tracker_initialized_empty(tmp_path):
    """New tracker starts with zero runtime"""
    from src.runtime_tracker import DosingRuntimeTracker

    tracker = DosingRuntimeTracker(storage_path=str(tmp_path / "runtime.json"))
    assert tracker.get_today_total_runtime() == 0


def test_add_dosing_event_increases_runtime(tmp_path):
    """Adding dosing event increases total runtime"""
    from src.runtime_tracker import DosingRuntimeTracker

    tracker = DosingRuntimeTracker(storage_path=str(tmp_path / "runtime.json"))
    tracker.add_dosing_event(pump_name="NutrientPumpA", duration_seconds=120)

    assert tracker.get_today_total_runtime() == 120


def test_can_dose_within_daily_limit(tmp_path):
    """Dosing allowed when under 60 min limit"""
    from src.runtime_tracker import DosingRuntimeTracker

    tracker = DosingRuntimeTracker(storage_path=str(tmp_path / "runtime.json"))
    tracker.add_dosing_event(pump_name="NutrientPumpA", duration_seconds=1800)  # 30 min

    assert tracker.can_dose(planned_duration=1800) == True  # 30 + 30 = 60 min


def test_cannot_dose_exceeds_daily_limit(tmp_path):
    """Dosing blocked when would exceed 60 min limit"""
    from src.runtime_tracker import DosingRuntimeTracker

    tracker = DosingRuntimeTracker(storage_path=str(tmp_path / "runtime.json"))
    tracker.add_dosing_event(pump_name="NutrientPumpA", duration_seconds=3600)  # 60 min

    assert tracker.can_dose(planned_duration=1) == False  # Already at limit


def test_runtime_resets_next_day(tmp_path):
    """Runtime resets to zero at midnight"""
    from src.runtime_tracker import DosingRuntimeTracker

    with freeze_time("2026-01-30 23:00:00") as frozen_time:
        tracker = DosingRuntimeTracker(storage_path=str(tmp_path / "runtime.json"))
        tracker.add_dosing_event(pump_name="NutrientPumpA", duration_seconds=1800)

        assert tracker.get_today_total_runtime() == 1800

        # Advance to next day
        frozen_time.move_to("2026-01-31 01:00:00")

        assert tracker.get_today_total_runtime() == 0  # Reset
