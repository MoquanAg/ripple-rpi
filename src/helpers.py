import orjson
import re
import tzlocal
from datetime import datetime, timedelta
import os, sys
import json
try:
    # Try importing when running from main directory
    import src.globals as globals
    from src.lumina_logger import GlobalLogger
except ImportError:
    # Import when running from src directory
    import globals
    from lumina_logger import GlobalLogger

logger = GlobalLogger("RippleHelpers", log_prefix="ripple_").logger

current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)


def remove_comments(jsonc_content):
    """Remove C-style comments from a string"""
    pattern = r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"'
    return re.sub(
        pattern,
        lambda m: "" if m.group(0).startswith("/") else m.group(0),
        jsonc_content,
        flags=re.MULTILINE | re.DOTALL,
    )


def jsonc_to_json(jsonc_content):
    # Remove comments
    cleaned_content = remove_comments(jsonc_content)

    # Parse and return the JSON object
    return orjson.loads(cleaned_content)


def instruction_sets_are_the_same(set1, set2):
    if isinstance(set1, dict) and isinstance(set2, dict):
        if len(set1) != len(set2):
            return False

        for key in set1:
            if key == "time" or (
                key == "data" and "current_phase_last_update" in set1[key]
            ):
                continue
            if key not in set2:
                return False
            if not instruction_sets_are_the_same(set1[key], set2[key]):
                return False
        return True

    if isinstance(set1, list) and isinstance(set2, list):
        if len(set1) != len(set2):
            return False
        for i in range(len(set1)):
            if not instruction_sets_are_the_same(set1[i], set2[i]):
                return False
        return True

    return set1 == set2


def iso8601_to_datetime(timestamp_string):
    timestamp_format = "%Y-%m-%dT%H:%M:%S%z"
    datetime_obj = datetime.strptime(timestamp_string, timestamp_format)

    if datetime_obj.tzinfo is None:
        local_tz = tzlocal.get_localzone()
        datetime_obj = datetime_obj.replace(tzinfo=local_tz)

    return datetime_obj


def datetime_to_iso8601(datetime_obj="now"):
    if datetime_obj is None or datetime_obj == "now":
        datetime_obj = datetime.now()

    local_timezone = datetime.now().astimezone().tzinfo
    datetime_obj = datetime_obj.replace(tzinfo=local_timezone)

    return datetime_obj.strftime("%Y-%m-%dT%H:%M:%S%z")


def iso8601_to_seconds(timestamp_string):
    duration = datetime.strptime(timestamp_string, "%H:%M:%S")
    total_seconds = duration.hour * 3600 + duration.minute * 60 + duration.second
    return total_seconds

def is_within_time(dt, seconds):
    if isinstance(dt, str):
        dt = iso8601_to_datetime(dt)
    elif not isinstance(dt, datetime):
        raise TypeError("Input must be a datetime object or a string.")

    now = datetime.now(dt.tzinfo)
    
    # Extract time components
    dt_time = dt.time()
    now_time = now.time()
    
    # Convert times to timedelta for comparison
    dt_delta = timedelta(hours=dt_time.hour, minutes=dt_time.minute, seconds=dt_time.second, microseconds=dt_time.microsecond)
    now_delta = timedelta(hours=now_time.hour, minutes=now_time.minute, seconds=now_time.second, microseconds=now_time.microsecond)
    
    # Calculate the difference
    diff = abs((now_delta - dt_delta).total_seconds())
    
    # Handle cases crossing midnight
    if diff > 12 * 3600:  # If difference is more than 12 hours, it's shorter the other way around the clock
        diff = 24 * 3600 - diff
    
    return diff <= seconds

def scheduler_safe_now():
    return datetime.now() + timedelta(seconds=1)

def save_sensor_data(subpath, data):
    save_data(subpath, data, globals.SAVED_SENSOR_DATA_PATH)


