"""
Pure functions for water level valve control.

Called on every sensor reading via the WaterLevel callback mechanism.
No schedulers, no file polling — just threshold evaluation and valve control.

Created: 2025-09-23
Simplified to event-driven: 2026-02-09
"""

import configparser
import os
from datetime import datetime

try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("WaterLevelStatic", log_prefix="ripple_").logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


# --- Drain state (module-level) ---
_drain_state = {
    'active': False,
    'target_level': None,
    'reason': None,          # 'manual', 'ec_high', 'ph_range', 'scheduled', 'cleaning'
    'started_at': None,
    'max_duration': None,    # seconds
    'inhibit_refill': True,  # False for flush mode
    'mode': None,            # 'drain', 'flush', 'full_drain'
}


def get_water_level_targets():
    """Get water level targets and limits from device.conf"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)

        # Get operational values (second value after comma)
        target_str = config.get('WaterLevel', 'water_level_target')
        deadband_str = config.get('WaterLevel', 'water_level_deadband')
        min_str = config.get('WaterLevel', 'water_level_min')
        max_str = config.get('WaterLevel', 'water_level_max')

        target = float(target_str.split(',')[1].strip())
        deadband = float(deadband_str.split(',')[1].strip())
        water_min = float(min_str.split(',')[1].strip())
        water_max = float(max_str.split(',')[1].strip())

        return target, deadband, water_min, water_max
    except Exception as e:
        logger.error(f"Error reading water level targets: {e}")
        return 80.0, 10.0, 50.0, 100.0  # Default: target=80, deadband=10, min=50, max=100


def is_water_level_control_enabled():
    """Check if automatic water level valve control is enabled in config"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)

        if not config.has_option('WaterLevel', 'water_level_control_enabled'):
            # Default to enabled if option doesn't exist (backward compatibility)
            return True

        enabled_str = config.get('WaterLevel', 'water_level_control_enabled')
        # Get operational value (second value after comma)
        operational_value = enabled_str.split(',')[1].strip().lower()
        return operational_value == 'true'
    except Exception as e:
        logger.error(f"Error reading water_level_control_enabled: {e}")
        return True  # Default to enabled


def get_drain_config():
    """Read drain safety config from device.conf."""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)

        safety_floor = 30.0
        max_duration = 1800

        if config.has_option('WaterLevel', 'tank_dump_safety_floor'):
            safety_floor = float(config.get('WaterLevel', 'tank_dump_safety_floor').split(',')[1].strip())
        if config.has_option('WaterLevel', 'tank_dump_max_duration_seconds'):
            max_duration = int(config.get('WaterLevel', 'tank_dump_max_duration_seconds').split(',')[1].strip())

        return safety_floor, max_duration
    except Exception as e:
        logger.error(f"Error reading drain config: {e}")
        return 30.0, 1800


def start_drain(target_level=None, drain_amount=None, duration_seconds=None,
                reason='manual', mode='drain'):
    """
    Start a tank drain/flush.

    Modes:
      'drain'      — outlet open, inlet inhibited, stops at target_level
      'flush'      — outlet open, inlet active, stops after duration_seconds
      'full_drain' — outlet open, inlet inhibited, drains to 0 (safety override)

    Returns:
      dict with 'status' ('ok' or 'error') and 'message'.
    """
    global _drain_state

    if _drain_state['active']:
        return {'status': 'error', 'message': 'Drain already active. Stop it first.'}

    safety_floor, config_max_duration = get_drain_config()

    if mode == 'full_drain':
        resolved_target = 0.0
        inhibit_refill = True
        max_dur = duration_seconds or config_max_duration
    elif mode == 'flush':
        if not duration_seconds:
            return {'status': 'error', 'message': 'flush mode requires duration_seconds'}
        resolved_target = safety_floor  # safety net
        inhibit_refill = False
        max_dur = duration_seconds
    elif mode == 'drain':
        # Resolve target level
        if target_level is not None:
            resolved_target = target_level
        elif drain_amount is not None:
            # Need current level to compute target
            try:
                from src.sensors.water_level import WaterLevel
                current_level = None
                for sensor_id, sensor in WaterLevel._instances.items():
                    current_level = sensor.level
                    break
                if current_level is None:
                    return {'status': 'error', 'message': 'Cannot read current water level for drain_amount calculation'}
                resolved_target = current_level - drain_amount
            except Exception as e:
                return {'status': 'error', 'message': f'Error reading current level: {e}'}
        elif duration_seconds:
            # Timed drain with safety floor as target
            resolved_target = safety_floor
        else:
            return {'status': 'error', 'message': 'drain mode requires target_level, drain_amount, or duration_seconds'}

        # Clamp to safety floor
        resolved_target = max(resolved_target, safety_floor)
        inhibit_refill = True
        max_dur = duration_seconds or config_max_duration
    else:
        return {'status': 'error', 'message': f'Unknown mode: {mode}'}

    # Open outlet valve
    try:
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            return {'status': 'error', 'message': 'Relay not available'}
        relay.set_valve_tank_to_outside(True)
    except Exception as e:
        return {'status': 'error', 'message': f'Failed to open outlet valve: {e}'}

    _drain_state = {
        'active': True,
        'target_level': resolved_target,
        'reason': reason,
        'started_at': datetime.now(),
        'max_duration': max_dur,
        'inhibit_refill': inhibit_refill,
        'mode': mode,
    }

    logger.info(f"DRAIN STARTED: mode={mode}, target={resolved_target} cm, "
                f"max_duration={max_dur}s, reason={reason}, inhibit_refill={inhibit_refill}")

    return {'status': 'ok', 'message': f'Drain started: mode={mode}, target={resolved_target} cm'}


