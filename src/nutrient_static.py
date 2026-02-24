"""
Static functions for nutrient pump control with APScheduler.

These functions are completely independent and safe for SQLite serialization.
No lambda functions, no closures, no serialization issues.

Based on proven sprinkler pattern.
Created: 2025-09-23
Author: Linus-style simplification
"""

import configparser
import os
import time
import threading
from datetime import datetime, timedelta
# APScheduler imports removed - using global scheduler from globals.py

# Global lock to prevent race conditions in scheduling
_scheduling_lock = threading.Lock()

# Global logger import
try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("NutrientStatic", log_prefix="ripple_").logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    from audit_event import audit
except Exception:
    audit = None

def get_scheduler():
    """Get the global scheduler instance from globals.py"""
    try:
        import src.globals as globals_module
        return globals_module.get_scheduler()
    except Exception as e:
        logger.error(f"Error getting global scheduler: {e}")
        return None

def get_nutrient_config():
    """Get nutrient pump configuration from device.conf"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)
        
        # Get operational values (second value after comma)
        on_str = config.get('NutrientPump', 'nutrient_pump_on_duration')
        wait_str = config.get('NutrientPump', 'nutrient_pump_wait_duration')
        
        on_duration = on_str.split(',')[1].strip()
        wait_duration = wait_str.split(',')[1].strip()
        
        return on_duration, wait_duration
    except Exception as e:
        logger.error(f"Error reading nutrient config: {e}")
        return "00:00:00", "00:00:00"

def parse_duration(duration_str):
    """Parse HH:MM:SS to seconds"""
    try:
        parts = duration_str.split(':')
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except Exception:
        return 0

def get_ec_targets():
    """Get EC target and deadband from config"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)
        
        # Get operational values (second value after comma)
        target_str = config.get('EC', 'ec_target')
        deadband_str = config.get('EC', 'ec_deadband')
        
        target = float(target_str.split(',')[1].strip())
        deadband = float(deadband_str.split(',')[1].strip())
        
        return target, deadband
    except Exception as e:
        logger.error(f"Error reading EC config: {e}")
        return 1.0, 0.1  # Default values

def get_ec_min_max():
    """Get EC min and max from config"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)
        ec_min = float(config.get('EC', 'ec_min').split(',')[1].strip())
        ec_max = float(config.get('EC', 'ec_max').split(',')[1].strip())
        return ec_min, ec_max
    except Exception as e:
        logger.error(f"Error reading EC min/max config: {e}")
        return 0.0, 99.0  # Safe defaults (never alert)

# Hysteresis flag: tracks whether a dosing sequence is active.
# Initialized True so that after a restart, if EC is between
# lower_threshold and target, we dose up to target.
_dosing_active = True

def get_abc_ratio_from_config():
    """Get ABC ratio from config"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)

        # Get operational values (second value after comma)
        ratio_str = config.get('NutrientPump', 'abc_ratio')
        ratio_values = ratio_str.split(',')[1].strip().strip('"').strip("'")

        # Parse "1:1:0" format (strip quotes/whitespace from each part)
        parts = ratio_values.split(':')
        return [int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip())]
    except Exception as e:
        logger.error(f"Error reading ABC ratio: {e}")
        return [1, 1, 0]  # Default ratio

