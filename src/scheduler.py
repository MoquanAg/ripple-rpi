from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import globals
from globals import logger
import configparser
import os
import time

class RippleScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.config = globals.DEVICE_CONFIG_FILE
        self.jobs = {}
        self.mixing_pump_running = False
        self.mixing_pump_end_time = None
        self.last_nutrient_pump_time = None
        
    def start(self):
        """Start the scheduler and initialize all scheduled tasks"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Ripple scheduler started")
            
            # Initialize all scheduled tasks
            self._initialize_mixing_schedule()
            self._initialize_nutrient_schedule()
            self._initialize_sprinkler_schedule()
            self._initialize_fresh_water_dilution()
            self._initialize_auto_refill()
            
            # Log initial schedule status
            self._log_all_schedules()
            
    def shutdown(self):
        """Safely shutdown the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Ripple scheduler shutdown")
            
    def _time_to_seconds(self, time_str):
        """Convert HH:MM:SS format to seconds"""
        hours, minutes, seconds = map(int, time_str.split(':'))
        return hours * 3600 + minutes * 60 + seconds
            
    def _initialize_mixing_schedule(self):
        """Initialize mixing pump schedule based on device.conf settings"""
        try:
            mixing_interval = self.config.get('MIXING', 'mixing_interval').split(',')[0]
            mixing_duration = self.config.get('MIXING', 'mixing_duration').split(',')[0]
            trigger_duration = self.config.get('MIXING', 'trigger_mixing_duration').split(',')[0]
            
            # Validate durations
            if mixing_interval == "00:00:00" or mixing_duration == "00:00:00" or trigger_duration == "00:00:00":
                logger.warning("Mixing schedule not initialized: zero duration detected")
                return
                
            # Convert to seconds
            mixing_interval_seconds = self._time_to_seconds(mixing_interval)
            mixing_duration_seconds = self._time_to_seconds(mixing_duration)
            trigger_duration_seconds = self._time_to_seconds(trigger_duration)
            
            if mixing_interval_seconds == 0 or mixing_duration_seconds == 0 or trigger_duration_seconds == 0:
                logger.warning("Mixing schedule not initialized: zero duration after conversion")
                return
            
            # Add regular mixing job
            self.scheduler.add_job(
                self._run_mixing_cycle,
                IntervalTrigger(seconds=mixing_interval_seconds),
                id='mixing_cycle',
                max_instances=1
            )
            
            # Add UV sterilization job (every 6 hours)
            self.scheduler.add_job(
                self._run_uv_sterilization,
                CronTrigger(hour='*/6'),
                id='uv_sterilization',
                max_instances=1
            )
            
            logger.info(f"Mixing pump schedule initialized: {mixing_interval} interval, {mixing_duration} duration")
        except Exception as e:
            logger.error(f"Failed to initialize mixing schedule: {e}")
            
    def _initialize_nutrient_schedule(self):
        """Initialize nutrient pump schedule based on device.conf settings"""
        try:
            wait_duration = self.config.get('NutrientPump', 'nutrient_pump_wait_duration').split(',')[0]
            on_duration = self.config.get('NutrientPump', 'nutrient_pump_on_duration').split(',')[0]
            ph_wait_duration = self.config.get('NutrientPump', 'ph_pump_wait_duration').split(',')[0]
            ph_on_duration = self.config.get('NutrientPump', 'ph_pump_on_duration').split(',')[0]
            
            # Validate durations
            if (wait_duration == "00:00:00" or on_duration == "00:00:00" or 
                ph_wait_duration == "00:00:00" or ph_on_duration == "00:00:00"):
                logger.warning("Nutrient schedule not initialized: zero duration detected")
                return
                
            # Convert to seconds
            wait_seconds = self._time_to_seconds(wait_duration)
            on_seconds = self._time_to_seconds(on_duration)
            ph_wait_seconds = self._time_to_seconds(ph_wait_duration)
            ph_on_seconds = self._time_to_seconds(ph_on_duration)
            
            if wait_seconds == 0 or on_seconds == 0 or ph_wait_seconds == 0 or ph_on_seconds == 0:
                logger.warning("Nutrient schedule not initialized: zero duration after conversion")
                return
            
            # Add nutrient pump job
            self.scheduler.add_job(
                self._run_nutrient_cycle,
                IntervalTrigger(seconds=wait_seconds),
                id='nutrient_cycle',
                max_instances=1
            )
            
            # Add pH pump job
            self.scheduler.add_job(
                self._run_ph_cycle,
                IntervalTrigger(seconds=ph_wait_seconds),
                id='ph_cycle',
                max_instances=1
            )
            
            logger.info(f"Nutrient schedule initialized: {wait_duration} wait, {on_duration} on")
            logger.info(f"pH schedule initialized: {ph_wait_duration} wait, {ph_on_duration} on")
        except Exception as e:
            logger.error(f"Failed to initialize nutrient schedule: {e}")
            
    def _initialize_sprinkler_schedule(self):
        """Initialize sprinkler schedule based on device.conf settings"""
        try:
            on_duration = self.config.get('Sprinkler', 'sprinkler_on_duration').split(',')[0]
            wait_duration = self.config.get('Sprinkler', 'sprinkler_wait_duration').split(',')[0]
            
            # Validate durations
            if on_duration == "00:00:00" or wait_duration == "00:00:00":
                logger.warning("Sprinkler schedule not initialized: zero duration detected")
                return
                
            # Convert to seconds
            on_seconds = self._time_to_seconds(on_duration)
            wait_seconds = self._time_to_seconds(wait_duration)
            
            if on_seconds == 0 or wait_seconds == 0:
                logger.warning("Sprinkler schedule not initialized: zero duration after conversion")
                return
            
            # Add sprinkler job
            self.scheduler.add_job(
                self._run_sprinkler_cycle,
                IntervalTrigger(seconds=wait_seconds),
                id='sprinkler_cycle',
                max_instances=1
            )
            
            logger.info(f"Sprinkler schedule initialized: {on_duration} on, {wait_duration} wait")
        except Exception as e:
            logger.error(f"Failed to initialize sprinkler schedule: {e}")
            
    def _initialize_fresh_water_dilution(self):
        """Initialize fresh water dilution monitoring"""
        try:
            # Fresh water dilution runs every 5 minutes by default
            self.scheduler.add_job(
                self._check_fresh_water_dilution,
                IntervalTrigger(seconds=300),  # Check every 5 minutes
                id='fresh_water_dilution',
                max_instances=1
            )
            logger.info("Fresh water dilution monitoring initialized")
        except Exception as e:
            logger.error(f"Failed to initialize fresh water dilution monitoring: {e}")
            
    def _initialize_auto_refill(self):
        """Initialize auto refill monitoring"""
        try:
            # Auto refill checks every minute by default
            self.scheduler.add_job(
                self._check_auto_refill,
                IntervalTrigger(seconds=60),  # Check every minute
                id='auto_refill',
                max_instances=1
            )
            logger.info("Auto refill monitoring initialized")
        except Exception as e:
            logger.error(f"Failed to initialize auto refill monitoring: {e}")
            
    def _run_mixing_cycle(self):
        """Execute mixing pump cycle"""
        try:
            if not self.mixing_pump_running:
                mixing_duration = self.config.get('MIXING', 'mixing_duration').split(',')[0]
                mixing_duration_seconds = self._time_to_seconds(mixing_duration)
                
                if mixing_duration_seconds == 0:
                    logger.warning("Skipping mixing cycle: zero duration")
                    return
                    
                self.mixing_pump_running = True
                self.mixing_pump_end_time = datetime.now() + timedelta(seconds=mixing_duration_seconds)
                
                # Start mixing pump
                logger.info(f"Starting mixing pump for {mixing_duration}")
                
                # Simulate mixing duration
                time.sleep(mixing_duration_seconds)
                
                # Stop mixing pump
                self.mixing_pump_running = False
                self.mixing_pump_end_time = None
                logger.info("Mixing pump cycle completed")
        except Exception as e:
            logger.error(f"Error in mixing cycle: {e}")
            self.mixing_pump_running = False
            self.mixing_pump_end_time = None
            
    def _run_uv_sterilization(self):
        """Execute UV sterilization cycle"""
        try:
            if not self.mixing_pump_running:
                self.mixing_pump_running = True
                logger.info("Starting mixing pump for UV sterilization")
                
                # UV sterilization runs for 20 minutes
                uv_duration = 20 * 60  # 20 minutes in seconds
                self.mixing_pump_end_time = datetime.now() + timedelta(seconds=uv_duration)
                
                # Simulate UV duration
                time.sleep(uv_duration)
                
                # Stop mixing pump
                self.mixing_pump_running = False
                self.mixing_pump_end_time = None
                logger.info("UV sterilization cycle completed")
        except Exception as e:
            logger.error(f"Error in UV sterilization cycle: {e}")
            self.mixing_pump_running = False
            self.mixing_pump_end_time = None
            
    def _run_nutrient_cycle(self):
        """Execute nutrient cycle"""
        try:
            on_duration = self.config.get('NutrientPump', 'nutrient_pump_on_duration').split(',')[0]
            on_seconds = self._time_to_seconds(on_duration)
            trigger_duration = self.config.get('MIXING', 'trigger_mixing_duration').split(',')[0]
            trigger_seconds = self._time_to_seconds(trigger_duration)
            
            if on_seconds == 0:
                logger.warning("Skipping nutrient cycle: zero duration")
                return
                
            # Record the time when nutrient pump starts
            self.last_nutrient_pump_time = datetime.now()
            
            # Check if mixing pump is running and has less than trigger duration remaining
            if self.mixing_pump_running and self.mixing_pump_end_time:
                remaining_seconds = (self.mixing_pump_end_time - datetime.now()).total_seconds()
                if remaining_seconds < trigger_seconds:
                    # Extend mixing pump duration
                    extension_seconds = trigger_seconds - remaining_seconds
                    self.mixing_pump_end_time = self.mixing_pump_end_time + timedelta(seconds=extension_seconds)
                    logger.info(f"Extending mixing pump by {extension_seconds} seconds to ensure proper mixing after nutrient addition")
            elif not self.mixing_pump_running:
                # Start mixing pump if not running
                self.mixing_pump_running = True
                self.mixing_pump_end_time = datetime.now() + timedelta(seconds=trigger_seconds)
                logger.info(f"Starting mixing pump for {trigger_duration} after nutrient pump activation")
            
            # Implement nutrient pump logic here
            logger.info(f"Running nutrient cycle for {on_duration}")
        except Exception as e:
            logger.error(f"Error in nutrient cycle: {e}")
            
    def _run_ph_cycle(self):
        """Execute pH adjustment cycle"""
        try:
            on_duration = self.config.get('NutrientPump', 'ph_pump_on_duration').split(',')[0]
            on_seconds = self._time_to_seconds(on_duration)
            trigger_duration = self.config.get('MIXING', 'trigger_mixing_duration').split(',')[0]
            trigger_seconds = self._time_to_seconds(trigger_duration)
            
            if on_seconds == 0:
                logger.warning("Skipping pH cycle: zero duration")
                return
                
            # Record the time when pH pump starts
            self.last_nutrient_pump_time = datetime.now()
            
            # Check if mixing pump is running and has less than trigger duration remaining
            if self.mixing_pump_running and self.mixing_pump_end_time:
                remaining_seconds = (self.mixing_pump_end_time - datetime.now()).total_seconds()
                if remaining_seconds < trigger_seconds:
                    # Extend mixing pump duration
                    extension_seconds = trigger_seconds - remaining_seconds
                    self.mixing_pump_end_time = self.mixing_pump_end_time + timedelta(seconds=extension_seconds)
                    logger.info(f"Extending mixing pump by {extension_seconds} seconds to ensure proper mixing after pH adjustment")
            elif not self.mixing_pump_running:
                # Start mixing pump if not running
                self.mixing_pump_running = True
                self.mixing_pump_end_time = datetime.now() + timedelta(seconds=trigger_seconds)
                logger.info(f"Starting mixing pump for {trigger_duration} after pH pump activation")
            
            # Implement pH pump logic here
            logger.info(f"Running pH cycle for {on_duration}")
        except Exception as e:
            logger.error(f"Error in pH cycle: {e}")
            
    def _run_sprinkler_cycle(self):
        """Execute sprinkler cycle"""
        try:
            on_duration = self.config.get('Sprinkler', 'sprinkler_on_duration').split(',')[0]
            on_seconds = self._time_to_seconds(on_duration)
            
            if on_seconds == 0:
                logger.warning("Skipping sprinkler cycle: zero duration")
                return
                
            # Implement sprinkler logic here
            logger.info(f"Running sprinkler cycle for {on_duration}")
        except Exception as e:
            logger.error(f"Error in sprinkler cycle: {e}")
            
    def _check_fresh_water_dilution(self):
        """Check if fresh water dilution is needed"""
        try:
            # Implement fresh water dilution check logic here
            logger.info("Checking if fresh water dilution is needed")
        except Exception as e:
            logger.error(f"Error in fresh water dilution check: {e}")
            
    def _check_auto_refill(self):
        """Check if auto refill is needed"""
        try:
            # Implement auto refill check logic here
            logger.info("Checking if auto refill is needed")
        except Exception as e:
            logger.error(f"Error in auto refill check: {e}")
            
    def get_scheduled_jobs(self):
        """Get information about all scheduled jobs"""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                'id': job.id,
                'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger),
                'max_instances': job.max_instances
            })
        return jobs 

    def _log_schedule_details(self, job_id):
        """Log details about a scheduled job"""
        try:
            job = self.scheduler.get_job(job_id)
            if job:
                next_run = job.next_run_time
                trigger = str(job.trigger)
                logger.info(f"Schedule details for {job_id}:")
                logger.info(f"  Next run time: {next_run}")
                logger.info(f"  Trigger: {trigger}")
                logger.info(f"  Max instances: {job.max_instances}")
            else:
                logger.warning(f"No schedule found for {job_id}")
        except Exception as e:
            logger.error(f"Failed to log schedule details: {e}")
            
    def _log_all_schedules(self):
        """Log details about all scheduled jobs"""
        try:
            logger.info("Current schedule status:")
            for job in self.scheduler.get_jobs():
                self._log_schedule_details(job.id)
        except Exception as e:
            logger.error(f"Failed to log all schedules: {e}")
            
    def update_configuration(self, section, key, value):
        """Update configuration and restart affected schedules"""
        try:
            # Update the configuration
            self.config.set(section, key, value)
            
            # Determine which schedules need to be restarted
            if section == 'MIXING':
                self._restart_mixing_schedule()
                self._log_schedule_details('mixing_cycle')
                self._log_schedule_details('uv_sterilization')
            elif section == 'NutrientPump':
                self._restart_nutrient_schedule()
                self._log_schedule_details('nutrient_cycle')
                self._log_schedule_details('ph_cycle')
            elif section == 'Sprinkler':
                self._restart_sprinkler_schedule()
                self._log_schedule_details('sprinkler_cycle')
            elif section == 'Recirculation':
                self._restart_recirculation_schedule()
                self._log_schedule_details('recirculation_cycle')
                
            logger.info(f"Configuration updated: {section}.{key} = {value}")
            return True
        except Exception as e:
            logger.error(f"Failed to update configuration: {e}")
            return False
            
    def _restart_mixing_schedule(self):
        """Restart mixing pump schedule with new configuration"""
        try:
            # Remove existing jobs
            if 'mixing_cycle' in self.jobs:
                self.scheduler.remove_job('mixing_cycle')
            if 'uv_sterilization' in self.jobs:
                self.scheduler.remove_job('uv_sterilization')
                
            # Reinitialize the schedule
            self._initialize_mixing_schedule()
            logger.info("Mixing schedule restarted with new configuration")
        except Exception as e:
            logger.error(f"Failed to restart mixing schedule: {e}")
            
    def _restart_nutrient_schedule(self):
        """Restart nutrient pump schedule with new configuration"""
        try:
            # Remove existing jobs
            if 'nutrient_cycle' in self.jobs:
                self.scheduler.remove_job('nutrient_cycle')
            if 'ph_cycle' in self.jobs:
                self.scheduler.remove_job('ph_cycle')
                
            # Reinitialize the schedule
            self._initialize_nutrient_schedule()
            logger.info("Nutrient schedule restarted with new configuration")
        except Exception as e:
            logger.error(f"Failed to restart nutrient schedule: {e}")
            
    def _restart_sprinkler_schedule(self):
        """Restart sprinkler schedule with new configuration"""
        try:
            # Remove existing job
            if 'sprinkler_cycle' in self.jobs:
                self.scheduler.remove_job('sprinkler_cycle')
                
            # Reinitialize the schedule
            self._initialize_sprinkler_schedule()
            logger.info("Sprinkler schedule restarted with new configuration")
        except Exception as e:
            logger.error(f"Failed to restart sprinkler schedule: {e}")
            
    def _restart_recirculation_schedule(self):
        """Restart recirculation schedule with new configuration"""
        try:
            # Remove existing job
            if 'recirculation_cycle' in self.jobs:
                self.scheduler.remove_job('recirculation_cycle')
                
            # Reinitialize the schedule
            self._initialize_recirculation_schedule()
            logger.info("Recirculation schedule restarted with new configuration")
        except Exception as e:
            logger.error(f"Failed to restart recirculation schedule: {e}")
            
    def handle_manual_command(self, command_type, duration=None):
        """Handle manual commands from the API"""
        try:
            if command_type == 'mixing':
                if duration:
                    # Convert duration to seconds
                    duration_seconds = self._time_to_seconds(duration)
                    if duration_seconds > 0:
                        # Start mixing pump for specified duration
                        self.mixing_pump_running = True
                        self.mixing_pump_end_time = datetime.now() + timedelta(seconds=duration_seconds)
                        logger.info(f"Manual mixing pump started for {duration}")
                        logger.info(f"  Scheduled to end at: {self.mixing_pump_end_time}")
                else:
                    # Stop mixing pump
                    self.mixing_pump_running = False
                    self.mixing_pump_end_time = None
                    logger.info("Manual mixing pump stopped")
                    
            elif command_type == 'nutrient':
                if duration:
                    # Convert duration to seconds
                    duration_seconds = self._time_to_seconds(duration)
                    if duration_seconds > 0:
                        # Start nutrient pump for specified duration
                        self._run_nutrient_cycle()
                        logger.info(f"Manual nutrient pump started for {duration}")
                        self._log_schedule_details('nutrient_cycle')
                        
            elif command_type == 'ph':
                if duration:
                    # Convert duration to seconds
                    duration_seconds = self._time_to_seconds(duration)
                    if duration_seconds > 0:
                        # Start pH pump for specified duration
                        self._run_ph_cycle()
                        logger.info(f"Manual pH pump started for {duration}")
                        self._log_schedule_details('ph_cycle')
                        
            elif command_type == 'sprinkler':
                if duration:
                    # Convert duration to seconds
                    duration_seconds = self._time_to_seconds(duration)
                    if duration_seconds > 0:
                        # Start sprinkler for specified duration
                        self._run_sprinkler_cycle()
                        logger.info(f"Manual sprinkler started for {duration}")
                        self._log_schedule_details('sprinkler_cycle')
                        
            # Log all schedules after manual command
            self._log_all_schedules()
            return True
        except Exception as e:
            logger.error(f"Failed to handle manual command: {e}")
            return False 