def stop_drain(reason_msg='manual stop'):
    """Close outlet valve, clear drain state."""
    global _drain_state

    if not _drain_state['active']:
        logger.info(f"stop_drain called but no drain active (reason: {reason_msg})")
        return

    try:
        from src.sensors.Relay import Relay
        relay = Relay()
        if relay:
            relay.set_valve_tank_to_outside(False)
    except Exception as e:
        logger.error(f"Error closing outlet valve during stop_drain: {e}")

    elapsed = 0
    if _drain_state['started_at']:
        elapsed = (datetime.now() - _drain_state['started_at']).total_seconds()

    logger.info(f"DRAIN STOPPED: reason='{reason_msg}', mode={_drain_state['mode']}, "
                f"elapsed={elapsed:.1f}s, target_was={_drain_state['target_level']} cm")

    _drain_state = {
        'active': False,
        'target_level': None,
        'reason': None,
        'started_at': None,
        'max_duration': None,
        'inhibit_refill': True,
        'mode': None,
    }


def get_drain_status():
    """Return a copy of the drain state (safe for JSON serialization)."""
    state = _drain_state.copy()
    if state['started_at']:
        elapsed = (datetime.now() - state['started_at']).total_seconds()
        state['elapsed_seconds'] = round(elapsed, 1)
        state['started_at'] = state['started_at'].isoformat()
    else:
        state['elapsed_seconds'] = 0
    return state


def evaluate_water_level(level):
    """Evaluate water level and control valve. Called on every sensor reading."""
    if not is_water_level_control_enabled():
        return

    if level is None:
        return

    # --- Drain/flush logic ---
    if _drain_state['active']:
        inhibit_refill = _drain_state['inhibit_refill']
        elapsed = (datetime.now() - _drain_state['started_at']).total_seconds()

        # Check stop conditions
        if level <= _drain_state['target_level']:
            stop_drain(f"target {_drain_state['target_level']} cm reached (level={level} cm)")
        elif _drain_state['max_duration'] and elapsed >= _drain_state['max_duration']:
            stop_drain(f"duration {_drain_state['max_duration']}s exceeded (elapsed={elapsed:.1f}s)")
        else:
            logger.info(f"DRAIN active: level={level} cm, target={_drain_state['target_level']} cm, "
                        f"elapsed={elapsed:.1f}s/{_drain_state['max_duration']}s")

        if inhibit_refill:
            return  # Skip refill logic for pure drain / full drain

    # --- Refill logic (runs normally during flush, or when no drain active) ---
    target, deadband, water_min, water_max = get_water_level_targets()
    low_threshold = target - deadband

    from src.sensors.Relay import Relay
    relay = Relay()
    if not relay:
        return

    if level < water_min:
        relay.set_valve_outside_to_tank(True)
        logger.warning(f"Water level ({level} cm) BELOW minimum ({water_min} cm) - EMERGENCY REFILL")
    elif level < low_threshold:
        relay.set_valve_outside_to_tank(True)
        logger.info(f"Water level ({level} cm) below threshold ({low_threshold} cm) - REFILL")
    elif level >= target:
        relay.set_valve_outside_to_tank(False)
        logger.info(f"Water level ({level} cm) reached target ({target} cm) - valve CLOSED")
    # Between low_threshold and target: no action (hysteresis)
