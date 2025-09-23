"""
Static functions for pH pump control with APScheduler.

These functions are completely independent and safe for SQLite serialization.
No lambda functions, no closures, no serialization issues.

Based on proven nutrient pattern.
Created: 2025-09-23
Author: Linus-style simplification
"""

import configparser
import os
import time
import json
from datetime import datetime, timedelta
# APScheduler imports removed - using global scheduler from globals.py

try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("PhStatic", log_prefix="ripple_").logger
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

def get_ph_config():
    """Get pH pump configuration from device.conf"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)
        
        # Get operational values (second value after comma)
        on_str = config.get('NutrientPump', 'ph_pump_on_duration')
        wait_str = config.get('NutrientPump', 'ph_pump_wait_duration')
        
        on_duration = on_str.split(',')[1].strip()
        wait_duration = wait_str.split(',')[1].strip()
        
        return on_duration, wait_duration
    except Exception as e:
        logger.error(f"Error reading pH config: {e}")
        return "00:00:02", "00:02:00"  # Default: 2s ON, 2min wait

def parse_duration(duration_str):
    """Parse HH:MM:SS to seconds"""
    try:
        parts = duration_str.split(':')
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except:
        return 0

def get_ph_targets():
    """Get pH target, deadband, and limits from device.conf"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        config = configparser.ConfigParser()
        config.read(config_path)
        
        # Get operational values (second value after comma)
        target_str = config.get('pH', 'ph_target')
        deadband_str = config.get('pH', 'ph_deadband')
        
        target = float(target_str.split(',')[1].strip())
        deadband = float(deadband_str.split(',')[1].strip())
        
        # Get pH limits if available
        try:
            min_str = config.get('pH', 'ph_min')
            max_str = config.get('pH', 'ph_max')
            ph_min = float(min_str.split(',')[1].strip())
            ph_max = float(max_str.split(',')[1].strip())
        except:
            # Default limits if not configured
            ph_min = 4.0
            ph_max = 8.0
        
        return target, deadband, ph_min, ph_max
    except Exception as e:
        logger.error(f"Error reading pH targets: {e}")
        return 6.0, 0.2, 4.0, 8.0  # Default: target=6.0, deadband=0.2, min=4.0, max=8.0

def check_if_ph_adjustment_needed():
    """Check pH levels to determine if adjustment is needed and which pump to use"""
    try:
        # Get current pH reading from log file (same approach as scheduler)
        ph_value = None
        data_timestamp = None
        max_data_age = timedelta(minutes=2)
        ph_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'sensor_data.data.water_metrics.ph.log')
        
        try:
            if os.path.exists(ph_log_path):
                with open(ph_log_path, 'r') as f:
                    lines = f.readlines()
                    if lines:
                        last_line = lines[-1].strip()
                        if last_line:
                            parts = last_line.split('\t', 2)
                            if len(parts) >= 3:
                                timestamp_str = parts[0]
                                json_data = parts[2]
                                data = json.loads(json_data)
                                
                                if ('measurements' in data 
                                    and 'points' in data['measurements'] 
                                    and len(data['measurements']['points']) > 0
                                    and 'fields' in data['measurements']['points'][0]
                                    and 'value' in data['measurements']['points'][0]['fields']):
                                    ph_value = float(data['measurements']['points'][0]['fields']['value'])
                                    data_timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except Exception as e:
            logger.error(f"[SENSOR] Error reading pH log: {e}")
            
        if ph_value is None:
            logger.warning("[SENSOR] Could not read pH sensor, skipping adjustment decision")
            return False, None
            
        # Check data freshness
        if data_timestamp and datetime.now(data_timestamp.tzinfo) - data_timestamp > max_data_age:
            logger.warning(f"[SENSOR] pH data too old ({data_timestamp}), skipping adjustment")
            return False, None
            
        # Get targets and limits
        target_ph, ph_deadband, ph_min, ph_max = get_ph_targets()
        
        logger.info(f"[SENSOR] Current pH: {ph_value}, Target: {target_ph}, Deadband: {ph_deadband}, Min: {ph_min}, Max: {ph_max}")
        
        # Determine action needed (using fixed deadband logic)
        if ph_value > ph_max:
            logger.info(f"[SENSOR] pH ({ph_value}) above maximum ({ph_max}) - pH DOWN needed")
            return True, False  # Need pH Down
        elif ph_value < ph_min:
            logger.info(f"[SENSOR] pH ({ph_value}) below minimum ({ph_min}) - pH UP needed")
            return True, True   # Need pH Up
        elif ph_value > (target_ph + ph_deadband):
            logger.info(f"[SENSOR] pH ({ph_value}) above high threshold ({target_ph + ph_deadband}) - pH DOWN needed")
            return True, False  # Need pH Down
        elif ph_value < (target_ph - ph_deadband):
            logger.info(f"[SENSOR] pH ({ph_value}) below low threshold ({target_ph - ph_deadband}) - pH UP needed")
            return True, True   # Need pH Up
        else:
            logger.info(f"[SENSOR] pH ({ph_value}) within deadband - no adjustment needed")
            return False, None
            
    except Exception as e:
        logger.error(f"[SENSOR] Error checking pH levels: {e}")
        logger.exception("[SENSOR] Full exception details:")
        return False, None

