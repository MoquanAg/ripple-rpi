"""
Test nutrient dosing decision logic based on EC sensor readings.

Critical tests:
- EC below threshold triggers dosing
- EC at/above threshold skips dosing
- Sensor failures prevent dosing (safety)
- Deadband calculations
- Hysteresis: dose until target, not just until lower threshold
- Min/max alerts
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
from freezegun import freeze_time
from datetime import datetime, timedelta

# Ensure project root is in path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


def _make_sensor_data(ec_value):
    """Build saved_sensor_data structure with given EC value"""
    if ec_value is None:
        return {'data': {'water_metrics': {'ec': {'measurements': {'points': [{'fields': {}}]}}}}}
    return {
        'data': {
            'water_metrics': {
                'ec': {
                    'measurements': {
                        'points': [{'fields': {'value': ec_value}}]
                    }
                }
            }
        }
    }


class TestECDecisionLogic:
    """Test EC-driven nutrient dosing decisions"""

    def _setup_ec_mocks(self, monkeypatch, ec_value, target=1.2, deadband=0.1,
                        ec_min=0.0, ec_max=99.0, dosing_active=True):
        """Common setup: mock sensor data, config helpers, logger, and reset hysteresis"""
        import src.nutrient_static as ns
        ns._dosing_active = dosing_active
        monkeypatch.setattr("src.nutrient_static.logger", MagicMock())
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (target, deadband))
        monkeypatch.setattr("src.nutrient_static.get_ec_min_max", lambda: (ec_min, ec_max))
        monkeypatch.setattr("src.globals.saved_sensor_data", lambda: _make_sensor_data(ec_value))

    def test_dosing_needed_when_ec_below_threshold(self, monkeypatch):
        """EC below (target - deadband) should trigger dosing"""
        self._setup_ec_mocks(monkeypatch, ec_value=0.8, target=1.2, deadband=0.1)
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == True

    def test_no_dosing_when_ec_at_target(self, monkeypatch):
        """EC at target should NOT dose (hysteresis: dosing_active resets)"""
        self._setup_ec_mocks(monkeypatch, ec_value=1.2, target=1.2, deadband=0.1)
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == False

    def test_no_dosing_when_ec_above_threshold(self, monkeypatch):
        """EC above target is safe, no dosing needed"""
        self._setup_ec_mocks(monkeypatch, ec_value=1.5, target=1.2, deadband=0.1)
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == False

    def test_no_dosing_when_sensor_data_missing(self, monkeypatch):
        """Missing sensor data should prevent dosing (safe default)"""
        import src.nutrient_static as ns
        ns._dosing_active = True
        monkeypatch.setattr("src.nutrient_static.logger", MagicMock())
        monkeypatch.setattr("src.globals.saved_sensor_data", lambda: None)
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == False

    def test_no_dosing_when_ec_reading_none(self, monkeypatch):
        """Failed sensor read (value=None) should prevent dosing"""
        self._setup_ec_mocks(monkeypatch, ec_value=None, target=1.2, deadband=0.1)
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == False

    @pytest.mark.parametrize("target,deadband,ec_value,expected", [
        (1.2, 0.1, 0.8, True),   # EC well below lower threshold
        (1.2, 0.1, 1.2, False),  # EC at target
        (1.2, 0.1, 1.5, False),  # EC above target
        (1.5, 0.2, 1.2, True),   # Different deadband, below lower threshold
        (1.0, 0.05, 0.94, True), # Small deadband, below lower threshold
    ])
    def test_deadband_calculation(self, monkeypatch, target, deadband, ec_value, expected):
        """Verify dosing triggers below (target - deadband)"""
        self._setup_ec_mocks(monkeypatch, ec_value=ec_value, target=target, deadband=deadband)
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == expected


class TestECHysteresis:
    """Test hysteresis behavior: dose until target, not just until lower threshold"""

    def _setup(self, monkeypatch, ec_value, dosing_active, target=1.0, deadband=0.1):
        import src.nutrient_static as ns
        ns._dosing_active = dosing_active
        monkeypatch.setattr("src.nutrient_static.logger", MagicMock())
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (target, deadband))
        monkeypatch.setattr("src.nutrient_static.get_ec_min_max", lambda: (0.0, 99.0))
        monkeypatch.setattr("src.globals.saved_sensor_data", lambda: _make_sensor_data(ec_value))

    def test_dose_when_below_deadband(self, monkeypatch):
        """EC < lower_threshold activates dosing"""
        self._setup(monkeypatch, ec_value=0.85, dosing_active=False)
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == True

    def test_continue_dosing_in_recovery_zone(self, monkeypatch):
        """EC between lower_threshold and target continues dosing when active"""
        # EC=0.95, target=1.0, deadband=0.1 → lower=0.9
        # _dosing_active=True (recovering from below 0.9)
        self._setup(monkeypatch, ec_value=0.95, dosing_active=True)
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == True

    def test_no_dosing_in_deadband_when_stable(self, monkeypatch):
        """EC in deadband but never dropped below → no dosing"""
        # EC=0.95, _dosing_active=False (was already above threshold)
        self._setup(monkeypatch, ec_value=0.95, dosing_active=False)
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == False

    def test_dosing_stops_at_target(self, monkeypatch):
        """EC reaching target deactivates dosing"""
        self._setup(monkeypatch, ec_value=1.0, dosing_active=True)
        import src.nutrient_static as ns
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == False
        assert ns._dosing_active == False

    def test_startup_doses_to_target(self, monkeypatch):
        """After restart, if EC is between lower_threshold and target, dose to target"""
        # _dosing_active defaults to True on module load (simulated here)
        self._setup(monkeypatch, ec_value=0.95, dosing_active=True)
        from src.nutrient_static import check_if_nutrient_dosing_needed
        assert check_if_nutrient_dosing_needed() == True

    def test_full_hysteresis_cycle(self, monkeypatch):
        """Complete cycle: drop → dose → recover → stop → drift → no dose"""
        import src.nutrient_static as ns
        from src.nutrient_static import check_if_nutrient_dosing_needed

        def set_ec(val, active):
            self._setup(monkeypatch, ec_value=val, dosing_active=active)

        # 1. EC drops below threshold → dose
        set_ec(0.85, False)
        assert check_if_nutrient_dosing_needed() == True
        assert ns._dosing_active == True

        # 2. EC recovers to 0.95 (still below target) → keep dosing
        set_ec(0.95, ns._dosing_active)
        assert check_if_nutrient_dosing_needed() == True

        # 3. EC reaches target → stop
        set_ec(1.01, ns._dosing_active)
        assert check_if_nutrient_dosing_needed() == False
        assert ns._dosing_active == False

        # 4. EC drifts to 0.95 (within deadband) → don't dose
        set_ec(0.95, ns._dosing_active)
        assert check_if_nutrient_dosing_needed() == False


class TestECMinMaxAlerts:
    """Test min/max EC boundary alerts"""

    def test_alert_when_ec_below_minimum(self, monkeypatch):
        """EC below ec_min should log a warning"""
        import src.nutrient_static as ns
        ns._dosing_active = True
        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.0, 0.1))
        monkeypatch.setattr("src.nutrient_static.get_ec_min_max", lambda: (0.6, 1.5))
        monkeypatch.setattr("src.globals.saved_sensor_data", lambda: _make_sensor_data(0.4))

        from src.nutrient_static import check_if_nutrient_dosing_needed
        check_if_nutrient_dosing_needed()

        # Should have logged a warning about below minimum
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("BELOW MINIMUM" in s for s in warning_calls)

    def test_alert_when_ec_above_maximum(self, monkeypatch):
        """EC above ec_max should log a warning"""
        import src.nutrient_static as ns
        ns._dosing_active = False
        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.0, 0.1))
        monkeypatch.setattr("src.nutrient_static.get_ec_min_max", lambda: (0.6, 1.5))
        monkeypatch.setattr("src.globals.saved_sensor_data", lambda: _make_sensor_data(2.0))

        from src.nutrient_static import check_if_nutrient_dosing_needed
        check_if_nutrient_dosing_needed()

        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("ABOVE MAXIMUM" in s for s in warning_calls)

    def test_no_alert_when_ec_in_range(self, monkeypatch):
        """EC within min/max should not trigger alerts"""
        import src.nutrient_static as ns
        ns._dosing_active = False
        mock_logger = MagicMock()
        monkeypatch.setattr("src.nutrient_static.logger", mock_logger)
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (1.0, 0.1))
        monkeypatch.setattr("src.nutrient_static.get_ec_min_max", lambda: (0.6, 1.5))
        monkeypatch.setattr("src.globals.saved_sensor_data", lambda: _make_sensor_data(1.0))

        from src.nutrient_static import check_if_nutrient_dosing_needed
        check_if_nutrient_dosing_needed()

        mock_logger.warning.assert_not_called()


class TestPumpControlABCRatio:
    """Test pump activation based on ABC ratio configuration"""

    def _setup_dosing_mocks(self, monkeypatch, ec_value, target=1.2, deadband=0.1):
        """Common mock setup for pump control tests"""
        import src.nutrient_static as ns
        ns._dosing_active = True  # Ensure dosing will trigger for low EC
        monkeypatch.setattr("src.nutrient_static.logger", MagicMock())
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (target, deadband))
        monkeypatch.setattr("src.nutrient_static.get_ec_min_max", lambda: (0.0, 99.0))
        monkeypatch.setattr("src.globals.saved_sensor_data", lambda: _make_sensor_data(ec_value))

    def test_pumps_start_with_ratio_1_1_0(self, mock_relay, monkeypatch):
        """ABC ratio 1:1:0 should activate pumps A and B only"""
        self._setup_dosing_mocks(monkeypatch, ec_value=0.8)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [1, 1, 0])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        assert ("NutrientPumpA", True) in relay_calls
        assert ("NutrientPumpB", True) in relay_calls
        pump_c_on_calls = [call for call in relay_calls if call == ("NutrientPumpC", True)]
        assert len(pump_c_on_calls) == 0

    def test_pumps_start_with_ratio_1_1_1(self, mock_relay, monkeypatch):
        """ABC ratio 1:1:1 should activate all three pumps"""
        self._setup_dosing_mocks(monkeypatch, ec_value=0.8)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [1, 1, 1])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        assert ("NutrientPumpA", True) in relay_calls
        assert ("NutrientPumpB", True) in relay_calls
        assert ("NutrientPumpC", True) in relay_calls

    def test_abc_ratio_2_1_0_activates_correct_pumps(self, mock_relay, monkeypatch):
        """Ratio uses >0 as boolean, not duration multiplier"""
        self._setup_dosing_mocks(monkeypatch, ec_value=0.8)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [2, 1, 0])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        assert ("NutrientPumpA", True) in relay_calls
        assert ("NutrientPumpB", True) in relay_calls
        pump_c_on_calls = [call for call in relay_calls if call == ("NutrientPumpC", True)]
        assert len(pump_c_on_calls) == 0

    def test_no_pumps_start_when_ec_adequate(self, mock_relay, monkeypatch):
        """High EC should skip dosing even with valid ABC ratio"""
        self._setup_dosing_mocks(monkeypatch, ec_value=1.5)
        import src.nutrient_static as ns
        ns._dosing_active = False  # Not in recovery

        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [1, 1, 1])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        pump_on_calls = [call for call in relay_calls if call[1] == True]
        assert len(pump_on_calls) == 0

    def test_all_pumps_stop(self, mock_relay, monkeypatch):
        """Stop should turn off all pumps regardless of which were on"""
        monkeypatch.setattr("src.nutrient_static.logger", MagicMock())

        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        mock_relay.set_relay("NutrientPumpA", True)
        mock_relay.set_relay("NutrientPumpC", True)

        from src.nutrient_static import stop_nutrient_pumps_static
        stop_nutrient_pumps_static()

        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        assert ("NutrientPumpA", False) in relay_calls
        assert ("NutrientPumpB", False) in relay_calls
        assert ("NutrientPumpC", False) in relay_calls


class TestEndToEndCycleFlow:
    """Test complete nutrient dosing cycles with timing"""

    def _setup_dosing_mocks(self, monkeypatch, ec_value, target=1.2, deadband=0.1):
        """Common mock setup for cycle flow tests"""
        import src.nutrient_static as ns
        ns._dosing_active = True
        monkeypatch.setattr("src.nutrient_static.logger", MagicMock())
        monkeypatch.setattr("src.nutrient_static.get_ec_targets", lambda: (target, deadband))
        monkeypatch.setattr("src.nutrient_static.get_ec_min_max", lambda: (0.0, 99.0))
        monkeypatch.setattr("src.globals.saved_sensor_data", lambda: _make_sensor_data(ec_value))

    def test_pumps_run_for_configured_duration(self, mock_relay, monkeypatch):
        """Stop job should be scheduled at start + on_duration"""
        self._setup_dosing_mocks(monkeypatch, ec_value=0.8)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [1, 1, 0])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        with freeze_time("2026-01-29 12:00:00"):
            from src.nutrient_static import start_nutrient_pumps_static
            start_nutrient_pumps_static()

            expected_time = datetime(2026, 1, 29, 12, 0, 5)
            mock_scheduler.add_job.assert_called()
            call_args = mock_scheduler.add_job.call_args
            assert call_args[1]['id'] == 'nutrient_stop'
            run_date = call_args[1]['run_date']
            assert abs((run_date - expected_time).total_seconds()) < 1

    def test_next_cycle_scheduled_after_wait(self, mock_relay, monkeypatch):
        """After stop, next start should be scheduled at stop + wait_duration"""
        monkeypatch.setattr("src.nutrient_static.logger", MagicMock())

        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        with freeze_time("2026-01-29 12:00:00"):
            from src.nutrient_static import stop_nutrient_pumps_static
            stop_nutrient_pumps_static()

            expected_time = datetime(2026, 1, 29, 12, 5, 0)
            mock_scheduler.add_job.assert_called()
            call_args = mock_scheduler.add_job.call_args
            assert call_args[1]['id'] == 'nutrient_start'
            run_date = call_args[1]['run_date']
            assert abs((run_date - expected_time).total_seconds()) < 1

    def test_skip_dosing_when_ec_adequate_schedule_next(self, mock_relay, monkeypatch):
        """When EC adequate, skip dosing but schedule next check"""
        self._setup_dosing_mocks(monkeypatch, ec_value=1.5)
        import src.nutrient_static as ns
        ns._dosing_active = False  # Not in recovery

        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [1, 1, 0])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
        pump_on_calls = [call for call in relay_calls if call[1] == True]
        assert len(pump_on_calls) == 0
        mock_scheduler.add_job.assert_called()

    def test_complete_nutrient_cycle(self, mock_relay, monkeypatch):
        """Test full cycle: start → stop → next start"""
        self._setup_dosing_mocks(monkeypatch, ec_value=0.8)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [1, 1, 0])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:05:00"))

        with freeze_time("2026-01-29 12:00:00") as frozen_time:
            from src.nutrient_static import start_nutrient_pumps_static, stop_nutrient_pumps_static

            # 1. Start cycle
            start_nutrient_pumps_static()
            relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
            assert ("NutrientPumpA", True) in relay_calls

            # 2. Advance time and stop
            mock_relay.set_relay.reset_mock()
            frozen_time.tick(delta=timedelta(seconds=5))
            stop_nutrient_pumps_static()
            relay_calls = [call[0] for call in mock_relay.set_relay.call_args_list]
            assert ("NutrientPumpA", False) in relay_calls

            # 3. Verify next cycle scheduled
            call_args = mock_scheduler.add_job.call_args
            assert call_args[1]['id'] == 'nutrient_start'

    def test_no_scheduling_when_duration_zero(self, mock_relay, monkeypatch):
        """on_duration=0 should disable the system"""
        self._setup_dosing_mocks(monkeypatch, ec_value=0.8)

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_abc_ratio_from_config", lambda: [1, 1, 0])
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:00", "00:05:00"))

        from src.nutrient_static import start_nutrient_pumps_static
        start_nutrient_pumps_static()

        assert mock_scheduler.add_job.call_count == 0

    def test_wait_duration_zero_no_next_cycle(self, mock_relay, monkeypatch):
        """wait_duration=0 should not schedule next cycle"""
        monkeypatch.setattr("src.nutrient_static.logger", MagicMock())

        mock_scheduler = MagicMock()
        monkeypatch.setattr("src.nutrient_static.get_scheduler", lambda: mock_scheduler)
        monkeypatch.setattr("src.nutrient_static.get_nutrient_config", lambda: ("00:00:05", "00:00:00"))

        from src.nutrient_static import stop_nutrient_pumps_static
        stop_nutrient_pumps_static()

        assert mock_scheduler.add_job.call_count == 0
