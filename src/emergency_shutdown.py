"""Emergency shutdown system for safety-critical failures"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from audit_event import audit
except Exception:
    audit = None


def trigger_emergency_shutdown(reason: str, flag_path: str, relay=None):
    """
    Trigger emergency shutdown.

    Actions:
    1. Stop all dosing pumps immediately
    2. Create persistent emergency flag
    3. Log reason
    4. Block automatic restarts

    Args:
        reason: Why emergency shutdown was triggered
        flag_path: Path to emergency flag file
        relay: Relay controller instance (optional for testing)
    """
    logger.error(f"EMERGENCY SHUTDOWN TRIGGERED: {reason}")

    # Stop all dosing pumps
    if relay is not None:
        dosing_pumps = [
            "NutrientPumpA",
            "NutrientPumpB",
            "NutrientPumpC",
            "pHPlusPump",
            "pHMinusPump"
        ]

        for pump in dosing_pumps:
            try:
                relay.set_relay(pump, False)
            except Exception as e:
                logger.error(f"Failed to stop {pump}: {e}")

    # Create persistent flag file
    flag_file = Path(flag_path)
    flag_file.parent.mkdir(parents=True, exist_ok=True)
    flag_file.write_text(f"Emergency shutdown: {reason}\n")

    logger.critical(f"Emergency flag created at {flag_path}. Manual intervention required.")

    if audit:
        audit.emit("alarm", "emergency_shutdown",
                   source="autonomous", status="success",
                   value={"reason": reason, "flag_path": flag_path},
                   details=f"EMERGENCY SHUTDOWN: {reason}")


def is_emergency_active(flag_path: str) -> bool:
    """
    Check if emergency shutdown flag is set.

    Args:
        flag_path: Path to emergency flag file

    Returns:
        True if emergency shutdown is active
    """
    return Path(flag_path).exists()


def clear_emergency_shutdown(flag_path: str):
    """
    Clear emergency shutdown flag (manual API call).

    Args:
        flag_path: Path to emergency flag file
    """
    flag_file = Path(flag_path)
    if flag_file.exists():
        flag_file.unlink()
        logger.info("Emergency shutdown flag cleared manually")