def start_ph_pump_static():
    """Static function to start pH pump - SENSOR DRIVEN - safe for APScheduler"""
    try:
        logger.info("==== SENSOR-DRIVEN pH CHECK TRIGGERED ====")
        
        # Check if adjustment needed
        adjustment_needed, use_ph_up = check_if_ph_adjustment_needed()
        
        if not adjustment_needed:
            logger.info("[SENSOR-DRIVEN] pH levels adequate - skipping adjustment")
            schedule_next_ph_cycle_static()  # Schedule next check
            return
            
        # Get configuration
        on_duration_str, wait_duration_str = get_ph_config()
        on_seconds = parse_duration(on_duration_str)
        
        if on_seconds == 0:
            logger.warning("[SENSOR-DRIVEN] pH pump duration is 0, skipping")
            return
            
        # Turn on appropriate pH pump
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            logger.error("[SENSOR-DRIVEN] No relay available for pH pump start")
            return
            
        if use_ph_up:
            result = relay.set_ph_plus_pump(True)
            pump_type = "pH UP"
            logger.info(f"[SENSOR-DRIVEN] {pump_type} pump started for {on_duration_str} ({on_seconds}s)")
        else:
            result = relay.set_ph_minus_pump(True)  
            pump_type = "pH DOWN"
            logger.info(f"[SENSOR-DRIVEN] {pump_type} pump started for {on_duration_str} ({on_seconds}s)")
            
        # Schedule stop
        schedule_ph_stop_static(on_seconds, use_ph_up)
        
    except Exception as e:
        logger.error(f"[SENSOR-DRIVEN] Error in pH pump logic: {e}")
        logger.exception("[SENSOR-DRIVEN] Full exception details:")

def stop_ph_pump_static():
    """Static function to stop pH pumps - safe for APScheduler"""
    try:
        logger.info("==== STATIC pH PUMP STOP TRIGGERED ====")
        
        # Turn off both pH pumps (safety)
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            logger.error("[STATIC] No relay available for pH pump stop")
            return
            
        relay.set_ph_plus_pump(False)
        relay.set_ph_minus_pump(False)
        logger.info("[STATIC] pH pumps stopped")
        
        # Schedule next cycle
        schedule_next_ph_cycle_static()
        
    except Exception as e:
        logger.error(f"[STATIC] Error stopping pH pump: {e}")
        logger.exception("[STATIC] Full exception details:")

def schedule_ph_stop_static(on_seconds, use_ph_up):
    """Schedule pH pump stop using APScheduler"""
    try:
        scheduler = get_scheduler()
        if not scheduler:
            logger.error("[STATIC] No scheduler available for stop scheduling")
            return
            
        stop_time = datetime.now() + timedelta(seconds=on_seconds)
        scheduler.add_job(
            stop_ph_pump_static,
            'date',
            run_date=stop_time,
            id='ph_stop',
            replace_existing=True
        )
        pump_type = "pH UP" if use_ph_up else "pH DOWN"
        logger.info(f"[STATIC] {pump_type} pump stop scheduled for {stop_time.strftime('%H:%M:%S')}")
        
    except Exception as e:
        logger.error(f"[STATIC] Error scheduling pH pump stop: {e}")

def schedule_next_ph_cycle_static():
    """Schedule the next pH cycle using APScheduler"""
    try:
        # Get configuration
        on_duration_str, wait_duration_str = get_ph_config()
        wait_seconds = parse_duration(wait_duration_str)
        
        if wait_seconds == 0:
            logger.warning("[STATIC] pH wait duration is 0, not scheduling next cycle")
            return
            
        scheduler = get_scheduler()
        if not scheduler:
            logger.error("[STATIC] No scheduler available for next cycle scheduling")
            return
            
        next_run = datetime.now() + timedelta(seconds=wait_seconds)
        scheduler.add_job(
            start_ph_pump_static,
            'date',
            run_date=next_run,
            id='ph_start',
            replace_existing=True
        )
        logger.info(f"[STATIC] Next pH cycle scheduled for {next_run.strftime('%H:%M:%S')} (in {wait_duration_str})")
        
    except Exception as e:
        logger.error(f"[STATIC] Error scheduling next cycle: {e}")

def initialize_ph_schedule():
    """Initialize pH schedule on system startup"""
    try:
        logger.info("==== INITIALIZING pH SCHEDULE ====")
        
        # Get configuration
        on_duration_str, wait_duration_str = get_ph_config()
        on_seconds = parse_duration(on_duration_str)
        
        if on_seconds == 0:
            logger.warning("[INIT] pH system disabled (duration = 0)")
            return False
            
        # Start first cycle immediately on startup
        start_ph_pump_static()
        logger.info("[INIT] pH schedule initialized")
        return True
        
    except Exception as e:
        logger.error(f"[INIT] Error initializing pH schedule: {e}")
        return False

def stop_ph_schedule():
    """Stop all pH pump scheduling"""
    try:
        scheduler = get_scheduler()
        if scheduler:
            # Remove all pH jobs
            for job_id in ['ph_start', 'ph_stop']:
                try:
                    scheduler.remove_job(job_id)
                    logger.info(f"[STOP] Removed job: {job_id}")
                except:
                    pass  # Job might not exist
                    
        # Turn off pH pumps
        from src.sensors.Relay import Relay
        relay = Relay()
        if relay:
            relay.set_ph_plus_pump(False)
            relay.set_ph_minus_pump(False)
            logger.info("[STOP] pH pumps turned off")
            
    except Exception as e:
        logger.error(f"[STOP] Error stopping pH schedule: {e}")