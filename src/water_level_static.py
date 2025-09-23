"""
Static functions for water level control with APScheduler.

These functions are completely independent and safe for SQLite serialization.
No lambda functions, no closures, no serialization issues.

Based on proven sensor-driven pattern (like nutrients/pH).
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
    logger = GlobalLogger("WaterLevelStatic", log_prefix="ripple_").logger
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

def get_water_level_config():
    """Get water level check interval from device.conf"""
    try:
        # Water level checks don't have duration like pumps, just monitoring interval
        # Use a reasonable default of 5 minutes for checks
        return "00:05:00"  # Check every 5 minutes
    except Exception as e:
        logger.error(f"Error reading water level config: {e}")
        return "00:05:00"  # Default: 5min interval

def parse_duration(duration_str):
    """Parse HH:MM:SS to seconds"""
    try:
        parts = duration_str.split(':')
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except:
        return 0

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

def check_water_level_and_determine_action():
    """Check water level and determine if valve action is needed"""
    try:
        # Get current water level reading from saved sensor data file
        water_level = None
        data_timestamp = None
        max_data_age = timedelta(minutes=5)
        sensor_data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'saved_sensor_data.json')
        
        try:
            if os.path.exists(sensor_data_path):
                with open(sensor_data_path, 'r') as f:
                    data = json.load(f)
                    
                    # Extract water level value from saved data
                    if ('data' in data 
                        and 'water_metrics' in data['data'] 
                        and 'water_level' in data['data']['water_metrics'] 
                        and 'measurements' in data['data']['water_metrics']['water_level'] 
                        and 'points' in data['data']['water_metrics']['water_level']['measurements']):
                        
                        points = data['data']['water_metrics']['water_level']['measurements']['points']
                        if points and len(points) > 0 and 'fields' in points[0] and 'value' in points[0]['fields']:
                            water_level = points[0]['fields']['value']
                            
                            # Check timestamp if available
                            if 'timestamp' in points[0]:
                                timestamp_str = points[0]['timestamp']
                                data_timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                
                                # Check data freshness
                                now = datetime.now().astimezone()
                                data_age = now - data_timestamp
                                
                                if data_age > max_data_age:
                                    logger.warning(f"[SENSOR] Water level data too old ({timestamp_str}), skipping")
                                    return False, None
        except Exception as e:
            logger.error(f"[SENSOR] Error reading water level data: {e}")
            
        if water_level is None:
            logger.warning("[SENSOR] Could not read water level sensor, skipping valve control")
            return False, None
            
        # Get targets and limits
        target, deadband, water_min, water_max = get_water_level_targets()
        
        logger.info(f"[SENSOR] Current water level: {water_level}%, Target: {target}%, Deadband: {deadband}%, Min: {water_min}%, Max: {water_max}%")
        
        # Determine valve action needed
        low_threshold = target - deadband
        
        if water_level < water_min:
            logger.warning(f"[SENSOR] Water level ({water_level}%) BELOW minimum ({water_min}%) - EMERGENCY REFILL needed")
            return True, True   # Need refill, emergency
        elif water_level < low_threshold:
            logger.info(f"[SENSOR] Water level ({water_level}%) below threshold ({low_threshold}%) - REFILL needed")
            return True, False  # Need refill, normal
        elif water_level > water_max:
            logger.warning(f"[SENSOR] Water level ({water_level}%) ABOVE maximum ({water_max}%) - CLOSE valve")
            return True, None   # Need to close valve (stop refill)
        else:
            logger.info(f"[SENSOR] Water level ({water_level}%) adequate - no action needed")
            return False, None
            
    except Exception as e:
        logger.error(f"[SENSOR] Error checking water level: {e}")
        logger.exception("[SENSOR] Full exception details:")
        return False, None

def check_water_level_static():
    """Static function to check water level - SENSOR DRIVEN - safe for APScheduler"""
    try:
        logger.info("==== SENSOR-DRIVEN WATER LEVEL CHECK TRIGGERED ====")
        
        # Check if action needed
        action_needed, is_emergency = check_water_level_and_determine_action()
        
        if not action_needed:
            logger.info("[SENSOR-DRIVEN] Water level adequate - no valve action needed")
            schedule_next_water_level_check_static()  # Schedule next check
            return
            
        # Get relay for valve control
        from src.sensors.Relay import Relay
        relay = Relay()
        if not relay:
            logger.error("[SENSOR-DRIVEN] No relay available for valve control")
            return
            
        # Determine valve action
        if is_emergency is True:
            # Emergency refill - open inlet valve
            relay.set_valve_outside_to_tank(True)
            logger.warning("[SENSOR-DRIVEN] EMERGENCY: Inlet valve opened for tank refill")
        elif is_emergency is False:
            # Normal refill - open inlet valve
            relay.set_valve_outside_to_tank(True)
            logger.info("[SENSOR-DRIVEN] Inlet valve opened for tank refill")
        elif is_emergency is None:
            # Stop refill - close inlet valve
            relay.set_valve_outside_to_tank(False)
            logger.info("[SENSOR-DRIVEN] Inlet valve closed (tank full)")
            
        # Schedule next check
        schedule_next_water_level_check_static()
        
    except Exception as e:
        logger.error(f"[SENSOR-DRIVEN] Error in water level logic: {e}")
        logger.exception("[SENSOR-DRIVEN] Full exception details:")

def schedule_next_water_level_check_static():
    """Schedule the next water level check using APScheduler"""
    try:
        # Get check interval
        interval_str = get_water_level_config()
        interval_seconds = parse_duration(interval_str)
        
        if interval_seconds == 0:
            logger.warning("[STATIC] Water level check interval is 0, not scheduling next check")
            return
            
        scheduler = get_scheduler()
        if not scheduler:
            logger.error("[STATIC] No scheduler available for next check scheduling")
            return
            
        next_run = datetime.now() + timedelta(seconds=interval_seconds)
        scheduler.add_job(
            check_water_level_static,
            'date',
            run_date=next_run,
            id='water_level_check',
            replace_existing=True
        )
        logger.info(f"[STATIC] Next water level check scheduled for {next_run.strftime('%H:%M:%S')} (in {interval_str})")
        
    except Exception as e:
        logger.error(f"[STATIC] Error scheduling next check: {e}")

def initialize_water_level_schedule():
    """Initialize water level monitoring on system startup"""
    try:
        logger.info("==== INITIALIZING WATER LEVEL MONITORING ====")
        
        # Start first check immediately on startup
        check_water_level_static()
        logger.info("[INIT] Water level monitoring initialized")
        return True
        
    except Exception as e:
        logger.error(f"[INIT] Error initializing water level monitoring: {e}")
        return False

def stop_water_level_schedule():
    """Stop all water level monitoring"""
    try:
        scheduler = get_scheduler()
        if scheduler:
            # Remove water level job
            try:
                scheduler.remove_job('water_level_check')
                logger.info("[STOP] Removed water level check job")
            except:
                pass  # Job might not exist
                
        # Ensure valves are in safe state (close inlet)
        from src.sensors.Relay import Relay
        relay = Relay()
        if relay:
            relay.set_valve_outside_to_tank(False)
            logger.info("[STOP] Inlet valve closed for safety")
            
    except Exception as e:
        logger.error(f"[STOP] Error stopping water level schedule: {e}")

def refresh_water_level_sensor():
    """Refresh water level sensor data"""
    try:
        logger.info("[REFRESH] Triggering water level sensor refresh")
        from src.sensors.water_level import WaterLevel
        WaterLevel.get_statuses_async()  # Request fresh data
        time.sleep(5)  # Wait for async operation
        logger.info("[REFRESH] Water level sensor refresh completed")
        return True
    except Exception as e:
        logger.error(f"[REFRESH] Error refreshing water level sensor: {e}")
        return False