def save_data(subpath, data, path):
    try:
        # Attempt to read the existing configuration
        with open(path, "r") as file:
            try:
                config = orjson.loads(file.read())
            except orjson.JSONDecodeError:
                globals.logger.info(f"Empty file for {path}. Initializing a new one.")
                config = {}  # Initialize if the file is empty
    except FileNotFoundError:
        globals.logger.info(f"No file found for {path}. Creating a new one.")
        config = {}

    if not subpath:
        config.update(data)
    else:
        current_level = config
        for key in subpath[:-1]:
            if key not in current_level:
                current_level[key] = {}
            current_level = current_level[key]

        last_key = subpath[-1]
        if last_key not in current_level:
            current_level[last_key] = {}
        for key, value in data.items():
            current_level[last_key][key] = value

    # Format all float values to 2 decimal places
    def format_floats(obj):
        if isinstance(obj, float):
            return round(obj, 2)
        elif isinstance(obj, dict):
            return {k: format_floats(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [format_floats(item) for item in obj]
        return obj

    config = format_floats(config)

    # Changed from orjson.dump to orjson.dumps and manual write
    with open(path, "wb") as file:  # Note: changed to "wb" mode
        json_bytes = orjson.dumps(config, option=orjson.OPT_INDENT_2)
        file.write(json_bytes)


def remove_file(file_path):
    try:
        if os.path.isfile(file_path):
            os.remove(file_path)
            print(f"File '{file_path}' has been successfully removed.")
        else:
            print(f"File '{file_path}' does not exist.")
    except OSError as e:
        print(f"Error occurred while removing the file: {e}")


def pwm_safe_intensity(intensity):
    if isinstance(intensity, str):
        try:
            intensity = float(intensity)
        except ValueError:
            try:
                intensity = int(intensity)
            except ValueError:
                return 0

    # print(f"pwm_safe_intensity: {intensity}")
    if isinstance(intensity, float):
        new_intensity = min(max(int(intensity), 0), 255)
    elif isinstance(intensity, int):
        new_intensity = min(max(intensity, 0), 255)
    else:
        return 0

    return new_intensity


def relative_seconds(seconds):
    weeks = seconds // (7 * 24 * 3600)
    seconds %= 7 * 24 * 3600
    days = seconds // (24 * 3600)
    seconds %= 24 * 3600
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    result = []
    if weeks > 0:
        result.append(f"{int(weeks)}w")
    if days > 0:
        result.append(f"{int(days)}d")
    if hours > 0:
        result.append(f"{int(hours)}h")
    if minutes > 0:
        result.append(f"{int(minutes)}m")
    if seconds > 0 or not result:
        result.append(f"{int(seconds)}s")
    return " ".join(result)


def percentage_to_byte_array(value):  # 0-1.0, as 00.00% to 100.00%
    try:
        # Convert the input to a float
        if isinstance(value, str):
            value = float(value)
        elif isinstance(value, int):
            value = float(value)
        elif not isinstance(value, float):
            raise ValueError("Unsupported type")

        # Ensure the value is within the range 0 to 1.0
        if not 0.0 <= value <= 1.0:
            raise ValueError("Value out of range")

        # Normalize to a range that fits in 2 bytes (16 bits)
        normalized_value = int(value * 0x2710)

        # Convert to a 2-byte hexadecimal string
        hex_value = f"{normalized_value:04x}"

        # Split into bytes and convert each to integer
        byte_array = bytearray(int(hex_value[i : i + 2], 16) for i in range(0, 4, 2))

        return byte_array

    except Exception:
        return bytearray([0x00, 0x00])

def byte_subarray_to_decimal(response, start_pos, end_pos):
    """
    Extract a subarray from the response and convert it to a decimal number.
    If an error occurs, it returns None and logs the error.
    
    :param response: The full byte array response
    :param start_pos: The starting position of the subarray (inclusive, 0-indexed)
    :param end_pos: The ending position of the subarray (inclusive, 0-indexed)
    :return: The decimal representation of the subarray, or None if an error occurred
    """
    try:
        # Check if response is a bytes-like object
        if not isinstance(response, (bytes, bytearray)):
            logger.error("Response must be a bytes-like object")
            return None
        
        # Check if start_pos and end_pos are integers
        if not isinstance(start_pos, int) or not isinstance(end_pos, int):
            logger.error("Start and end positions must be integers")
            return None
        
        # Check if start_pos is non-negative
        if start_pos < 0:
            logger.error("Start position must be non-negative")
            return None
        
        # Check if end_pos is greater than or equal to start_pos
        if end_pos < start_pos:
            logger.error("End position must be greater than or equal to start position")
            return None
        
        # Check if the response is long enough
        if len(response) < end_pos + 1:
            logger.error(f"Response is too short. Expected at least {end_pos + 1} bytes, got {len(response)}")
            return None
        
        # Extract the subarray
        subarray = response[start_pos:end_pos+1]
        
        # Convert the subarray to an integer
        decimal_value = int.from_bytes(subarray, byteorder='big')
        
        return decimal_value
    
    except Exception as e:
        # Log the error
        logger.error(f"Unexpected error in byte_subarray_to_decimal: {str(e)}")
        return None

def iso8601_to_timedelta(duration_string):
    """
    Convert an ISO 8601 duration string to a timedelta object.
    Supports formats like 'HH:MM:SS' or 'PT1H30M15S'.
    """
    if ':' in duration_string:
        # Format: 'HH:MM:SS'
        hours, minutes, seconds = map(int, duration_string.split(':'))
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    else:
        # Format: 'PT1H30M15S'
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_string)
        if not match:
            raise ValueError(f"Invalid duration format: {duration_string}")
        
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)

def minimize_json(data):
    """Convert data to minimized JSON string by removing whitespace and newlines"""
    return orjson.dumps(data)  # orjson already produces minimized output by default
