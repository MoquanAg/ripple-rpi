"""
Simplified pH Controller with Dual-Layer Protection.

Uses APScheduler as primary mechanism with SQLite persistence,
plus a single failsafe timer thread as backup.

Architecture:
- Layer 1: APScheduler with static functions (no serialization issues)
- Layer 2: Simple failsafe timer thread (backup only)

Based on proven nutrient pattern.
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
from src.ph_static import (
    start_ph_pump_static, 
    stop_ph_pump_static,
    get_ph_config, 
    parse_duration,
    get_scheduler
)

try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("SimplifiedpH", log_prefix="ripple_").logger
except:
    import logging
    logger = logging.getLogger(__name__)

class SimplifiedpHController:
    """
    Simplified pH controller with dual-layer protection.
    
    Features:
    - APScheduler primary timing with SQLite persistence
    - Single failsafe timer thread as backup
    - Static functions to avoid serialization issues
    - Clean job management with consistent IDs
    """
    
    def __init__(self):
        """Initialize the simplified pH controller"""
        self.is_running = False
        self.current_thread = None
        self.scheduler = get_scheduler()
        logger.info("SimplifiedpHController initialized")
    
    def _check_hardware_running_state(self):
        """Check if pH pumps are actually running based on hardware state"""
        try:
            from src.sensors.Relay import Relay
            relay = Relay()
            if not relay:
                logger.warning("No relay available for state check")
                return False
                
            # Check pHUpPump and pHDownPump hardware states
            ph_up_state = relay.get_relay_state("pHUpPump")
            ph_down_state = relay.get_relay_state("pHDownPump")
            
            # Consider running if either pump is on
            hardware_running = bool(ph_up_state or ph_down_state)
            logger.info(f"Hardware state check - pHUpPump: {ph_up_state}, pHDownPump: {ph_down_state}, Running: {hardware_running}")
            return hardware_running
            
        except Exception as e:
            logger.error(f"Error checking hardware state: {e}")
            return False
    
    def start_ph_cycle(self):
        """Start pH cycle with dual protection"""
        # Check hardware state instead of software state
        if self._check_hardware_running_state():
            logger.warning("pH cycle already running (hardware check)")
            return False
            
        try:
            # Get configuration
            duration_str, wait_duration_str = get_ph_config()
            duration_seconds = parse_duration(duration_str)
            
            if duration_seconds == 0:
                logger.warning("pH duration is 0, skipping cycle")
                return False
                
            # Turn on appropriate pH pump via static function
            from src.sensors.Relay import Relay
            relay = Relay()
            if not relay:
                logger.error("No relay available for pH pump start")
                return False
                
            # Note: No longer using self.is_running - hardware state is truth
            logger.info(f"[CONTROLLER] pH pump started for {duration_str} ({duration_seconds}s)")
            
            # Layer 1: APScheduler (primary)
            apscheduler_success = self._schedule_stop_with_apscheduler(duration_seconds)
            
            # Layer 2: Failsafe timer thread (backup)
            self._start_failsafe_timer(duration_seconds)
            
            # Call static function to actually start the pumps
            start_ph_pump_static()
            
            return True
            
        except Exception as e:
            self.is_running = False
            logger.error(f"Error starting pH cycle: {e}")
            logger.exception("Full exception details:")
            return False
    
    def _schedule_stop_with_apscheduler(self, duration_seconds):
        """Schedule pump stop using APScheduler"""
        try:
            if not self.scheduler:
                logger.error("No scheduler available for APScheduler stop")
                return False
                
            stop_time = datetime.now() + timedelta(seconds=duration_seconds)
            self.scheduler.add_job(
                'src.simplified_ph_controller:SimplifiedpHController._stop_ph_pump_and_mark_complete',
                'date',
                run_date=stop_time,
                id='controller_ph_stop',
                replace_existing=True
            )
            logger.info(f"[CONTROLLER] APScheduler stop scheduled for {stop_time.strftime('%H:%M:%S')}")
            return True
            
        except Exception as e:
            logger.error(f"Error scheduling APScheduler stop: {e}")
            return False
    
    def _start_failsafe_timer(self, duration_seconds):
        """Start failsafe timer thread"""
        try:
            # Add 30 seconds buffer for failsafe
            failsafe_seconds = duration_seconds + 30
            
            def failsafe_stop():
                time.sleep(failsafe_seconds)
                if self.is_running:
                    logger.warning(f"[FAILSAFE] pH pump still running after {failsafe_seconds}s - emergency stop!")
                    self._emergency_stop_ph_pump()
                    
            self.current_thread = threading.Thread(target=failsafe_stop, daemon=True)
            self.current_thread.start()
            logger.info(f"[CONTROLLER] Failsafe timer started ({failsafe_seconds}s)")
            
        except Exception as e:
            logger.error(f"Error starting failsafe timer: {e}")
    
    def _stop_ph_pump_and_mark_complete(self):
        """Stop pH pump and mark cycle complete (called by APScheduler)"""
        try:
            logger.info("[CONTROLLER] APScheduler triggered stop")
            
            # Turn off pH pumps
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                relay.set_ph_plus_pump(False)
                relay.set_ph_minus_pump(False)
                logger.info("[CONTROLLER] pH pumps stopped via controller")
            
            # Mark as not running
            self.is_running = False
            
            # Schedule next cycle via static function
            from src.ph_static import schedule_next_ph_cycle_static
            schedule_next_ph_cycle_static()
            
        except Exception as e:
            logger.error(f"Error in controller stop: {e}")
            self.is_running = False  # Always reset the flag
    
    def _emergency_stop_ph_pump(self):
        """Emergency stop for failsafe"""
        try:
            logger.warning("[FAILSAFE] Emergency pH pump stop")
            
            # Turn off pH pumps
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                relay.set_ph_plus_pump(False)
                relay.set_ph_minus_pump(False)
                logger.info("[FAILSAFE] pH pumps stopped")
            
            # Mark as not running
            self.is_running = False
            
            # Schedule next cycle
            from src.ph_static import schedule_next_ph_cycle_static
            schedule_next_ph_cycle_static()
            
        except Exception as e:
            logger.error(f"Error in emergency stop: {e}")
            self.is_running = False  # Always reset the flag
    
    def stop_current_cycle(self):
        """Manually stop current cycle"""
        try:
            if not self.is_running:
                logger.info("No pH cycle currently running")
                return True
                
            logger.info("[CONTROLLER] Manual stop requested")
            
            # Note: Don't manually remove date-triggered jobs - APScheduler handles this automatically
            # after job execution. Manual removal causes race conditions.
            
            # Stop pumps
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                relay.set_ph_plus_pump(False)
                relay.set_ph_minus_pump(False)
                logger.info("[CONTROLLER] pH pumps stopped manually")
            
            self.is_running = False
            return True
            
        except Exception as e:
            logger.error(f"Error stopping cycle manually: {e}")
            self.is_running = False
            return False
    
    def get_status(self):
        """Get current controller status"""
        return {
            'is_running': self.is_running,
            'has_scheduler': self.scheduler is not None,
            'has_thread': self.current_thread is not None and self.current_thread.is_alive()
        }
    
    def shutdown(self):
        """Shutdown the controller"""
        try:
            logger.info("[CONTROLLER] Shutting down pH controller")
            
            # Stop current cycle
            self.stop_current_cycle()
            
            # Stop scheduler
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown()
                logger.info("[CONTROLLER] Scheduler stopped")
                
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

# Global controller instance (singleton pattern)
_controller_instance = None

def get_ph_controller():
    """Get singleton instance of pH controller"""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = SimplifiedpHController()
    return _controller_instance