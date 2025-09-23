"""
Static functions for mixing pump control with APScheduler.

These functions are completely independent and safe for SQLite serialization.
No lambda functions, no closures, no serialization issues.

Based on proven sprinkler pattern.
Created: 2025-09-23
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

def get_mixing_config():
    """Get mixing pump configuration from device.conf"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)
        
        # Get operational values (second value after comma)
        duration_str = config.get('Mixing', 'mixing_duration')
        interval_str = config.get('Mixing', 'mixing_interval')
        
        duration = duration_str.split(',')[1].strip()
        interval = interval_str.split(',')[1].strip()
        
        return duration, interval
    except Exception as e:
        logger.error(f"Error reading mixing config: {e}")
        return "00:20:00", "02:00:00"  # Default: 20min duration, 2hr interval

def parse_duration(duration_str):
    """Parse HH:MM:SS to seconds"""
    try:
        parts = duration_str.split(':')
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except:
        return 0

def start_mixing_pump_static():
    """Static function to start mixing pump - safe for APScheduler"""
    try:
        logger.info("==== STATIC MIXING PUMP START TRIGGERED ====")
        
        # Get configuration
        duration_str, interval_str = get_mixing_config()
        duration_seconds = parse_duration(duration_str)
        
        if duration_seconds == 0:
            logger.warning("[STATIC] Mixing pump duration is 0, skipping")
            return
            
        # Turn on mixing pump
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            logger.error("[STATIC] No relay available for mixing pump start")
            return
            
        relay.set_mixing_pump(True)
        logger.info(f"[STATIC] Mixing pump started for {duration_str} ({duration_seconds}s)")
        
        # Schedule stop
        schedule_mixing_stop_static(duration_seconds)
        
    except Exception as e:
        logger.error(f"[STATIC] Error starting mixing pump: {e}")
        logger.exception("[STATIC] Full exception details:")

def stop_mixing_pump_static():
    """Static function to stop mixing pump - safe for APScheduler"""
    try:
        logger.info("==== STATIC MIXING PUMP STOP TRIGGERED ====")
        
        # Turn off mixing pump
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            logger.error("[STATIC] No relay available for mixing pump stop")
            return
            
        relay.set_mixing_pump(False)
        logger.info("[STATIC] Mixing pump stopped")
        
        # Schedule next cycle
        schedule_next_mixing_cycle_static()
        
    except Exception as e:
        logger.error(f"[STATIC] Error stopping mixing pump: {e}")
        logger.exception("[STATIC] Full exception details:")

def schedule_mixing_stop_static(duration_seconds):
    """Schedule mixing pump stop using APScheduler"""
    try:
        scheduler = get_scheduler()
        if not scheduler:
            logger.error("[STATIC] No scheduler available for stop scheduling")
            return
            
        stop_time = datetime.now() + timedelta(seconds=duration_seconds)
        scheduler.add_job(
            stop_mixing_pump_static,
            'date',
            run_date=stop_time,
            id='mixing_stop',
            replace_existing=True
        )
        logger.info(f"[STATIC] Mixing pump stop scheduled for {stop_time.strftime('%H:%M:%S')}")
        
    except Exception as e:
        logger.error(f"[STATIC] Error scheduling mixing pump stop: {e}")

def schedule_next_mixing_cycle_static():
    """Schedule the next mixing pump cycle using APScheduler"""
    try:
        # Get configuration
        duration_str, interval_str = get_mixing_config()
        interval_seconds = parse_duration(interval_str)
        
        if interval_seconds == 0:
            logger.warning("[STATIC] Mixing interval is 0, not scheduling next cycle")
            return
            
        scheduler = get_scheduler()
        if not scheduler:
            logger.error("[STATIC] No scheduler available for next cycle scheduling")
            return
            
        next_run = datetime.now() + timedelta(seconds=interval_seconds)
        scheduler.add_job(
            start_mixing_pump_static,
            'date',
            run_date=next_run,
            id='mixing_start',
            replace_existing=True
        )
        logger.info(f"[STATIC] Next mixing cycle scheduled for {next_run.strftime('%H:%M:%S')} (in {interval_str})")
        
    except Exception as e:
        logger.error(f"[STATIC] Error scheduling next cycle: {e}")

def initialize_mixing_schedule():
    """Initialize mixing pump schedule on system startup"""
    try:
        logger.info("==== INITIALIZING MIXING SCHEDULE ====")
        
        # Get configuration
        duration_str, interval_str = get_mixing_config()
        duration_seconds = parse_duration(duration_str)
        
        if duration_seconds == 0:
            logger.warning("[INIT] Mixing system disabled (duration = 0)")
            return False
            
        # Start first cycle immediately on startup
        start_mixing_pump_static()
        logger.info("[INIT] Mixing schedule initialized")
        return True
        
    except Exception as e:
        logger.error(f"[INIT] Error initializing mixing schedule: {e}")
        return False

def stop_mixing_schedule():
    """Stop all mixing pump scheduling"""
    try:
        scheduler = get_scheduler()
        if scheduler:
            # Remove all mixing jobs
            for job_id in ['mixing_start', 'mixing_stop']:
                try:
                    scheduler.remove_job(job_id)
                    logger.info(f"[STOP] Removed job: {job_id}")
                except:
                    pass  # Job might not exist
                    
        # Turn off mixing pump
        from src.sensors.Relay import Relay
        relay = Relay()
        if relay:
            relay.set_mixing_pump(False)
            logger.info("[STOP] Mixing pump turned off")
            
    except Exception as e:
        logger.error(f"[STOP] Error stopping mixing schedule: {e}")
