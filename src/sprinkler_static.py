"""
Static functions for sprinkler control with APScheduler.

These functions are completely independent and safe for SQLite serialization.
No lambda functions, no closures, no serialization issues.

Created: 2025-09-22
Author: Linus-style simplification
"""

import configparser
import os
import time
from datetime import datetime, timedelta
# APScheduler imports removed - using global scheduler from globals.py

# Global logger import
try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("SprinklerStatic", log_prefix="ripple_").logger
except:
    import logging
    logger = logging.getLogger(__name__)

def get_scheduler():
    """Get the global scheduler instance from globals.py"""
    try:
        from src.globals import scheduler
        return scheduler
    except Exception as e:
        logger.error(f"Error getting global scheduler: {e}")
        return None

def get_sprinkler_config():
    """Get sprinkler configuration from device.conf"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)
        
        # Get operational values (second value after comma)
        on_str = config.get('Sprinkler', 'sprinkler_on_duration')
        wait_str = config.get('Sprinkler', 'sprinkler_wait_duration')
        
        on_duration = on_str.split(',')[1].strip()
        wait_duration = wait_str.split(',')[1].strip()
        
        return on_duration, wait_duration
    except Exception as e:
        logger.error(f"Error reading sprinkler config: {e}")
        return "00:00:00", "00:00:00"

def is_sprinkler_scheduling_enabled():
    """Check if automatic sprinkler scheduling is enabled in config"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)
        
        if not config.has_option('Sprinkler', 'sprinkler_scheduling_enabled'):
            # Default to enabled if option doesn't exist (backward compatibility)
            return True
            
        enabled_str = config.get('Sprinkler', 'sprinkler_scheduling_enabled')
        # Get operational value (second value after comma)
        operational_value = enabled_str.split(',')[1].strip().lower()
        return operational_value == 'true'
    except Exception as e:
        logger.error(f"Error checking sprinkler_scheduling_enabled: {e}")
        return True  # Default to enabled on error

def parse_duration(duration_str):
    """Parse HH:MM:SS to seconds"""
    try:
        parts = duration_str.split(':')
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except:
        return 0

def start_sprinklers_static():
    """Static function to start sprinklers - safe for APScheduler"""
    try:
        logger.info("==== STATIC SPRINKLER START TRIGGERED ====")
        
        # Check if scheduling is enabled
        if not is_sprinkler_scheduling_enabled():
            logger.info("[STATIC] Sprinkler scheduling is DISABLED - skipping start")
            return
        
        # Get configuration
        on_duration_str, wait_duration_str = get_sprinkler_config()
        on_seconds = parse_duration(on_duration_str)
        
        if on_seconds == 0:
            logger.warning("[STATIC] Sprinkler duration is 0, skipping")
            return
            
        # Turn on sprinklers
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            logger.error("[STATIC] No relay available for sprinkler start")
            return
            
        relay.set_sprinklers(True)
        logger.info(f"[STATIC] Sprinklers started for {on_duration_str} ({on_seconds}s)")
        
        # Schedule stop
        schedule_sprinkler_stop_static(on_seconds)
        
    except Exception as e:
        logger.error(f"[STATIC] Error starting sprinklers: {e}")
        logger.exception("[STATIC] Full exception details:")

def stop_sprinklers_static():
    """Static function to stop sprinklers - safe for APScheduler"""
    try:
        logger.info("==== STATIC SPRINKLER STOP TRIGGERED ====")
        
        # Turn off sprinklers
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            logger.error("[STATIC] No relay available for sprinkler stop")
            return
            
        relay.set_sprinklers(False)
        logger.info("[STATIC] Sprinklers stopped")
        
        # Schedule next cycle
        schedule_next_sprinkler_cycle_static()
        
    except Exception as e:
        logger.error(f"[STATIC] Error stopping sprinklers: {e}")
        logger.exception("[STATIC] Full exception details:")

