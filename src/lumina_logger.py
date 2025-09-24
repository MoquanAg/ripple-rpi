import logging
import os
import json
from enum import Enum
import threading
import datetime
import shutil
import glob
import tzlocal
import orjson

# Define constants locally to avoid circular imports
LOG_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "log")
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
SENSOR_DATA_LOG_PATH = os.path.join(BASE_DIR, "data", "sensor_data")

LOG_MAX_SIZE = 2  # MB
LOG_SIZE_CHECK_INTERVAL = 5 * 60  # 5 minutes

SENSOR_DATA_LOG_MAX_SIZE = 20 * 1024 * 1024  # 20 MB

MIN_FREE_SPACE_MB = 500  # Minimum free space in MB before cleanup


class CustomLogger(logging.Logger):

    def __init__(self, name):
        super().__init__(name)

    # Smart info
    def sinfo(self, msg, *args, **kwargs):
        if True:  # Always log for now, can be made configurable later
            super().info(msg, *args, **kwargs)


class GlobalLogger:
    _instances = {}  # Dictionary to hold instances for different prefixes

    def __new__(cls, logger_name=None, log_prefix="lumina_"):
        instance_key = f"{logger_name}_{log_prefix}"
        if instance_key not in cls._instances:
            instance = super(GlobalLogger, cls).__new__(cls)
            instance.init(logger_name, log_prefix)  # Initialize the instance
            cls._instances[instance_key] = instance
        return cls._instances[instance_key]

    def init(self, logger_name=None, log_prefix="lumina_"):
        """Initialize a new logger instance."""
        # Your setup_logging function
        global logger
        logger_name = logger_name or __name__
        logger = CustomLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        # Set higher logging level for third-party libraries
        logging.getLogger("pika").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("apscheduler").setLevel(logging.WARNING)

        # Initialize the current date and log number
        self.current_date = datetime.datetime.now().strftime("%Y%m%d")
        self.current_log_number = 1
        self.log_prefix = log_prefix

        # Generate the initial log file name without checking existing files
        log_file_name = f"{self.log_prefix}{self.current_date}_{self.current_log_number:03d}.log"
        self.LOG_FILE_PATH = os.path.join(
            LOG_FOLDER_PATH, log_file_name
        )

        file_handler = logging.FileHandler(self.LOG_FILE_PATH)
        file_handler.setLevel(logging.INFO)

        # Set up console handler to print logs to console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Define log format with time
        formatter = logging.Formatter(
            "%(asctime)s - %(filename)s - %(funcName)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Add handlers to the logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        self.logger = logger

        # Add the log_sensor_data method to the logger instance
        self.logger.log_sensor_data = self.log_sensor_data

        self.schedule_cleanup()  # Schedule log file cleanup

        # Explicitly set the level for the root logger
        logging.getLogger().setLevel(logging.INFO)

    def schedule_cleanup(self):
        # Schedule the `clean_up_if_needed` function to run every `LOG_SIZE_CHECK_INTERVAL` seconds
        timer = threading.Timer(LOG_SIZE_CHECK_INTERVAL, self.clean_up_if_needed)
        timer.daemon = True
        timer.start()

    def clean_up_if_needed(self):
        # Check free space first
        free_space = self.get_free_space()
        if free_space < MIN_FREE_SPACE_MB:
            self.logger.warning(
                f"Low disk space detected: {free_space:.2f}MB free. Cleaning up old logs..."
            )
            self.delete_oldest_log_files()
            # Check space again after cleanup
            new_free_space = self.get_free_space()
            self.logger.info(f"After cleanup: {new_free_space:.2f}MB free")

            # Create a new log file if the current one was deleted
            if not os.path.exists(self.LOG_FILE_PATH):
                self.current_log_number = 1
                new_log_file_name = (
                    f"{self.log_prefix}{self.current_date}_{self.current_log_number:03d}.log"
                )
                self.LOG_FILE_PATH = os.path.join(
                    LOG_FOLDER_PATH, new_log_file_name
                )

                # Create new file handler
                file_handler = logging.FileHandler(self.LOG_FILE_PATH)
                file_handler.setLevel(logging.INFO)
                formatter = logging.Formatter(
                    "%(asctime)s - %(filename)s - %(funcName)s - %(message)s"
                )
                file_handler.setFormatter(formatter)

                # Update handlers
                self.logger.handlers = [
                    h
                    for h in self.logger.handlers
                    if not isinstance(h, logging.FileHandler)
                ]
                self.logger.addHandler(file_handler)

                self.logger.info(
                    f"Created new log file after cleanup: {new_log_file_name}"
                )

        # Only check file size if the file exists
        if os.path.exists(self.LOG_FILE_PATH):
            file_size = os.path.getsize(self.LOG_FILE_PATH) / (
                1024 * 1024
            )  # Convert size to MB
            current_date = datetime.datetime.now().strftime("%Y%m%d")

            # Check if we need a new log file
            need_new_file = (
                file_size > LOG_MAX_SIZE or current_date != self.current_date
            )

            if need_new_file:
                self.logger.info(
                    f"Log file size is over {LOG_MAX_SIZE} MB or date has changed. Current size: {file_size:.5f} MB"
                )

                # Send the current log file to the cloud
                self.send_log_to_cloud()

                # Update the log number or reset it for a new day
                if current_date != self.current_date:
                    self.current_date = current_date
                    self.current_log_number = 1
                else:
                    self.current_log_number += 1
                    if self.current_log_number > 999:
                        self.current_log_number = 1

                # Create the new log file name
                new_log_file_name = (
                    f"{self.log_prefix}{self.current_date}_{self.current_log_number:03d}.log"
                )
                new_log_file_path = os.path.join(
                    LOG_FOLDER_PATH, new_log_file_name
                )

                # Update the log file path and create a new file handler
                self.LOG_FILE_PATH = new_log_file_path
                file_handler = logging.FileHandler(self.LOG_FILE_PATH)
                file_handler.setLevel(logging.INFO)
                formatter = logging.Formatter(
                    "%(asctime)s - %(filename)s - %(funcName)s - %(message)s"
                )
                file_handler.setFormatter(formatter)

                # Remove the old file handler and add the new one
                self.logger.handlers = [
                    h
                    for h in self.logger.handlers
                    if not isinstance(h, logging.FileHandler)
                ]
                self.logger.addHandler(file_handler)

                self.logger.info(f"Created new log file: {new_log_file_name}")
            else:
                self.logger.info(
                    f"Log file size is under {LOG_MAX_SIZE} MB and date hasn't changed. Current size: {file_size:.5f} MB"
                )

        # Schedule the next cleanup
        self.schedule_cleanup()

    def get_free_space(self):
        _, _, free = shutil.disk_usage(BASE_DIR)
        free_mb = free / (1024 * 1024)  # Convert to MB
        return free_mb

    def date_changed(self):
        current_date = datetime.datetime.now().strftime("%Y%m%d")
        return current_date != self.current_date

    def generate_new_log_file_name(self):
        current_date = datetime.datetime.now().strftime("%Y%m%d")
        self.current_date = current_date

        log_files = glob.glob(
            os.path.join(LOG_FOLDER_PATH, f"{self.log_prefix}{current_date}_*.log")
        )
        if log_files:
            latest_log_file = max(log_files, key=os.path.getctime)
            latest_log_number = int(os.path.splitext(latest_log_file)[0].split("_")[-1])
            new_log_number = latest_log_number + 1 if latest_log_number < 999 else 1
        else:
            new_log_number = 1

        new_log_file_name = f"{self.log_prefix}{current_date}_{new_log_number:03d}.log"
        return new_log_file_name

    def delete_oldest_log_files(self):
        log_files = glob.glob(os.path.join(LOG_FOLDER_PATH, f"{self.log_prefix}*_*.log"))
        if log_files:
            oldest_date = min(
                log_files, key=lambda x: os.path.splitext(x)[0].split("_")[1]
            )
            oldest_date = oldest_date.split("_")[1]
            oldest_log_files = glob.glob(
                os.path.join(LOG_FOLDER_PATH, f"{self.log_prefix}{oldest_date}_*.log")
            )
            for log_file in oldest_log_files:
                try:
                    os.remove(log_file)
                    self.logger.info(f"Deleted log file: {log_file}")
                except Exception as e:
                    self.logger.error(
                        f"Failed to delete log file: {log_file}. Error: {str(e)}"
                    )

    def send_log_to_cloud(self):

        return

        import NetworkManager

        self.logger.info("Sending log to cloud")
        NetworkManager.NetworkManager().send_text_file_to_cloud(
            "log", self.LOG_FILE_PATH
        )

    def log_sensor_data(self, path_list, value=None):
        # Convert path_list to a string for the filename
        sensor_name = ".".join(path_list)
        log_file_path = f"{SENSOR_DATA_LOG_PATH}.{sensor_name}.log"

        # Get current datetime in the specified format
        local_timezone = datetime.datetime.now().astimezone().tzinfo
        datetime_obj = datetime.datetime.now()
        datetime_obj = datetime_obj.replace(tzinfo=local_timezone)
        current_datetime = datetime_obj.strftime("%Y-%m-%dT%H:%M:%S%z")

        # Convert value to string with double quotes if it's JSON, or use "null" if it's None
        if value is None:
            value_string = "null"
        elif isinstance(value, (dict, list)):
            value_string = json.dumps(value)  # This will use double quotes by default
        else:
            value_string = str(value)

        # Construct the log entry
        log_entry = f"{current_datetime}\t{'.'.join(path_list)}\t{value_string}\n"

        # Check if the file exists and its size
        if os.path.exists(log_file_path):
            file_size = os.path.getsize(log_file_path)
            if file_size > SENSOR_DATA_LOG_MAX_SIZE:
                self.truncate_log_file(
                    log_file_path, capped_size=SENSOR_DATA_LOG_MAX_SIZE
                )

        # Append the log entry to the sensor data log file
        with open(log_file_path, "a") as f:
            f.write(log_entry)

    def truncate_log_file(self, file_path, capped_size=5 * 1024 * 1024):
        with open(file_path, "r+") as f:
            content = f.readlines()
            f.seek(0)
            f.truncate()

            # Calculate how many lines we can keep while staying under 5MB
            total_size = 0
            keep_lines = []
            for line in reversed(content):
                line_size = len(line.encode("utf-8"))
                if total_size + line_size > capped_size:
                    break
                total_size += line_size
                keep_lines.append(line)

            # Write the most recent lines back to the file
            f.writelines(reversed(keep_lines))

        self.logger.debug(f"Truncated sensor log file: {file_path}")


class JsonSerializable:
    @property
    def status_json(self):
        instance_vars = vars(self).copy()
        instance_vars.pop("logger", None)

        # Convert Enum keys to their string names and process other types
        new_instance_vars = {}
        for key, value in instance_vars.items():
            # Check if key is an Enum and use its name
            if isinstance(key, Enum):
                key = key.name
            # Otherwise, if key is not one of the allowed types, continue to next iteration
            elif not isinstance(key, (str, int, float, bool, type(None))):
                continue

            # If value is a dictionary, recurse into it
            if isinstance(value, dict):
                value = {
                    k.name if isinstance(k, Enum) else k: v for k, v in value.items()
                }

            # Process the value
            if isinstance(value, Enum):
                value = value.name

            if issubclass(type(value), JsonSerializable):
                value = value.status_json

            new_instance_vars[key] = value

        return orjson.dumps(new_instance_vars, option=orjson.OPT_INDENT_2)
