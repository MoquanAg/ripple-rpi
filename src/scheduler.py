from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import globals
from globals import logger
import configparser
import os
import time
import json

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
            mixing_interval = self.config.get('Mixing', 'mixing_interval').split(',')[0]
            mixing_duration = self.config.get('Mixing', 'mixing_duration').split(',')[0]
            trigger_duration = self.config.get('Mixing', 'trigger_mixing_duration').split(',')[0]
            
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
                mixing_duration = self.config.get('Mixing', 'mixing_duration').split(',')[0]
                mixing_duration_seconds = self._time_to_seconds(mixing_duration)
                
                if mixing_duration_seconds == 0:
                    logger.warning("Skipping mixing cycle: zero duration")
                    return
                
                from src.sensors.Relay import Relay
                relay = Relay()
                if not relay:
                    logger.warning("Failed to start mixing cycle: relay not available")
                    return
                    
                # Start mixing pump
                relay.set_mixing_pump(True)
                self.mixing_pump_running = True
                self.mixing_pump_end_time = datetime.now() + timedelta(seconds=mixing_duration_seconds)
                logger.info(f"Starting mixing pump for {mixing_duration}")
                
                # Schedule job to stop the mixing pump after duration
                self.scheduler.add_job(
                    self._stop_mixing_pump,
                    'date',
                    run_date=self.mixing_pump_end_time,
                    id='mixing_stop_job',
                    replace_existing=True
                )
                logger.info(f"Mixing pump scheduled to stop at: {self.mixing_pump_end_time}")
        except Exception as e:
            logger.error(f"Error in mixing cycle: {e}")
            self.mixing_pump_running = False
            self.mixing_pump_end_time = None
            
    def _run_uv_sterilization(self):
        """Execute UV sterilization cycle"""
        try:
            if not self.mixing_pump_running:
                # UV sterilization runs for 20 minutes
                uv_duration = 20 * 60  # 20 minutes in seconds
                
                from src.sensors.Relay import Relay
                relay = Relay()
                if not relay:
                    logger.warning("Failed to start UV sterilization: relay not available")
                    return
                
                # Start mixing pump for UV sterilization
                relay.set_mixing_pump(True)
                self.mixing_pump_running = True
                self.mixing_pump_end_time = datetime.now() + timedelta(seconds=uv_duration)
                logger.info("Starting mixing pump for UV sterilization")
                
                # Schedule job to stop the mixing pump after duration
                self.scheduler.add_job(
                    self._stop_mixing_pump,
                    'date',
                    run_date=self.mixing_pump_end_time,
                    id='uv_stop_job',
                    replace_existing=True
                )
                logger.info(f"UV sterilization scheduled to stop at: {self.mixing_pump_end_time}")
        except Exception as e:
            logger.error(f"Error in UV sterilization cycle: {e}")
            self.mixing_pump_running = False
            self.mixing_pump_end_time = None
            
    def _run_nutrient_cycle(self):
        """Execute nutrient cycle"""
        try:
            # Get EC data from saved sensor data file instead of directly from sensors
            ec_value = None
            sensor_data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'saved_sensor_data.json')
            
            try:
                if os.path.exists(sensor_data_path):
                    with open(sensor_data_path, 'r') as f:
                        data = json.load(f)
                        # Extract EC value from saved data
                        if ('data' in data 
                            and 'water_metrics' in data['data'] 
                            and 'ec' in data['data']['water_metrics'] 
                            and 'measurements' in data['data']['water_metrics']['ec'] 
                            and 'points' in data['data']['water_metrics']['ec']['measurements']):
                            
                            points = data['data']['water_metrics']['ec']['measurements']['points']
                            if points and len(points) > 0 and 'fields' in points[0] and 'value' in points[0]['fields']:
                                ec_value = points[0]['fields']['value']
                                logger.info(f"Current EC reading from saved data: {ec_value}")
            except Exception as e:
                logger.error(f"Error reading saved EC data: {e}")
                
            if ec_value is None:
                logger.warning("No EC readings available, cannot determine if nutrient cycle should run")
                return
            
            # Now proceed with the original logic but using ec_value instead of reading from sensors
            try:
                ec_target = float(self.config.get('EC', 'ec_target').split(',')[0])
                ec_deadband = float(self.config.get('EC', 'ec_deadband').split(',')[0])
                ec_max = float(self.config.get('EC', 'ec_max').split(',')[0])
                ec_min = float(self.config.get('EC', 'ec_min').split(',')[0])
                logger.info(f"EC targets - target: {ec_target}, deadband: {ec_deadband}, min: {ec_min}, max: {ec_max}")
                
                # Check if EC is too high
                if ec_value > ec_max:
                    logger.warning(f"EC value {ec_value} is above maximum threshold {ec_max}, but will continue to monitor")
                elif ec_value > (ec_target + ec_deadband):
                    logger.warning(f"EC value {ec_value} is above target range, skipping nutrient cycle")
                    return
                
                # Explicitly check if EC is too low - this is when we WANT to run the nutrient pumps
                if ec_value < ec_min:
                    logger.warning(f"EC value {ec_value} is below minimum threshold {ec_min}, nutrient addition required")
                elif ec_value < (ec_target - ec_deadband):
                    logger.info(f"EC value {ec_value} is below target range, nutrient addition required")
                else:
                    logger.info(f"EC value {ec_value} is within target range ({ec_target}±{ec_deadband}), no nutrient addition needed")
                    return
                
            except Exception as e:
                logger.error(f"Failed to get EC targets from config: {e}")
                return

            on_duration = self.config.get('NutrientPump', 'nutrient_pump_on_duration').split(',')[0]
            on_seconds = self._time_to_seconds(on_duration)
            trigger_duration = self.config.get('Mixing', 'trigger_mixing_duration').split(',')[0]
            trigger_seconds = self._time_to_seconds(trigger_duration)
            
            if on_seconds == 0:
                logger.warning("Skipping nutrient cycle: zero duration")
                return
                
            # Get relay instance
            from src.sensors.Relay import Relay
            relay = Relay()
            if not relay:
                logger.warning("Failed to start nutrient cycle: relay not available")
                return
                
            # Record the time when nutrient pump starts
            self.last_nutrient_pump_time = datetime.now()
            
            # Start nutrient pump
            relay.set_nutrient_pumps(True)
            logger.info(f"Running nutrient cycle for {on_duration}")
            
            # Schedule to stop after on_duration
            self.scheduler.add_job(
                self._stop_nutrient_pump,
                'date',
                run_date=datetime.now() + timedelta(seconds=on_seconds),
                id='scheduled_nutrient_stop',
                replace_existing=True
            )
            
            # Check if mixing pump is running and has less than trigger duration remaining
            if self.mixing_pump_running and self.mixing_pump_end_time:
                remaining_seconds = (self.mixing_pump_end_time - datetime.now()).total_seconds()
                if remaining_seconds < trigger_seconds:
                    # Extend mixing pump duration
                    extension_seconds = trigger_seconds - remaining_seconds
                    self.mixing_pump_end_time = self.mixing_pump_end_time + timedelta(seconds=extension_seconds)
                    
                    # Update the scheduled stop time
                    self.scheduler.remove_job('mixing_stop_job')
                    self.scheduler.add_job(
                        self._stop_mixing_pump,
                        'date',
                        run_date=self.mixing_pump_end_time,
                        id='mixing_stop_job',
                        replace_existing=True
                    )
                    
                    logger.info(f"Extending mixing pump by {extension_seconds} seconds to ensure proper mixing after nutrient addition")
            elif not self.mixing_pump_running:
                # Start mixing pump if not running
                relay.set_mixing_pump(True)
                self.mixing_pump_running = True
                self.mixing_pump_end_time = datetime.now() + timedelta(seconds=trigger_seconds)
                
                # Schedule mixing pump to stop
                self.scheduler.add_job(
                    self._stop_mixing_pump,
                    'date',
                    run_date=self.mixing_pump_end_time,
                    id='mixing_stop_job',
                    replace_existing=True
                )
                
                logger.info(f"Starting mixing pump for {trigger_duration} after nutrient pump activation")
        except Exception as e:
            logger.error(f"Error in nutrient cycle: {e}")
            
    def _run_ph_cycle(self):
        """Execute pH adjustment cycle"""
        try:
            # Get pH data from saved sensor data file instead of directly from sensors
            ph_value = None
            sensor_data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'saved_sensor_data.json')
            
            try:
                if os.path.exists(sensor_data_path):
                    with open(sensor_data_path, 'r') as f:
                        data = json.load(f)
                        # Extract pH value from saved data
                        if ('data' in data 
                            and 'water_metrics' in data['data'] 
                            and 'ph' in data['data']['water_metrics'] 
                            and 'measurements' in data['data']['water_metrics']['ph'] 
                            and 'points' in data['data']['water_metrics']['ph']['measurements']):
                            
                            points = data['data']['water_metrics']['ph']['measurements']['points']
                            if points and len(points) > 0 and 'fields' in points[0] and 'value' in points[0]['fields']:
                                ph_value = points[0]['fields']['value']
                                logger.info(f"Current pH reading from saved data: {ph_value}")
            except Exception as e:
                logger.error(f"Error reading saved pH data: {e}")
                
            if ph_value is None:
                logger.warning("No pH readings available, cannot determine which pump to use")
                return
                
            # Get configuration parameters
            on_duration = self.config.get('NutrientPump', 'ph_pump_on_duration').split(',')[0]
            on_seconds = self._time_to_seconds(on_duration)
            trigger_duration = self.config.get('Mixing', 'trigger_mixing_duration').split(',')[0]
            trigger_seconds = self._time_to_seconds(trigger_duration)
            
            if on_seconds == 0:
                logger.warning("Skipping pH cycle: zero duration")
                return
                
            # Get relay instance
            from src.sensors.Relay import Relay
            relay = Relay()
            if not relay:
                logger.warning("Failed to start pH cycle: relay not available")
                return
                
            # Record the time when pH pump starts
            self.last_nutrient_pump_time = datetime.now()
            
            # Get pH targets from configuration
            try:
                target_ph = float(self.config.get('pH', 'ph_target').split(',')[0])
                ph_deadband = float(self.config.get('pH', 'ph_deadband').split(',')[0])
                ph_min = float(self.config.get('pH', 'ph_min').split(',')[0])
                ph_max = float(self.config.get('pH', 'ph_max').split(',')[0])
                logger.info(f"pH targets - target: {target_ph}, deadband: {ph_deadband}, min: {ph_min}, max: {ph_max}")
                
                # CRITICAL FIX: Instead of skipping adjustment when pH is outside safe range,
                # we should prioritize bringing it back into range
                
                # Determine which pump to use based on pH value
                if ph_value > ph_max:
                    # DEFINITELY use pH DOWN when above maximum
                    use_ph_up = False
                    logger.warning(f"pH value {ph_value} is ABOVE maximum threshold {ph_max}, using pH DOWN pump")
                elif ph_value < ph_min:
                    # DEFINITELY use pH UP when below minimum
                    use_ph_up = True
                    logger.warning(f"pH value {ph_value} is BELOW minimum threshold {ph_min}, using pH UP pump")
                elif ph_value > (target_ph + (ph_deadband / 2)):
                    # Use pH Down within safe range but above target+deadband
                    use_ph_up = False
                    logger.info(f"Current pH ({ph_value}) is above high threshold ({target_ph + (ph_deadband / 2)}), using pH DOWN pump")
                elif ph_value < (target_ph - (ph_deadband / 2)):
                    # Use pH Up within safe range but below target-deadband
                    use_ph_up = True
                    logger.info(f"Current pH ({ph_value}) is below low threshold ({target_ph - (ph_deadband / 2)}), using pH UP pump")
                else:
                    logger.info(f"Current pH ({ph_value}) is within deadband of target ({target_ph}), no pH adjustment needed")
                    return
            except Exception as e:
                logger.error(f"Failed to get pH targets from config: {e}")
                return
            
            # Debug relay assignments
            if relay.relay_assignments:
                if 'pHDownPump' in relay.relay_assignments:
                    logger.info(f"pHDownPump relay assignment: {relay.relay_assignments['pHDownPump']}")
                else:
                    found = False
                    for key in relay.relay_assignments:
                        if key.lower() == 'phdownpump':
                            logger.info(f"Found pH Down pump with case-insensitive match: {key} -> {relay.relay_assignments[key]}")
                            found = True
                    if not found:
                        logger.warning("pHDownPump not found in relay assignments!")
            
            # Start appropriate pH pump
            if use_ph_up:
                result = relay.set_ph_plus_pump(True)
                pump_type = "pH Up"
                logger.info(f"pH Up pump activation result: {result}")
            else:
                result = relay.set_ph_minus_pump(True)
                pump_type = "pH Down"
                logger.info(f"pH Down pump activation result: {result}")
                
            logger.info(f"Running {pump_type} cycle for {on_duration}")
            
            # Schedule to stop after on_duration
            self.scheduler.add_job(
                self._stop_ph_pump,
                'date',
                run_date=datetime.now() + timedelta(seconds=on_seconds),
                id='scheduled_ph_stop',
                replace_existing=True
            )
            
            # Check if mixing pump is running and has less than trigger duration remaining
            if self.mixing_pump_running and self.mixing_pump_end_time:
                remaining_seconds = (self.mixing_pump_end_time - datetime.now()).total_seconds()
                if remaining_seconds < trigger_seconds:
                    # Extend mixing pump duration
                    extension_seconds = trigger_seconds - remaining_seconds
                    self.mixing_pump_end_time = self.mixing_pump_end_time + timedelta(seconds=extension_seconds)
                    
                    # Update the scheduled stop time
                    self.scheduler.remove_job('mixing_stop_job')
                    self.scheduler.add_job(
                        self._stop_mixing_pump,
                        'date',
                        run_date=self.mixing_pump_end_time,
                        id='mixing_stop_job',
                        replace_existing=True
                    )
                    
                    logger.info(f"Extending mixing pump by {extension_seconds} seconds to ensure proper mixing after pH adjustment")
            elif not self.mixing_pump_running:
                # Start mixing pump if not running
                relay.set_mixing_pump(True)
                self.mixing_pump_running = True
                self.mixing_pump_end_time = datetime.now() + timedelta(seconds=trigger_seconds)
                
                # Schedule mixing pump to stop
                self.scheduler.add_job(
                    self._stop_mixing_pump,
                    'date',
                    run_date=self.mixing_pump_end_time,
                    id='mixing_stop_job',
                    replace_existing=True
                )
                
                logger.info(f"Starting mixing pump for {trigger_duration} after pH pump activation")
        except Exception as e:
            logger.exception(f"Error in pH cycle: {e}")
            
    def _run_sprinkler_cycle(self):
        """Execute sprinkler cycle"""
        try:
            on_duration = self.config.get('Sprinkler', 'sprinkler_on_duration').split(',')[0]
            on_seconds = self._time_to_seconds(on_duration)
            
            if on_seconds == 0:
                logger.warning("Skipping sprinkler cycle: zero duration")
                return
            
            # Get relay instance
            from src.sensors.Relay import Relay
            relay = Relay()
            if not relay:
                logger.warning("Failed to start sprinkler cycle: relay not available")
                return
                
            # Start sprinkler
            relay.set_sprinklers(True)
            logger.info(f"Running sprinkler cycle for {on_duration}")
            
            # Schedule to stop after on_duration
            self.scheduler.add_job(
                self._stop_sprinkler,
                'date',
                run_date=datetime.now() + timedelta(seconds=on_seconds),
                id='scheduled_sprinkler_stop',
                replace_existing=True
            )
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
            if section == 'Mixing':
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
            elif section == 'EC':
                # EC targets affect nutrient pump control
                logger.info(f"EC target updated: {key} = {value}")
                # Force a nutrient cycle check on next run
                if 'nutrient_cycle' in self.jobs:
                    self.scheduler.remove_job('nutrient_cycle')
                    self._initialize_nutrient_schedule()
            elif section == 'pH':
                # pH targets affect pH pump control
                logger.info(f"pH target updated: {key} = {value}")
                # Force a pH cycle check on next run
                if 'ph_cycle' in self.jobs:
                    self.scheduler.remove_job('ph_cycle')
                    self._initialize_nutrient_schedule()
                
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
            
    def _stop_nutrient_pump(self):
        """Stop the nutrient pump"""
        try:
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                # Stop all three nutrient pumps (A, B, C)
                relay.set_nutrient_pumps(False)
                logger.info("Nutrient pumps stopped")
            else:
                logger.warning("Failed to stop nutrient pumps: relay not available")
        except Exception as e:
            logger.error(f"Error stopping nutrient pumps: {e}")
            
    def _stop_ph_pump(self):
        """Stop the pH pumps"""
        try:
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                # Stop both pH pumps (up and down)
                relay.set_ph_plus_pump(False)
                relay.set_ph_minus_pump(False)
                logger.info("pH pumps stopped")
            else:
                logger.warning("Failed to stop pH pumps: relay not available")
        except Exception as e:
            logger.error(f"Error stopping pH pumps: {e}")
            
    def _stop_mixing_pump(self):
        """Stop the mixing pump"""
        try:
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                relay.set_mixing_pump(False)
                # Update state tracking variables
                self.mixing_pump_running = False
                self.mixing_pump_end_time = None
                logger.info("Mixing pump stopped")
            else:
                logger.warning("Failed to stop mixing pump: relay not available")
        except Exception as e:
            logger.error(f"Error stopping mixing pump: {e}")
            
    def _stop_sprinkler(self):
        """Stop the sprinklers"""
        try:
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                relay.set_sprinklers(False)
                logger.info("Sprinklers stopped")
            else:
                logger.warning("Failed to stop sprinklers: relay not available")
        except Exception as e:
            logger.error(f"Error stopping sprinklers: {e}")

    def handle_manual_command(self, command_type, duration=None):
        """Handle manual commands from the API"""
        try:
            if command_type == 'mixing':
                if duration and duration != "00:00:00":
                    # Convert duration to seconds
                    duration_seconds = self._time_to_seconds(duration)
                    if duration_seconds > 0:
                        # Start mixing pump for specified duration
                        from src.sensors.Relay import Relay
                        relay = Relay()
                        if relay:
                            relay.set_mixing_pump(True)
                            self.mixing_pump_running = True
                            self.mixing_pump_end_time = datetime.now() + timedelta(seconds=duration_seconds)
                            logger.info(f"Manual mixing pump started for {duration}")
                            logger.info(f"  Scheduled to end at: {self.mixing_pump_end_time}")
                        else:
                            logger.warning("Failed to start mixing pump: relay not available")
                    else:
                        logger.warning(f"Invalid mixing duration: {duration}")
                else:
                    # Stop mixing pump
                    self._stop_mixing_pump()
                    
            elif command_type == 'nutrient':
                if duration and duration != "00:00:00":
                    # Convert duration to seconds
                    duration_seconds = self._time_to_seconds(duration)
                    if duration_seconds > 0:
                        # Start nutrient pump for specified duration
                        from src.sensors.Relay import Relay
                        relay = Relay()
                        if relay:
                            relay.set_nutrient_pumps(True)
                            # Schedule to stop after duration
                            self.scheduler.add_job(
                                self._stop_nutrient_pump,
                                'date',
                                run_date=datetime.now() + timedelta(seconds=duration_seconds),
                                id='nutrient_stop_job',
                                replace_existing=True
                            )
                            logger.info(f"Manual nutrient pump started for {duration}")
                            logger.info(f"  Scheduled to stop at: {datetime.now() + timedelta(seconds=duration_seconds)}")
                        else:
                            logger.warning("Failed to start nutrient pump: relay not available")
                    else:
                        logger.warning(f"Invalid nutrient duration: {duration}")
                else:
                    # Stop nutrient pump
                    self._stop_nutrient_pump()
                        
            elif command_type == 'ph':
                if duration and duration != "00:00:00":
                    # Convert duration to seconds
                    duration_seconds = self._time_to_seconds(duration)
                    if duration_seconds > 0:
                        # Start pH pump for specified duration
                        from src.sensors.Relay import Relay
                        relay = Relay()
                        if relay:
                            # Get current pH reading and target pH
                            from src.sensors.pH import pH
                            current_ph = None
                            ph_statuses = pH.get_statuses_async()
                            
                            if ph_statuses and len(ph_statuses) > 0:
                                # Use the first available pH sensor reading
                                current_ph = next(iter(ph_statuses.values()))
                                logger.info(f"Current pH reading: {current_ph}")
                            else:
                                logger.warning("No pH readings available, cannot determine which pump to use")
                                return
                                
                            # Get target pH from configuration
                            try:
                                target_ph = float(self.config.get('pH', 'ph_target').split(',')[0])
                                logger.info(f"Target pH: {target_ph}")
                            except Exception as e:
                                logger.error(f"Failed to get target pH from config: {e}")
                                return
                                
                            # Get deadband from configuration
                            try:
                                ph_deadband = float(self.config.get('pH', 'ph_deadband').split(',')[0])
                                logger.info(f"pH deadband: {ph_deadband}")
                            except Exception as e:
                                logger.error(f"Failed to get pH deadband from config, using default: {e}")
                                ph_deadband = 0.5  # Default deadband
                            
                            # FIXED: Consistent pH control logic
                            # If the current pH differs from target pH by more than the deadband:
                            # - If current pH > target pH + deadband: use pH Down
                            # - If current pH < target pH - deadband: use pH Up
                            
                            if current_ph is not None:
                                # Calculate how far we are from target accounting for deadband
                                ph_high_threshold = target_ph + (ph_deadband / 2)
                                ph_low_threshold = target_ph - (ph_deadband / 2)
                                
                                logger.info(f"pH thresholds: low={ph_low_threshold}, target={target_ph}, high={ph_high_threshold}")
                                
                                if current_ph > ph_high_threshold:
                                    use_ph_up = False  # Use pH Down
                                    logger.info(f"Current pH ({current_ph}) is ABOVE high threshold ({ph_high_threshold}), using pH DOWN pump")
                                elif current_ph < ph_low_threshold:
                                    use_ph_up = True  # Use pH Up
                                    logger.info(f"Current pH ({current_ph}) is BELOW low threshold ({ph_low_threshold}), using pH UP pump")
                                else:
                                    logger.info(f"Current pH ({current_ph}) is within deadband of target ({target_ph}), no pH adjustment needed")
                                    return
                            else:
                                logger.warning("Invalid pH reading, cannot determine which pump to use")
                                return
                            
                            # Debug relay assignments
                            if relay.relay_assignments:
                                if 'pHDownPump' in relay.relay_assignments:
                                    logger.info(f"pHDownPump relay assignment: {relay.relay_assignments['pHDownPump']}")
                                else:
                                    found = False
                                    for key in relay.relay_assignments:
                                        if key.lower() == 'phdownpump':
                                            logger.info(f"Found pH Down pump with case-insensitive match: {key} -> {relay.relay_assignments[key]}")
                                            found = True
                                    if not found:
                                        logger.warning("pHDownPump not found in relay assignments!")
                            
                            if use_ph_up:
                                result = relay.set_ph_plus_pump(True)
                                pump_type = "pH Up"
                                logger.info(f"pH Up pump activation result: {result}")
                            else:
                                result = relay.set_ph_minus_pump(True)
                                pump_type = "pH Down"
                                logger.info(f"pH Down pump activation result: {result}")
                                
                            # Schedule to stop after duration
                            self.scheduler.add_job(
                                self._stop_ph_pump,
                                'date',
                                run_date=datetime.now() + timedelta(seconds=duration_seconds),
                                id='ph_stop_job',
                                replace_existing=True
                            )
                            logger.info(f"Manual {pump_type} pump started for {duration}")
                            logger.info(f"  Scheduled to stop at: {datetime.now() + timedelta(seconds=duration_seconds)}")
                        else:
                            logger.warning("Failed to start pH pump: relay not available")
                    else:
                        logger.warning(f"Invalid pH duration: {duration}")
                else:
                    # Stop pH pump
                    self._stop_ph_pump()
                        
            elif command_type == 'sprinkler':
                if duration and duration != "00:00:00":
                    # Convert duration to seconds
                    duration_seconds = self._time_to_seconds(duration)
                    if duration_seconds > 0:
                        # Start sprinkler for specified duration
                        from src.sensors.Relay import Relay
                        relay = Relay()
                        if relay:
                            relay.set_sprinklers(True)
                            # Schedule to stop after duration
                            self.scheduler.add_job(
                                self._stop_sprinkler,
                                'date',
                                run_date=datetime.now() + timedelta(seconds=duration_seconds),
                                id='sprinkler_stop_job',
                                replace_existing=True
                            )
                            logger.info(f"Manual sprinkler started for {duration}")
                            logger.info(f"  Scheduled to stop at: {datetime.now() + timedelta(seconds=duration_seconds)}")
                        else:
                            logger.warning("Failed to start sprinkler: relay not available")
                    else:
                        logger.warning(f"Invalid sprinkler duration: {duration}")
                else:
                    # Stop sprinkler
                    self._stop_sprinkler()
                    
            # Log all schedules after manual command
            self._log_all_schedules()
            return True
        except Exception as e:
            logger.error(f"Failed to handle manual command: {e}")
            return False 