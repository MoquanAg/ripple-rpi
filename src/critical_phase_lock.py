"""Critical phase locking for concurrent scheduling safety"""

import logging

logger = logging.getLogger(__name__)


def is_in_critical_phase(relay) -> bool:
    """Check if system is in critical phase (dosing active)"""
    dosing_pumps = [
        "NutrientPumpA",
        "NutrientPumpB",
        "NutrientPumpC",
        "pHPlusPump",
        "pHMinusPump"
    ]

    for pump in dosing_pumps:
        try:
            if relay.get_relay_state(pump):
                return True
        except Exception as e:
            logger.warning(f"Could not read relay state for {pump}: {e}")

    return False


def can_accept_new_command(relay) -> bool:
    """Check if new command can be accepted"""
    return not is_in_critical_phase(relay)
