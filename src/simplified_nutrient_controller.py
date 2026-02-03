"""
Simplified Nutrient Controller with Dual-Layer Protection.

Uses APScheduler as primary mechanism with SQLite persistence,
plus a single failsafe timer thread as backup.

Architecture:
- Layer 1: APScheduler with static functions (no serialization issues)
- Layer 2: Simple failsafe timer thread (backup only)

Based on proven sprinkler pattern.
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
from src.nutrient_static import (
    start_nutrient_pumps_static, 
    stop_nutrient_pumps_static,
    get_nutrient_config, 
    parse_duration,
    get_scheduler
)

try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("SimplifiedNutrient", log_prefix="ripple_").logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

class SimplifiedNutrientController:
    """
    Simplified nutrient controller with dual-layer protection.
    
    Features:
    - APScheduler primary timing with SQLite persistence
    - Single failsafe timer thread as backup
    - Static functions to avoid serialization issues
    - Clean job management with consistent IDs
    """
    
    def __init__(self):
        self.scheduler = self._setup_scheduler()
        self.failsafe_timer = None
        self.is_running = False
        self.config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'device.conf')
        
    def _setup_scheduler(self):
        """Setup APScheduler with SQLite persistence"""
        try:
            return get_scheduler()
        except Exception as e:
            logger.error(f"Error setting up scheduler: {e}")
            return None
            
    def _check_hardware_running_state(self):
        """Check if nutrient pumps are actually running based on hardware state"""
        try:
            from src.sensors.Relay import Relay
            relay = Relay()
            if not relay:
                logger.warning("No relay available for state check")
                return False
                
            # Check NutrientPumpA, B, and C hardware states
            pump_a_state = relay.get_relay_state("NutrientPumpA")
            pump_b_state = relay.get_relay_state("NutrientPumpB")
            pump_c_state = relay.get_relay_state("NutrientPumpC")
            
            # Consider running if any pump is on
            hardware_running = bool(pump_a_state or pump_b_state or pump_c_state)
            logger.info(f"Hardware state check - PumpA: {pump_a_state}, PumpB: {pump_b_state}, PumpC: {pump_c_state}, Running: {hardware_running}")
            return hardware_running
            
        except Exception as e:
            logger.error(f"Error checking hardware state: {e}")
            return False
    
    def start_nutrient_cycle(self):
        """Start nutrient cycle with dual protection"""
        # Check hardware state instead of software state
        if self._check_hardware_running_state():
            logger.warning("Nutrient cycle already running (hardware check)")
            return False
            
        try:
            # Get configuration
            on_duration_str, wait_duration_str = get_nutrient_config()
            on_seconds = parse_duration(on_duration_str)
            
            if on_seconds == 0:
                logger.warning("Nutrient duration is 0, skipping cycle")
                return False
                
            # Turn on nutrient pumps
            from src.sensors.Relay import Relay
            relay = Relay()
            if not relay:
                logger.error("No relay available for nutrient pump start")
                return False
                
            relay.set_nutrient_pumps(True)
            # NutrientPumpC based on ratio configuration
            # Note: No longer using self.is_running - hardware state is truth
            logger.info(f"[CONTROLLER] Nutrient pumps started for {on_duration_str} ({on_seconds}s)")
            
            # LAYER 1: APScheduler (Primary)
            apscheduler_success = self._schedule_stop_with_apscheduler(on_seconds)
            
            # LAYER 2: Failsafe Timer (Backup)
            self._start_failsafe_timer(on_seconds)
            
            if apscheduler_success:
                logger.info("[CONTROLLER] Dual-layer protection activated (APScheduler + Failsafe)")
            else:
                logger.warning("[CONTROLLER] APScheduler failed, relying on failsafe timer")
                
            return True
            
        except Exception as e:
            logger.error(f"Error starting nutrient cycle: {e}")
            self.is_running = False
            return False
            
    def _schedule_stop_with_apscheduler(self, on_seconds):
        """Schedule stop using APScheduler (Layer 1)"""
        try:
            if not self.scheduler:
                logger.error("[CONTROLLER] No scheduler available")
                return False
                
            stop_time = datetime.now() + timedelta(seconds=on_seconds)
            # Use static function to avoid serialization issues
            from src.nutrient_static import stop_nutrient_pumps_static
            self.scheduler.add_job(
                'src.nutrient_static:stop_nutrient_pumps_static',
                'date',
                run_date=stop_time,
                id='controller_nutrient_stop',
                replace_existing=True
            )
            logger.info(f"[CONTROLLER] APScheduler stop scheduled for {stop_time.strftime('%H:%M:%S')}")
            return True
            
        except Exception as e:
            logger.error(f"[CONTROLLER] APScheduler scheduling failed: {e}")
            return False
            
    def _start_failsafe_timer(self, duration):
        """Start failsafe timer as backup (Layer 2)"""
        try:
            def failsafe_stop():
                time.sleep(duration)
                if self.is_running:  # Only stop if still running
                    logger.warning("[CONTROLLER] FAILSAFE activated - APScheduler may have failed")
                    try:
                        from src.sensors.Relay import Relay
                        relay = Relay()
                        if relay:
                            relay.set_nutrient_pumps(False)
                            self.is_running = False
                            logger.info("[CONTROLLER] FAILSAFE stopped nutrient pumps")
                            
                            # Schedule next cycle using static function
                            from src.nutrient_static import schedule_next_nutrient_cycle_static
                            schedule_next_nutrient_cycle_static()
                        else:
                            logger.error("[CONTROLLER] FAILSAFE: No relay available")
                    except Exception as e:
                        logger.error(f"[CONTROLLER] FAILSAFE error: {e}")
                        
            self.failsafe_timer = threading.Thread(target=failsafe_stop, daemon=False)
            self.failsafe_timer.start()
            logger.info(f"[CONTROLLER] Failsafe timer started: {duration}s")
            
        except Exception as e:
            logger.error(f"Error starting failsafe timer: {e}")
            
            
    def stop_current_cycle(self):
        """Stop current nutrient cycle"""
        try:
            # Note: Don't manually remove date-triggered jobs - APScheduler handles this automatically
            # after job execution. Manual removal causes race conditions.
            
            if self.is_running:
                from src.sensors.Relay import Relay
                relay = Relay()
                if relay:
                    relay.set_nutrient_pumps(False)
                    self.is_running = False
                    logger.info("[CONTROLLER] Nutrient cycle stopped manually")
                    
        except Exception as e:
            logger.error(f"Error stopping nutrient cycle: {e}")
            
    def is_cycle_running(self):
        """Check if nutrient cycle is currently running"""
        return self.is_running
        
    def get_next_scheduled_time(self):
        """Get next scheduled nutrient time"""
        try:
            if self.scheduler:
                for job in self.scheduler.get_jobs():
                    if job.id in ['nutrient_start', 'controller_nutrient_stop']:
                        return job.next_run_time
            return None
        except:
            return None
            
    def shutdown(self):
        """Shutdown controller gracefully"""
        try:
            self.stop_current_cycle()
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown()
            logger.info("[CONTROLLER] Shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

# Global controller instance (singleton pattern)
_controller_instance = None

def get_nutrient_controller():
    """Get singleton instance of nutrient controller"""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = SimplifiedNutrientController()
    return _controller_instance
