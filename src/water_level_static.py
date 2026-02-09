"""
Pure functions for water level valve control.

Called on every sensor reading via the WaterLevel callback mechanism.
No schedulers, no file polling — just threshold evaluation and valve control.

Created: 2025-09-23
Simplified to event-driven: 2026-02-09
"""

import configparser
import os

try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("WaterLevelStatic", log_prefix="ripple_").logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


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


def evaluate_water_level(level):
    """Evaluate water level and control valve. Called on every sensor reading."""
    if not is_water_level_control_enabled():
        return

    if level is None:
        return

    target, deadband, water_min, water_max = get_water_level_targets()
    low_threshold = target - deadband

    from src.sensors.Relay import Relay
    relay = Relay()
    if not relay:
        return

    if level < water_min:
        relay.set_valve_outside_to_tank(True)
        logger.warning(f"Water level ({level}%) BELOW minimum ({water_min}%) - EMERGENCY REFILL")
    elif level < low_threshold:
        relay.set_valve_outside_to_tank(True)
        logger.info(f"Water level ({level}%) below threshold ({low_threshold}%) - REFILL")
    elif level > water_max:
        relay.set_valve_outside_to_tank(False)
        logger.info(f"Water level ({level}%) above maximum ({water_max}%) - valve CLOSED")
    # Between low_threshold and water_max: no action (hysteresis)
