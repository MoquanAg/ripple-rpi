"""
Test sprinkler scheduling logic.

Critical tests:
- Verify stop schedules next cycle
- Verify full cycle: start → stop → next start
- Verify get_scheduler() returns the live globals scheduler (dual-module import bug)
- Verify no scheduling when duration/wait is zero
- Verify scheduling disabled flag is respected
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from freezegun import freeze_time
import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


class TestSprinklerCycleScheduling:
    """Test sprinkler cycle scheduling via sprinkler_static"""

    def test_stop_schedules_next_cycle(self, mock_relay, mock_config, monkeypatch):
        """After stop, next start should be scheduled at stop + wait_duration"""
        mock_logger = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.get_scheduler", lambda: mock_scheduler)

        monkeypatch.setattr("src.sprinkler_static.get_sprinkler_config", lambda: ("00:02:00", "02:00:00"))
        monkeypatch.setattr("src.sprinkler_static.is_sprinkler_scheduling_enabled", lambda: True)

        with freeze_time("2026-02-01 12:00:00"):
            from src.sprinkler_static import stop_sprinklers_static
            stop_sprinklers_static()

            expected_time = datetime(2026, 2, 1, 14, 0, 0)
            mock_scheduler.add_job.assert_called()
            call_args = mock_scheduler.add_job.call_args
            assert call_args[1]['id'] == 'sprinkler_start'
            run_date = call_args[1]['run_date']
            assert abs((run_date - expected_time).total_seconds()) < 1

    def test_start_schedules_stop(self, mock_relay, mock_config, monkeypatch):
        """Start should schedule a stop job at start + on_duration"""
        mock_logger = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.get_scheduler", lambda: mock_scheduler)

        monkeypatch.setattr("src.sprinkler_static.get_sprinkler_config", lambda: ("00:02:00", "02:00:00"))
        monkeypatch.setattr("src.sprinkler_static.is_sprinkler_scheduling_enabled", lambda: True)

        with freeze_time("2026-02-01 12:00:00"):
            from src.sprinkler_static import start_sprinklers_static
            start_sprinklers_static()

            expected_time = datetime(2026, 2, 1, 12, 2, 0)
            mock_scheduler.add_job.assert_called()
            call_args = mock_scheduler.add_job.call_args
            assert call_args[1]['id'] == 'sprinkler_stop'
            run_date = call_args[1]['run_date']
            assert abs((run_date - expected_time).total_seconds()) < 1

    def test_complete_sprinkler_cycle(self, mock_relay, mock_config, monkeypatch):
        """Test full cycle: start → stop → next start scheduled"""
        mock_logger = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.get_scheduler", lambda: mock_scheduler)

        monkeypatch.setattr("src.sprinkler_static.get_sprinkler_config", lambda: ("00:02:00", "02:00:00"))
        monkeypatch.setattr("src.sprinkler_static.is_sprinkler_scheduling_enabled", lambda: True)

        with freeze_time("2026-02-01 12:00:00") as frozen_time:
            from src.sprinkler_static import start_sprinklers_static, stop_sprinklers_static

            # 1. Start cycle - set_sprinklers calls set_relay("Sprinkler", True)
            start_sprinklers_static()
            assert mock_relay.relay_states.get("Sprinkler") == True

            # 2. Advance time and stop
            mock_scheduler.add_job.reset_mock()
            frozen_time.tick(delta=timedelta(seconds=120))
            stop_sprinklers_static()
            assert mock_relay.relay_states.get("Sprinkler") == False

            # 3. Verify next cycle scheduled
            call_args = mock_scheduler.add_job.call_args
            assert call_args[1]['id'] == 'sprinkler_start'

    def test_stop_with_controller_callback_schedules_next(self, mock_relay, mock_config, monkeypatch):
        """stop_sprinklers_with_controller_callback should update controller and schedule next"""
        mock_logger = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.get_scheduler", lambda: mock_scheduler)

        monkeypatch.setattr("src.sprinkler_static.get_sprinkler_config", lambda: ("00:02:00", "02:00:00"))
        monkeypatch.setattr("src.sprinkler_static.is_sprinkler_scheduling_enabled", lambda: True)

        mock_controller = MagicMock()
        mock_controller.is_running = True
        monkeypatch.setattr("src.simplified_sprinkler_controller.get_sprinkler_controller", lambda: mock_controller)

        with freeze_time("2026-02-01 12:02:00"):
            from src.sprinkler_static import stop_sprinklers_with_controller_callback
            stop_sprinklers_with_controller_callback()

            # Sprinklers should be off
            assert mock_relay.relay_states.get("Sprinkler") == False
            # Controller state should be updated
            assert mock_controller.is_running == False
            # Next cycle should be scheduled
            mock_scheduler.add_job.assert_called()
            assert mock_scheduler.add_job.call_args[1]['id'] == 'sprinkler_start'

    def test_no_scheduling_when_duration_zero(self, mock_relay, mock_config, monkeypatch):
        """on_duration=0 should skip starting sprinklers"""
        mock_logger = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.get_scheduler", lambda: mock_scheduler)

        monkeypatch.setattr("src.sprinkler_static.get_sprinkler_config", lambda: ("00:00:00", "02:00:00"))
        monkeypatch.setattr("src.sprinkler_static.is_sprinkler_scheduling_enabled", lambda: True)

        from src.sprinkler_static import start_sprinklers_static
        start_sprinklers_static()

        assert mock_scheduler.add_job.call_count == 0

    def test_wait_duration_zero_no_next_cycle(self, mock_relay, mock_config, monkeypatch):
        """wait_duration=0 should not schedule next cycle"""
        mock_logger = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.get_scheduler", lambda: mock_scheduler)

        monkeypatch.setattr("src.sprinkler_static.get_sprinkler_config", lambda: ("00:02:00", "00:00:00"))
        monkeypatch.setattr("src.sprinkler_static.is_sprinkler_scheduling_enabled", lambda: True)

        from src.sprinkler_static import stop_sprinklers_static
        stop_sprinklers_static()

        assert mock_scheduler.add_job.call_count == 0

    def test_scheduling_disabled_skips_start(self, mock_relay, mock_config, monkeypatch):
        """When sprinkler_scheduling_enabled=false, start should be skipped"""
        mock_logger = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.get_scheduler", lambda: mock_scheduler)

        monkeypatch.setattr("src.sprinkler_static.get_sprinkler_config", lambda: ("00:02:00", "02:00:00"))
        monkeypatch.setattr("src.sprinkler_static.is_sprinkler_scheduling_enabled", lambda: False)

        from src.sprinkler_static import start_sprinklers_static
        start_sprinklers_static()

        assert mock_relay.relay_states.get("Sprinkler") is None  # never touched
        assert mock_scheduler.add_job.call_count == 0

    def test_scheduling_disabled_skips_next_cycle(self, mock_relay, mock_config, monkeypatch):
        """When scheduling disabled, stop should not schedule next cycle"""
        mock_logger = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.logger", mock_logger)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.get_scheduler", lambda: mock_scheduler)

        monkeypatch.setattr("src.sprinkler_static.get_sprinkler_config", lambda: ("00:02:00", "02:00:00"))
        monkeypatch.setattr("src.sprinkler_static.is_sprinkler_scheduling_enabled", lambda: False)

        from src.sprinkler_static import schedule_next_sprinkler_cycle_static
        schedule_next_sprinkler_cycle_static()

        assert mock_scheduler.add_job.call_count == 0


class TestGetSchedulerDualImport:
    """Test that get_scheduler() returns the live globals scheduler.

    This catches the dual-module import bug where 'from src.globals import scheduler'
    creates a stale local binding instead of reading the current value.
    """

    def test_get_scheduler_returns_live_value(self, monkeypatch):
        """get_scheduler() should return the current globals.scheduler, not a stale copy"""
        import src.globals as globals_module

        # Simulate scheduler being None initially (before start_scheduler)
        original_scheduler = globals_module.scheduler
        monkeypatch.setattr(globals_module, "scheduler", None)

        from src.sprinkler_static import get_scheduler
        assert get_scheduler() is None

        # Now simulate start_scheduler() setting the scheduler
        mock_scheduler = MagicMock()
        monkeypatch.setattr(globals_module, "scheduler", mock_scheduler)

        # get_scheduler() should see the updated value
        result = get_scheduler()
        assert result is mock_scheduler, (
            "get_scheduler() returned stale None instead of live scheduler. "
            "This is the dual-module import bug: 'from src.globals import scheduler' "
            "binds the value at import time instead of reading it live."
        )

    def test_all_static_modules_get_scheduler_returns_live_value(self, monkeypatch):
        """All *_static modules should return the live scheduler value"""
        import src.globals as globals_module

        mock_scheduler = MagicMock()
        monkeypatch.setattr(globals_module, "scheduler", mock_scheduler)

        from src.sprinkler_static import get_scheduler as sprinkler_get
        from src.nutrient_static import get_scheduler as nutrient_get
        from src.ph_static import get_scheduler as ph_get
        from src.mixing_static import get_scheduler as mixing_get
        from src.water_level_static import get_scheduler as wl_get

        for name, getter in [
            ("sprinkler_static", sprinkler_get),
            ("nutrient_static", nutrient_get),
            ("ph_static", ph_get),
            ("mixing_static", mixing_get),
            ("water_level_static", wl_get),
        ]:
            result = getter()
            assert result is mock_scheduler, (
                f"{name}.get_scheduler() did not return the live scheduler"
            )

    def test_get_scheduler_none_when_not_started(self, monkeypatch):
        """get_scheduler() should return None when scheduler hasn't been started"""
        import src.globals as globals_module
        monkeypatch.setattr(globals_module, "scheduler", None)

        from src.sprinkler_static import get_scheduler
        assert get_scheduler() is None

    def test_no_scheduling_when_scheduler_unavailable(self, mock_relay, mock_config, monkeypatch):
        """schedule_next_sprinkler_cycle_static should handle None scheduler gracefully"""
        mock_logger = MagicMock()
        monkeypatch.setattr("src.sprinkler_static.logger", mock_logger)

        monkeypatch.setattr("src.sprinkler_static.get_scheduler", lambda: None)
        monkeypatch.setattr("src.sprinkler_static.get_sprinkler_config", lambda: ("00:02:00", "02:00:00"))
        monkeypatch.setattr("src.sprinkler_static.is_sprinkler_scheduling_enabled", lambda: True)

        from src.sprinkler_static import schedule_next_sprinkler_cycle_static
        # Should not raise, should log error
        schedule_next_sprinkler_cycle_static()

        # Verify error was logged
        error_calls = [c for c in mock_logger.error.call_args_list
                       if "No scheduler available" in str(c)]
        assert len(error_calls) > 0
