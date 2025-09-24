"""
Simplified Sprinkler Controller with Dual-Layer Protection.

Uses APScheduler as primary mechanism with SQLite persistence,
plus a single failsafe timer thread as backup.

Architecture:
- Layer 1: APScheduler with static functions (no serialization issues)
- Layer 2: Simple failsafe timer thread (backup only)

Created: 2025-09-22
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
from src.sprinkler_static import (
    start_sprinklers_static, 
    stop_sprinklers_static,
    get_sprinkler_config, 
    parse_duration,
    get_scheduler
)

try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("SimplifiedSprinkler", log_prefix="ripple_").logger
except:
    import logging
    logger = logging.getLogger(__name__)

class SimplifiedSprinklerController:
    """
    Simplified sprinkler controller with dual-layer protection.
    
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
        """Check if sprinklers are actually running based on hardware state"""
        try:
            from src.sensors.Relay import Relay
            relay = Relay()
            if not relay:
                logger.warning("No relay available for state check")
                return False
                
            # Check SprinklerA and SprinklerB hardware states
            sprinkler_a_state = relay.get_relay_state("SprinklerA")
            sprinkler_b_state = relay.get_relay_state("SprinklerB")
            
            # Consider running if either sprinkler is on
            hardware_running = bool(sprinkler_a_state or sprinkler_b_state)
            logger.info(f"Hardware state check - SprinklerA: {sprinkler_a_state}, SprinklerB: {sprinkler_b_state}, Running: {hardware_running}")
            return hardware_running
            
        except Exception as e:
            logger.error(f"Error checking hardware state: {e}")
            return False
    
    def start_sprinkler_cycle(self):
        """Start sprinkler cycle with dual protection"""
        # Check hardware state instead of software state
        if self._check_hardware_running_state():
            logger.warning("Sprinkler cycle already running (hardware check)")
            return False
            
        try:
            # Get configuration
            on_duration_str, wait_duration_str = get_sprinkler_config()
            on_seconds = parse_duration(on_duration_str)
            
            if on_seconds == 0:
                logger.warning("Sprinkler duration is 0, skipping cycle")
                return False
                
            # Turn on sprinklers
            from src.sensors.Relay import Relay
            relay = Relay()
            if not relay:
                logger.error("No relay available for sprinkler start")
                return False
                
            relay.set_sprinklers(True)
            # Note: No longer using self.is_running - hardware state is truth
            logger.info(f"[CONTROLLER] Sprinklers started for {on_duration_str} ({on_seconds}s)")
            
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
            logger.error(f"Error starting sprinkler cycle: {e}")
            self.is_running = False
            return False
            
    def _schedule_stop_with_apscheduler(self, on_seconds):
        """Schedule stop using APScheduler (Layer 1)"""
        try:
            if not self.scheduler:
                logger.error("[CONTROLLER] No scheduler available")
                return False
                
            stop_time = datetime.now() + timedelta(seconds=on_seconds)
            # Use static function that communicates with controller
            from src.sprinkler_static import stop_sprinklers_with_controller_callback
            self.scheduler.add_job(
                'src.sprinkler_static:stop_sprinklers_with_controller_callback',
                'date',
                run_date=stop_time,
                id='controller_sprinkler_stop',
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
                try:
                    logger.info(f"[FAILSAFE] Timer started, sleeping for {duration}s")
                    time.sleep(duration)
                    logger.info(f"[FAILSAFE] Timer woke up after {duration}s, checking if sprinklers still running...")
                    
                    if self.is_running:  # Only stop if still running
                        logger.warning("[FAILSAFE] ACTIVATED - APScheduler failed, emergency stop!")
                        try:
                            from src.sensors.Relay import Relay
                            relay = Relay()
                            if relay:
                                relay.set_sprinklers(False)
                                self.is_running = False
                                logger.critical("[FAILSAFE] Emergency stop completed - sprinklers turned off!")
                                
                                # Schedule next cycle using static function
                                from src.sprinkler_static import schedule_next_sprinkler_cycle_static
                                schedule_next_sprinkler_cycle_static()
                            else:
                                logger.error("[FAILSAFE] CRITICAL: No relay available for emergency stop!")
                        except Exception as e:
                            logger.error(f"[FAILSAFE] CRITICAL ERROR during emergency stop: {e}")
                    else:
                        logger.info("[FAILSAFE] APScheduler worked correctly - sprinklers already stopped")
                        
                except Exception as e:
                    logger.error(f"[FAILSAFE] Thread error: {e}")
                        
            # Cancel existing failsafe if any
            if hasattr(self, 'failsafe_timer') and self.failsafe_timer and self.failsafe_timer.is_alive():
                logger.info("[CONTROLLER] Canceling existing failsafe timer")
                
            self.failsafe_timer = threading.Thread(target=failsafe_stop, daemon=False)
            self.failsafe_timer.start()
            logger.info(f"[CONTROLLER] Failsafe timer started: {duration}s (Thread: {self.failsafe_timer.name})")
            
        except Exception as e:
            logger.error(f"[CONTROLLER] Error starting failsafe timer: {e}")
            logger.exception("Full failsafe timer error:")
            
    def _stop_sprinklers_and_mark_complete(self):
        """Stop sprinklers and mark cycle complete (called by APScheduler)"""
        try:
            if self.is_running:
                from src.sensors.Relay import Relay
                relay = Relay()
                if relay:
                    relay.set_sprinklers(False)
                    self.is_running = False
                    logger.info("[CONTROLLER] APScheduler stopped sprinklers")
                    
                    # Schedule next cycle using static function
                    from src.sprinkler_static import schedule_next_sprinkler_cycle_static
                    schedule_next_sprinkler_cycle_static()
                else:
                    logger.error("[CONTROLLER] APScheduler: No relay available")
            else:
                logger.info("[CONTROLLER] APScheduler triggered but sprinklers already stopped")
                
        except Exception as e:
            logger.error(f"[CONTROLLER] Error in APScheduler stop: {e}")
            
    def stop_current_cycle(self):
        """Stop current sprinkler cycle"""
        try:
            # Note: Don't manually remove date-triggered jobs - APScheduler handles this automatically
            # after job execution. Manual removal causes race conditions.
                    
            if self.is_running:
                from src.sensors.Relay import Relay
                relay = Relay()
                if relay:
                    relay.set_sprinklers(False)
                    self.is_running = False
                    logger.info("[CONTROLLER] Sprinkler cycle stopped manually")
                    
        except Exception as e:
            logger.error(f"Error stopping sprinkler cycle: {e}")
            
    def is_cycle_running(self):
        """Check if sprinkler cycle is currently running"""
        return self.is_running
        
    def get_next_scheduled_time(self):
        """Get next scheduled sprinkler time"""
        try:
            if self.scheduler:
                for job in self.scheduler.get_jobs():
                    if job.id in ['sprinkler_start', 'controller_sprinkler_stop']:
                        return job.next_run_time
            return None
        except:
            return None
            
    def debug_protection_status(self):
        """Debug method to check both protection layers"""
        try:
            logger.info("=== PROTECTION LAYER DEBUG STATUS ===")
            logger.info(f"Controller is_running: {self.is_running}")
            
            # Check APScheduler
            if self.scheduler:
                jobs = self.scheduler.get_jobs()
                logger.info(f"APScheduler jobs: {len(jobs)}")
                for job in jobs:
                    logger.info(f"  Job: {job.id}, Next: {job.next_run_time}")
            else:
                logger.error("APScheduler: NOT AVAILABLE")
                
            # Check failsafe timer
            if hasattr(self, 'failsafe_timer') and self.failsafe_timer:
                logger.info(f"Failsafe timer alive: {self.failsafe_timer.is_alive()}")
                logger.info(f"Failsafe timer name: {self.failsafe_timer.name}")
            else:
                logger.error("Failsafe timer: NOT AVAILABLE")
                
            logger.info("=== END DEBUG STATUS ===")
            
        except Exception as e:
            logger.error(f"Error in debug status: {e}")

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

def get_sprinkler_controller():
    """Get singleton instance of sprinkler controller"""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = SimplifiedSprinklerController()
    return _controller_instance
