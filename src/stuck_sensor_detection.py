"""Stuck sensor detection for overdose prevention"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SensorCheckResult:
    """Result of sensor response check"""
    stuck: bool
    sensor_responding: bool = False
    action: Optional[str] = None


class StuckSensorDetector:
    """
    Detect sensors that don't respond to dosing.

    Tracks accumulated runtime without sensor change.
    Triggers alert after 60 seconds of dosing with no response.
    """

    MAX_RUNTIME_WITHOUT_CHANGE = 60  # seconds

    def __init__(self):
        self.sensors: Dict[str, dict] = {}

    def start_dosing(self, sensor_name: str, initial_value: float):
        """Start dosing cycle for sensor monitoring"""
        if sensor_name not in self.sensors:
            self.sensors[sensor_name] = {
                'accumulated_runtime': 0,
                'last_value': initial_value,
                'baseline_value': initial_value
            }
        else:
            self.sensors[sensor_name]['baseline_value'] = initial_value

    def check_sensor_response(self, sensor_name: str, current_value: float,
                             runtime_seconds: int) -> SensorCheckResult:
        """Check if sensor is responding to dosing"""
        if sensor_name not in self.sensors:
            return SensorCheckResult(stuck=False)

        sensor_info = self.sensors[sensor_name]
        baseline = sensor_info['baseline_value']

        CHANGE_THRESHOLD = 0.01
        sensor_changed = abs(current_value - baseline) > CHANGE_THRESHOLD

        if sensor_changed:
            sensor_info['accumulated_runtime'] = 0
            sensor_info['last_value'] = current_value
            return SensorCheckResult(stuck=False, sensor_responding=True)
        else:
            sensor_info['accumulated_runtime'] += runtime_seconds
            total_runtime = sensor_info['accumulated_runtime']

            if total_runtime >= self.MAX_RUNTIME_WITHOUT_CHANGE:
                logger.error(
                    f"Stuck {sensor_name} sensor detected: "
                    f"{total_runtime}s runtime, no change from {baseline}"
                )
                return SensorCheckResult(stuck=True, action="stop_dosing_alert")
            else:
                return SensorCheckResult(stuck=False)
