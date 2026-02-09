"""
Event-driven Water Level Controller.

Registers a callback with WaterLevel sensor so valve control reacts
immediately to each new reading. No APScheduler, no file polling.

Created: 2025-09-23
Simplified to event-driven: 2026-02-09
"""

from src.water_level_static import evaluate_water_level

try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("SimplifiedWaterLevel", log_prefix="ripple_").logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


class SimplifiedWaterLevelController:
    """Event-driven water level controller.

    Registers a callback with WaterLevel.on_reading() so every new sensor
    reading triggers threshold evaluation and valve control.
    """

    def __init__(self):
        self.is_monitoring = False
        logger.info("SimplifiedWaterLevelController initialized")

    def _on_level_reading(self, sensor_id, level):
        """Callback invoked by WaterLevel sensor on each new reading."""
        evaluate_water_level(level)

    def start_water_level_monitoring(self):
        """Register callback to react to sensor readings."""
        if self.is_monitoring:
            logger.warning("Water level monitoring already running")
            return False

        from src.sensors.water_level import WaterLevel
        WaterLevel.on_reading(self._on_level_reading)
        self.is_monitoring = True
        logger.info("Water level monitoring started (event-driven)")
        return True

    def stop_monitoring(self):
        """Unregister callback and close valve for safety."""
        if not self.is_monitoring:
            logger.info("No water level monitoring currently running")
            return True

        from src.sensors.water_level import WaterLevel
        WaterLevel.remove_on_reading(self._on_level_reading)

        # Close inlet valve for safety
        from src.sensors.Relay import Relay
        relay = Relay()
        if relay:
            relay.set_valve_outside_to_tank(False)
            logger.info("Inlet valve closed for safety")

        self.is_monitoring = False
        logger.info("Water level monitoring stopped")
        return True

    def force_check_now(self):
        """Force an immediate water level evaluation using latest sensor data."""
        try:
            logger.info("Forcing immediate water level check")
            from src.sensors.water_level import WaterLevel
            for sensor_id, sensor in WaterLevel._instances.items():
                evaluate_water_level(sensor.level)
            return True
        except Exception as e:
            logger.error(f"Error forcing check: {e}")
            return False

    def get_status(self):
        """Get current controller status."""
        return {
            'is_monitoring': self.is_monitoring,
        }

    def shutdown(self):
        """Shutdown the controller."""
        logger.info("Shutting down water level controller")
        self.stop_monitoring()


# Global controller instance (singleton pattern)
_controller_instance = None

def get_water_level_controller():
    """Get singleton instance of water level controller"""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = SimplifiedWaterLevelController()
    return _controller_instance
