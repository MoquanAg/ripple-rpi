"""
Simplified Water Level Controller with Dual-Layer Protection.

Uses APScheduler as primary mechanism with SQLite persistence,
plus a single failsafe timer thread as backup.

Architecture:
- Layer 1: APScheduler with static functions (no serialization issues)
- Layer 2: Simple failsafe timer thread (backup only)

Based on proven sensor-driven pattern (like nutrients/pH).
Created: 2025-09-23
Author: Linus-style simplification
"""

import threading
import time
import configparser
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

# Import static functions
from src.water_level_static import (
    check_water_level_static, 
    get_water_level_config, 
    parse_duration,
    get_scheduler
)

try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("SimplifiedWaterLevel", log_prefix="ripple_").logger
except:
    import logging
    logger = logging.getLogger(__name__)

class SimplifiedWaterLevelController:
    """
    Simplified water level controller with dual-layer protection.
    
    Features:
    - APScheduler primary timing with SQLite persistence
    - Single failsafe timer thread as backup
    - Static functions to avoid serialization issues
    - Clean job management with consistent IDs
    """
    
    def __init__(self):
        """Initialize the simplified water level controller"""
        self.is_monitoring = False
        self.current_thread = None
        self.scheduler = get_scheduler()
        logger.info("SimplifiedWaterLevelController initialized")
    
    def start_water_level_monitoring(self):
        """Start water level monitoring with dual protection"""
        if self.is_monitoring:
            logger.warning("Water level monitoring already running")
            return False
            
        try:
            # Get configuration
            interval_str = get_water_level_config()
            interval_seconds = parse_duration(interval_str)
            
            if interval_seconds == 0:
                logger.warning("Water level check interval is 0, skipping monitoring")
                return False
                
            self.is_monitoring = True
            logger.info(f"[CONTROLLER] Water level monitoring started (checking every {interval_str})")
            
            # Layer 1: APScheduler (primary)
            apscheduler_success = self._schedule_check_with_apscheduler(interval_seconds)
            
            # Layer 2: Failsafe timer thread (backup)
            self._start_failsafe_timer(interval_seconds)
            
            # Call static function to perform first check
            check_water_level_static()
            
            return True
            
        except Exception as e:
            self.is_monitoring = False
            logger.error(f"Error starting water level monitoring: {e}")
            logger.exception("Full exception details:")
            return False
    
    def _schedule_check_with_apscheduler(self, interval_seconds):
        """Schedule regular checks using APScheduler"""
        try:
            if not self.scheduler:
                logger.error("No scheduler available for APScheduler check")
                return False
                
            # Note: We don't schedule a specific stop time like pumps
            # Water level monitoring is continuous, the static function handles its own rescheduling
            logger.info(f"[CONTROLLER] APScheduler monitoring active (interval: {interval_seconds}s)")
            return True
            
        except Exception as e:
            logger.error(f"Error scheduling APScheduler check: {e}")
            return False
    
    def _start_failsafe_timer(self, interval_seconds):
        """Start failsafe timer thread"""
        try:
            # For water level, we want a longer failsafe interval (multiple check periods)
            failsafe_seconds = interval_seconds * 3  # If no activity for 3x interval, restart
            
            def failsafe_monitor():
                while self.is_monitoring:
                    time.sleep(failsafe_seconds)
                    if self.is_monitoring:
                        logger.info(f"[FAILSAFE] Water level monitoring heartbeat check ({failsafe_seconds}s)")
                        # For water level, we don't need emergency stops like pumps
                        # Just log that monitoring is still active
                        
            self.current_thread = threading.Thread(target=failsafe_monitor, daemon=True)
            self.current_thread.start()
            logger.info(f"[CONTROLLER] Failsafe monitor started ({failsafe_seconds}s interval)")
            
        except Exception as e:
            logger.error(f"Error starting failsafe monitor: {e}")
    
    def stop_monitoring(self):
        """Manually stop water level monitoring"""
        try:
            if not self.is_monitoring:
                logger.info("No water level monitoring currently running")
                return True
                
            logger.info("[CONTROLLER] Manual stop requested")
            
            # Note: Don't manually remove recurring jobs - let APScheduler manage them
            # Manual removal of active jobs can cause race conditions
            
            # Ensure valves are in safe state
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                relay.set_valve_outside_to_tank(False)  # Close inlet valve for safety
                logger.info("[CONTROLLER] Inlet valve closed for safety")
            
            self.is_monitoring = False
            return True
            
        except Exception as e:
            logger.error(f"Error stopping monitoring manually: {e}")
            self.is_monitoring = False
            return False
    
    def get_status(self):
        """Get current controller status"""
        return {
            'is_monitoring': self.is_monitoring,
            'has_scheduler': self.scheduler is not None,
            'has_thread': self.current_thread is not None and self.current_thread.is_alive()
        }
    
    def force_check_now(self):
        """Force an immediate water level check"""
        try:
            logger.info("[CONTROLLER] Forcing immediate water level check")
            check_water_level_static()
            return True
        except Exception as e:
            logger.error(f"Error forcing check: {e}")
            return False
    
    def shutdown(self):
        """Shutdown the controller"""
        try:
            logger.info("[CONTROLLER] Shutting down water level controller")
            
            # Stop monitoring
            self.stop_monitoring()
            
            # Stop scheduler
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown()
                logger.info("[CONTROLLER] Scheduler stopped")
                
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

# Global controller instance (singleton pattern)
_controller_instance = None

def get_water_level_controller():
    """Get singleton instance of water level controller"""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = SimplifiedWaterLevelController()
    return _controller_instance



