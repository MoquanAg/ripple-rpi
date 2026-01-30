"""Pump timeout enforcement and safety monitoring"""

import time
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class PumpTimeoutMonitor:
    """Monitor pump runtime and enforce timeouts"""

    def __init__(self):
        self.active_pumps: Dict[str, dict] = {}

    def start_pump(self, pump_name: str, relay, max_runtime_seconds: Optional[int]):
        """Start pump with timeout monitoring"""
        relay.set_relay(pump_name, True)
        self.active_pumps[pump_name] = {
            'start_time': time.time(),
            'max_runtime': max_runtime_seconds,
            'relay': relay
        }

    def stop_pump(self, pump_name: str):
        """Stop pump and remove from monitoring"""
        if pump_name in self.active_pumps:
            pump_info = self.active_pumps[pump_name]
            pump_info['relay'].set_relay(pump_name, False)
            del self.active_pumps[pump_name]

    def check_timeouts(self, emergency_flag_path: str):
        """Check all active pumps for timeout violations"""
        from src.emergency_shutdown import trigger_emergency_shutdown

        current_time = time.time()

        for pump_name, pump_info in list(self.active_pumps.items()):
            if pump_info['max_runtime'] is None:
                continue

            runtime = current_time - pump_info['start_time']

            if runtime > pump_info['max_runtime']:
                logger.error(
                    f"Pump timeout: {pump_name} ran {runtime:.1f}s "
                    f"(max {pump_info['max_runtime']}s)"
                )

                trigger_emergency_shutdown(
                    reason=f"pump_timeout_{pump_name}_{runtime:.1f}s",
                    flag_path=emergency_flag_path,
                    relay=pump_info['relay']
                )


# Global monitor instance
_monitor = PumpTimeoutMonitor()


def start_pump_with_timeout(pump_name: str, relay, max_runtime_seconds: Optional[int],
                            emergency_flag_path: str):
    """Start pump with timeout enforcement"""
    _monitor.start_pump(pump_name, relay, max_runtime_seconds)


def stop_pump_with_timeout(pump_name: str):
    """Stop pump and clear timeout"""
    _monitor.stop_pump(pump_name)


def check_pump_timeouts(emergency_flag_path: str = "data/emergency.flag"):
    """Check all pumps for timeout violations"""
    _monitor.check_timeouts(emergency_flag_path=emergency_flag_path)


def reset_monitor():
    """Reset the global monitor (for testing)"""
    global _monitor
    _monitor = PumpTimeoutMonitor()
