"""
Simplified Mixing Controller with Dual-Layer Protection.

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
from src.mixing_static import (
    start_mixing_pump_static, 
    stop_mixing_pump_static,
    get_mixing_config, 
    parse_duration,
    get_scheduler
)

try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("SimplifiedMixing", log_prefix="ripple_").logger
except:
    import logging
    logger = logging.getLogger(__name__)

class SimplifiedMixingController:
    """
    Simplified mixing controller with dual-layer protection.
    
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
            
    def start_mixing_cycle(self):
        """Start mixing cycle with dual protection"""
        if self.is_running:
            logger.warning("Mixing cycle already running")
            return False
            
        try:
            # Get configuration
            duration_str, interval_str = get_mixing_config()
            duration_seconds = parse_duration(duration_str)
            
            if duration_seconds == 0:
                logger.warning("Mixing duration is 0, skipping cycle")
                return False
                
            # Turn on mixing pump
            from src.sensors.Relay import Relay
            relay = Relay()
            if not relay:
                logger.error("No relay available for mixing pump start")
                return False
                
            relay.set_mixing_pump(True)
            self.is_running = True
            logger.info(f"[CONTROLLER] Mixing pump started for {duration_str} ({duration_seconds}s)")
            
            # LAYER 1: APScheduler (Primary)
            apscheduler_success = self._schedule_stop_with_apscheduler(duration_seconds)
            
            # LAYER 2: Failsafe Timer (Backup)
            self._start_failsafe_timer(duration_seconds)
            
            if apscheduler_success:
                logger.info("[CONTROLLER] Dual-layer protection activated (APScheduler + Failsafe)")
            else:
                logger.warning("[CONTROLLER] APScheduler failed, relying on failsafe timer")
                
            return True
            
        except Exception as e:
            logger.error(f"Error starting mixing cycle: {e}")
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
            from src.mixing_static import stop_mixing_pump_static
            self.scheduler.add_job(
                stop_mixing_pump_static,
                'date',
                run_date=stop_time,
                id='controller_mixing_stop',
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
                            relay.set_mixing_pump(False)
                            self.is_running = False
                            logger.info("[CONTROLLER] FAILSAFE stopped mixing pump")
                            
                            # Schedule next cycle using static function
                            from src.mixing_static import schedule_next_mixing_cycle_static
                            schedule_next_mixing_cycle_static()
                        else:
                            logger.error("[CONTROLLER] FAILSAFE: No relay available")
                    except Exception as e:
                        logger.error(f"[CONTROLLER] FAILSAFE error: {e}")
                        
            self.failsafe_timer = threading.Thread(target=failsafe_stop, daemon=True)
            self.failsafe_timer.start()
            logger.info(f"[CONTROLLER] Failsafe timer started: {duration}s")
            
        except Exception as e:
            logger.error(f"Error starting failsafe timer: {e}")
            
    def _stop_mixing_pump_and_mark_complete(self):
        """Stop mixing pump and mark cycle complete (called by APScheduler)"""
        try:
            if self.is_running:
                from src.sensors.Relay import Relay
                relay = Relay()
                if relay:
                    relay.set_mixing_pump(False)
                    self.is_running = False
                    logger.info("[CONTROLLER] APScheduler stopped mixing pump")
                    
                    # Schedule next cycle using static function
                    from src.mixing_static import schedule_next_mixing_cycle_static
                    schedule_next_mixing_cycle_static()
                else:
                    logger.error("[CONTROLLER] APScheduler: No relay available")
            else:
                logger.info("[CONTROLLER] APScheduler triggered but mixing pump already stopped")
                
        except Exception as e:
            logger.error(f"[CONTROLLER] Error in APScheduler stop: {e}")
            
    def stop_current_cycle(self):
        """Stop current mixing cycle"""
        try:
            # Note: Don't manually remove date-triggered jobs - APScheduler handles this automatically
            # after job execution. Manual removal causes race conditions.
                    
            if self.is_running:
                from src.sensors.Relay import Relay
                relay = Relay()
                if relay:
                    relay.set_mixing_pump(False)
                    self.is_running = False
                    logger.info("[CONTROLLER] Mixing cycle stopped manually")
                    
        except Exception as e:
            logger.error(f"Error stopping mixing cycle: {e}")
            
    def is_cycle_running(self):
        """Check if mixing cycle is currently running"""
        return self.is_running
        
    def get_next_scheduled_time(self):
        """Get next scheduled mixing time"""
        try:
            if self.scheduler:
                for job in self.scheduler.get_jobs():
                    if job.id in ['mixing_start', 'controller_mixing_stop']:
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

def get_mixing_controller():
    """Get singleton instance of mixing controller"""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = SimplifiedMixingController()
    return _controller_instance