def stop_sprinklers_with_controller_callback():
    """Static function that stops sprinklers and notifies controller"""
    try:
        logger.info("==== STATIC SPRINKLER STOP WITH CONTROLLER CALLBACK ====")
        
        # Turn off sprinklers
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            logger.error("[STATIC] No relay available for sprinkler stop")
            return
            
        relay.set_sprinklers(False)
        logger.info("[STATIC] Sprinklers stopped by APScheduler")
        
        # Notify controller that sprinklers stopped
        try:
            from src.simplified_sprinkler_controller import get_sprinkler_controller
            controller = get_sprinkler_controller()
            controller.is_running = False
            logger.info("[STATIC] Controller state updated: is_running = False")
        except Exception as e:
            logger.error(f"[STATIC] Could not update controller state: {e}")
        
        # Schedule next cycle
        schedule_next_sprinkler_cycle_static()
        
    except Exception as e:
        logger.error(f"[STATIC] Error stopping sprinklers with callback: {e}")
        logger.exception("[STATIC] Full exception details:")

def schedule_sprinkler_stop_static(on_seconds):
    """Schedule sprinkler stop using APScheduler"""
    try:
        scheduler = get_scheduler()
        if not scheduler:
            logger.error("[STATIC] No scheduler available for stop scheduling")
            return
            
        stop_time = datetime.now() + timedelta(seconds=on_seconds)
        scheduler.add_job(
            'src.sprinkler_static:stop_sprinklers_static',
            'date',
            run_date=stop_time,
            id='sprinkler_stop',
            replace_existing=True
        )
        logger.info(f"[STATIC] Sprinkler stop scheduled for {stop_time.strftime('%H:%M:%S')}")
        
    except Exception as e:
        logger.error(f"[STATIC] Error scheduling sprinkler stop: {e}")

def schedule_next_sprinkler_cycle_static():
    """Schedule the next sprinkler cycle using APScheduler"""
    try:
        # Check if scheduling is enabled
        if not is_sprinkler_scheduling_enabled():
            logger.info("[STATIC] Sprinkler scheduling is DISABLED - not scheduling next cycle")
            return
        
        # Get configuration
        on_duration_str, wait_duration_str = get_sprinkler_config()
        wait_seconds = parse_duration(wait_duration_str)
        
        if wait_seconds == 0:
            logger.warning("[STATIC] Wait duration is 0, not scheduling next cycle")
            return
            
        scheduler = get_scheduler()
        if not scheduler:
            logger.error("[STATIC] No scheduler available for next cycle scheduling")
            return
            
        next_run = datetime.now() + timedelta(seconds=wait_seconds)
        scheduler.add_job(
            'src.sprinkler_static:start_sprinklers_static',
            'date',
            run_date=next_run,
            id='sprinkler_start',
            replace_existing=True
        )
        logger.info(f"[STATIC] Next sprinkler cycle scheduled for {next_run.strftime('%H:%M:%S')} (in {wait_duration_str})")
        
    except Exception as e:
        logger.error(f"[STATIC] Error scheduling next cycle: {e}")

def initialize_sprinkler_schedule():
    """Initialize sprinkler schedule on system startup"""
    try:
        logger.info("==== INITIALIZING SPRINKLER SCHEDULE ====")
        
        # Get configuration
        on_duration_str, wait_duration_str = get_sprinkler_config()
        on_seconds = parse_duration(on_duration_str)
        
        if on_seconds == 0:
            logger.warning("[INIT] Sprinkler system disabled (duration = 0)")
            return False
            
        # Start first cycle immediately on startup
        start_sprinklers_static()
        logger.info("[INIT] Sprinkler schedule initialized")
        return True
        
    except Exception as e:
        logger.error(f"[INIT] Error initializing sprinkler schedule: {e}")
        return False

def stop_sprinkler_schedule():
    """Stop all sprinkler scheduling"""
    try:
        scheduler = get_scheduler()
        if scheduler:
            # Remove all sprinkler jobs
            for job_id in ['sprinkler_start', 'sprinkler_stop']:
                try:
                    scheduler.remove_job(job_id)
                    logger.info(f"[STOP] Removed job: {job_id}")
                except:
                    pass  # Job might not exist
                    
        # Turn off sprinklers
        from src.sensors.Relay import Relay
        relay = Relay()
        if relay:
            relay.set_sprinklers(False)
            logger.info("[STOP] Sprinklers turned off")
            
    except Exception as e:
        logger.error(f"[STOP] Error stopping sprinkler schedule: {e}")