def check_if_nutrient_dosing_needed():
    """Check EC levels to determine if nutrient dosing is needed.

    Uses hysteresis: dosing triggers when EC drops below (target - deadband),
    then continues until EC reaches the actual target. This prevents EC from
    settling at the bottom of the deadband.
    """
    global _dosing_active
    try:
        # Get current EC reading from saved sensor data file
        # Note: We read from file instead of EC singleton because APScheduler
        # jobs run in separate threads where the singleton may not be properly
        # initialized with current readings
        import src.globals as globals
        sensor_data = globals.saved_sensor_data()

        if not sensor_data:
            logger.error("[SENSOR-CHECK] Failed to load sensor data file")
            return False

        # Navigate to EC data: data -> water_metrics -> ec -> measurements -> points[0] -> fields -> value
        ec_data = sensor_data.get('data', {}).get('water_metrics', {}).get('ec', {})
        ec_points = ec_data.get('measurements', {}).get('points', [])

        if not ec_points:
            logger.error("[SENSOR-CHECK] No EC data points found in saved data")
            return False

        current_ec = ec_points[0].get('fields', {}).get('value')
        if current_ec is None:
            logger.error("[SENSOR-CHECK] Failed to get EC reading from saved data")
            return False

        # Get target configuration
        target_ec, deadband = get_ec_targets()
        ec_min, ec_max = get_ec_min_max()
        lower_threshold = target_ec - deadband

        logger.info(f"[SENSOR-CHECK] Current EC: {current_ec:.3f} mS/cm")
        logger.info(f"[SENSOR-CHECK] Target EC: {target_ec:.3f} mS/cm (deadband: ±{deadband:.3f})")
        logger.info(f"[SENSOR-CHECK] Lower threshold: {lower_threshold:.3f} mS/cm")

        # Alert on min/max breaches
        if current_ec < ec_min:
            logger.warning(f"⚠️ [SENSOR-CHECK] EC {current_ec:.3f} BELOW MINIMUM {ec_min:.3f}")
            if audit:
                audit.emit("alarm", "ec_below_minimum",
                           resource="EC", source="autonomous",
                           value={"current_ec": round(current_ec, 3), "ec_min": ec_min},
                           details=f"EC {current_ec:.3f} below minimum {ec_min:.3f}",
                           debounce_key="ec_below_minimum", debounce_seconds=600)
        if current_ec > ec_max:
            logger.warning(f"⚠️ [SENSOR-CHECK] EC {current_ec:.3f} ABOVE MAXIMUM {ec_max:.3f}")
            if audit:
                audit.emit("alarm", "ec_above_maximum",
                           resource="EC", source="autonomous",
                           value={"current_ec": round(current_ec, 3), "ec_max": ec_max},
                           details=f"EC {current_ec:.3f} above maximum {ec_max:.3f}",
                           debounce_key="ec_above_maximum", debounce_seconds=600)

        # Hysteresis dosing logic:
        # - Trigger dosing when EC drops below lower threshold (target - deadband)
        # - Continue dosing until EC reaches the actual target
        # - Once at target, don't re-dose until EC drops below lower threshold again
        if current_ec < lower_threshold:
            _dosing_active = True
            logger.info("🔴 [SENSOR-CHECK] EC BELOW DEADBAND - Nutrient dosing needed")
            return True
        elif _dosing_active and current_ec < target_ec:
            logger.info("🟡 [SENSOR-CHECK] EC BELOW TARGET (in deadband recovery) - Dosing to reach target")
            return True
        else:
            _dosing_active = False
            logger.info("🟢 [SENSOR-CHECK] EC ADEQUATE - No dosing needed")
            return False

    except Exception as e:
        logger.error(f"[SENSOR-CHECK] Error checking EC levels: {e}")
        return False  # Don't dose if we can't read sensors

def start_nutrient_pumps_static():
    """Static function to start nutrient pumps - SENSOR DRIVEN - safe for APScheduler"""
    try:
        logger.info("==== SENSOR-DRIVEN NUTRIENT CHECK TRIGGERED ====")
        
        # STEP 1: Check if nutrient dosing is actually needed
        dosing_needed = check_if_nutrient_dosing_needed()
        
        if not dosing_needed:
            logger.info("[SENSOR-DRIVEN] EC levels adequate - skipping nutrient dosing")
            # Schedule next check (don't dose, just check again later)
            schedule_next_nutrient_cycle_static()
            return
            
        # STEP 2: EC is low - proceed with dosing
        logger.info("🧪 [SENSOR-DRIVEN] EC below target - starting nutrient dosing")
        
        # Get configuration  
        on_duration_str, wait_duration_str = get_nutrient_config()
        on_seconds = parse_duration(on_duration_str)
        
        if on_seconds == 0:
            logger.warning("[SENSOR-DRIVEN] Nutrient pump duration is 0, skipping")
            return
            
        # STEP 3: Start nutrient pumps based on ABC ratio
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            logger.error("[SENSOR-DRIVEN] No relay available for nutrient pump start")
            return
            
        # Get ABC ratio from config and start appropriate pumps
        abc_ratio = get_abc_ratio_from_config()
        pumps_started = []
        
        if abc_ratio[0] > 0:  # Pump A
            relay.set_relay("NutrientPumpA", True)
            pumps_started.append("A")
        if abc_ratio[1] > 0:  # Pump B  
            relay.set_relay("NutrientPumpB", True)
            pumps_started.append("B")
        if abc_ratio[2] > 0:  # Pump C
            relay.set_relay("NutrientPumpC", True)
            pumps_started.append("C")
            
        logger.info(f"[SENSOR-DRIVEN] Nutrient pumps {pumps_started} started for {on_duration_str} ({on_seconds}s)")

        if audit:
            audit.emit("dosing", "nutrient_start",
                       resource=",".join(f"NutrientPump{p}" for p in pumps_started),
                       source="autonomous",
                       value={"abc_ratio": abc_ratio, "duration_s": on_seconds, "pumps": pumps_started},
                       details=f"EC-driven dosing, pumps {pumps_started} for {on_duration_str}")

        # Schedule stop
        schedule_nutrient_stop_static(on_seconds)
        
    except Exception as e:
        logger.error(f"[SENSOR-DRIVEN] Error in nutrient pump logic: {e}")
        logger.exception("[SENSOR-DRIVEN] Full exception details:")

def stop_nutrient_pumps_static():
    """Static function to stop nutrient pumps - safe for APScheduler"""
    try:
        logger.info("==== STATIC NUTRIENT PUMP STOP TRIGGERED ====")
        
        # Turn off nutrient pumps
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            logger.error("[STATIC] No relay available for nutrient pump stop")
            return
            
        relay.set_relay("NutrientPumpA", False)
        relay.set_relay("NutrientPumpB", False)
        relay.set_relay("NutrientPumpC", False)
        logger.info("[STATIC] Nutrient pumps stopped")

        if audit:
            audit.emit("dosing", "nutrient_stop",
                       resource="NutrientPumpA,NutrientPumpB,NutrientPumpC",
                       source="autonomous")

        # Schedule next cycle
        schedule_next_nutrient_cycle_static()
        
    except Exception as e:
        logger.error(f"[STATIC] Error stopping nutrient pumps: {e}")
        logger.exception("[STATIC] Full exception details:")

def schedule_nutrient_stop_static(on_seconds):
    """Schedule nutrient pump stop using APScheduler"""
    try:
        scheduler = get_scheduler()
        if not scheduler:
            logger.error("[STATIC] No scheduler available for stop scheduling")
            return
            
        stop_time = datetime.now() + timedelta(seconds=on_seconds)
        scheduler.add_job(
            'src.nutrient_static:stop_nutrient_pumps_static',
            'date',
            run_date=stop_time,
            id='nutrient_stop',
            replace_existing=True
        )
        logger.info(f"[STATIC] Nutrient pump stop scheduled for {stop_time.strftime('%H:%M:%S')}")
        
    except Exception as e:
        logger.error(f"[STATIC] Error scheduling nutrient pump stop: {e}")

def schedule_next_nutrient_cycle_static():
    """Schedule the next nutrient pump cycle using APScheduler"""
    with _scheduling_lock:  # Prevent race conditions
        try:
            # Get configuration
            on_duration_str, wait_duration_str = get_nutrient_config()
            wait_seconds = parse_duration(wait_duration_str)
            
            if wait_seconds == 0:
                logger.warning("[STATIC] Wait duration is 0, not scheduling next cycle")
                return
                
            scheduler = get_scheduler()
            if not scheduler:
                logger.error("[STATIC] No scheduler available for next cycle scheduling")
                return
                
            # Check if job already exists to avoid duplicate scheduling
            try:
                existing_job = scheduler.get_job('nutrient_start')
                if existing_job:
                    logger.debug(f"[STATIC] Nutrient cycle already scheduled for {existing_job.next_run_time}")
                    return
            except:
                pass  # Job doesn't exist, which is fine
                
            next_run = datetime.now() + timedelta(seconds=wait_seconds)
            scheduler.add_job(
                'src.nutrient_static:start_nutrient_pumps_static',
                'date',
                run_date=next_run,
                id='nutrient_start',
                replace_existing=True
            )
            logger.info(f"[STATIC] Next nutrient cycle scheduled for {next_run.strftime('%H:%M:%S')} (in {wait_duration_str})")
            
        except Exception as e:
            logger.error(f"[STATIC] Error scheduling next cycle: {e}")
            logger.exception("[STATIC] Full scheduling error details:")

def initialize_nutrient_schedule():
    """Initialize nutrient pump schedule on system startup"""
    try:
        logger.info("==== INITIALIZING NUTRIENT SCHEDULE ====")
        
        # Get configuration
        on_duration_str, wait_duration_str = get_nutrient_config()
        on_seconds = parse_duration(on_duration_str)
        
        if on_seconds == 0:
            logger.warning("[INIT] Nutrient system disabled (duration = 0)")
            return False
            
        # Start first cycle immediately on startup
        start_nutrient_pumps_static()
        logger.info("[INIT] Nutrient schedule initialized")
        return True
        
    except Exception as e:
        logger.error(f"[INIT] Error initializing nutrient schedule: {e}")
        return False

def stop_nutrient_schedule():
    """Stop all nutrient pump scheduling"""
    try:
        scheduler = get_scheduler()
        if scheduler:
            # Remove all nutrient jobs
            for job_id in ['nutrient_start', 'nutrient_stop']:
                try:
                    scheduler.remove_job(job_id)
                    logger.info(f"[STOP] Removed job: {job_id}")
                except:
                    pass  # Job might not exist
                    
        # Turn off nutrient pumps
        from src.sensors.Relay import Relay
        relay = Relay()
        if relay:
            relay.set_relay("NutrientPumpA", False)
            relay.set_relay("NutrientPumpB", False)
            relay.set_relay("NutrientPumpC", False)
            logger.info("[STOP] Nutrient pumps turned off")
            
    except Exception as e:
        logger.error(f"[STOP] Error stopping nutrient schedule: {e}")
