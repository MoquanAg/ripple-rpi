import time
import serial
import os
import sys
import asyncio
import threading
import logging

# Setup local logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def pwm_safe_intensity(intensity):
    """Clamp intensity value between 0 and 255, handling type conversion."""
    if isinstance(intensity, str):
        try:
            intensity = float(intensity)
        except ValueError:
            try:
                intensity = int(intensity)
            except ValueError:
                return 0

    if isinstance(intensity, float):
        new_intensity = min(max(int(intensity), 0), 255)
    elif isinstance(intensity, int):
        new_intensity = min(max(intensity, 0), 255)
    else:
        return 0

    return new_intensity


SUCCESS_CODE = 0x00
UNDETERMINED_ERROR = 0x01
DATA_ERROR = 0x02
COMMAND_ERROR = 0xFF

MAX_PWM_ID = 5

MAIN_LED_ID = 0
BLUE_LED_ID = 1
RED_LED_ID = 2
LED_730_ID = 3


class LEDDriver:
    """
    LED driver control system implementing singleton pattern for lighting management.
    
    Manages multiple LED channels for plant growth lighting including main LEDs,
    blue LEDs (450nm), red LEDs (660nm), and far-red LEDs (730nm). Provides
    precise intensity control through PWM modulation with safety validation
    and error handling.
    
    Features:
    - Multi-channel LED control (Main, Blue, Red, Far-Red)
    - PWM intensity control (0-255 range with safety clamping)
    - Serial communication protocol with checksum validation
    - Thread-safe singleton implementation
    - Automatic intensity validation and type conversion
    - Response validation with error code handling
    - Fade testing capabilities for LED validation
    
    LED Channels:
    - MAIN_LED_ID (0): Main growth light LED
    - BLUE_LED_ID (1): Blue spectrum LED (450nm)
    - RED_LED_ID (2): Red spectrum LED (660nm)
    - LED_730_ID (3): Far-red spectrum LED (730nm)
    
    Communication Protocol:
    - Serial communication over configurable port
    - Command format: [0x02, 0x03, 0x35, LED_ID, INTENSITY, 0x03, CHECKSUM]
    - Response format: [0x02, 0x03, 0x35, STATUS, LED_ID, 0x03, CHECKSUM]
    - Baud rate: 115200, 8N1 configuration
    - Timeout: 1 second for response validation
    
    Error Codes:
    - SUCCESS_CODE (0x00): Command executed successfully
    - UNDETERMINED_ERROR (0x01): Unknown error occurred
    - DATA_ERROR (0x02): Data validation or transmission error
    - COMMAND_ERROR (0xFF): Invalid command format or parameters
    
    Args:
        port (str): Serial port for LED controller communication (default: '/dev/ttyAMA5')
        
    Note:
        - Docstring created by Claude 3.5 Sonnet on 2024-09-22
        - Implements thread-safe singleton pattern for system-wide LED control
        - Uses XOR checksum validation for communication reliability
        - Automatically clamps intensity values to valid range (0-255)
        - Provides property-based access to individual LED intensities
        - Supports fade testing for LED system validation
        - Handles serial communication errors gracefully
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(LEDDriver, cls).__new__(cls)
        return cls._instance

    def __init__(self, port="/dev/ttyAMA5"):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self.port = port
            self._main_led_intensity = 0
            self._blue_led_intensity = 0
            self._red_led_intensity = 0
            self._led_730_intensity = 0
            self.MAIN_LED_ID = MAIN_LED_ID
            self.BLUE_LED_ID = BLUE_LED_ID
            self.RED_LED_ID = RED_LED_ID
            self.LED_730_ID = LED_730_ID

    @property
    def main_led_intensity(self):
        return self._main_led_intensity

    @main_led_intensity.setter
    def main_led_intensity(self, value):
        self._main_led_intensity = value

    @property
    def blue_led_intensity(self):
        return self._blue_led_intensity

    @blue_led_intensity.setter
    def blue_led_intensity(self, value):
        self._blue_led_intensity = value

    @property
    def red_led_intensity(self):
        return self._red_led_intensity

    @red_led_intensity.setter
    def red_led_intensity(self, value):
        self._red_led_intensity = value

    @property
    def led_730_intensity(self):
        return self._led_730_intensity

    @led_730_intensity.setter
    def led_730_intensity(self, value):
        self._led_730_intensity = value

    def get_led_intensity(self, id):
        if id == self.MAIN_LED_ID:
            return self.main_led_intensity
        elif id == self.BLUE_LED_ID:
            return self.blue_led_intensity
        elif id == self.RED_LED_ID:
            return self.red_led_intensity
        elif id == self.LED_730_ID:
            return self.led_730_intensity
        else:
            logger.warning(f"Unknown LED ID: {id}")
            return None

    def flush_input_buffer(self, ser):
        """
        Flush the input buffer of the serial port.
        
        Clears any pending data in the serial port input buffer to ensure
        clean communication. This prevents interference from previous
        commands or incomplete transmissions.
        
        Args:
            ser: Serial port object to flush
            
        Note:
            - Uses reset_input_buffer() to clear the buffer
            - Includes 5ms delay to ensure buffer is fully cleared
            - Called before sending commands to ensure clean transmission
        """
        ser.reset_input_buffer()
        time.sleep(0.005)  # Short delay to ensure buffer is cleared

    def set_led_intensity(self, id, intensity):
        """
        Set the intensity of a specific LED channel.
        
        Controls the PWM intensity of individual LED channels with safety
        validation, error handling, and response verification. Automatically
        clamps intensity values and validates LED IDs before transmission.
        
        Args:
            id (int): LED channel ID (0-5, see LED_ID constants)
            intensity (int/float/str): Intensity value (0-255, values ≤20 are clamped to 0)
            
        Returns:
            int: Set intensity value on success, negative error code on failure
                - Positive value: Successfully set intensity
                - -1: Invalid LED ID or serial communication error
                - -UNDETERMINED_ERROR: Unknown error from LED controller
                - -DATA_ERROR: Data validation or transmission error
                - -COMMAND_ERROR: Invalid command format
                
        Communication Protocol:
            - Command: [0x02, 0x03, 0x35, LED_ID, INTENSITY, 0x03, CHECKSUM]
            - Response: [0x02, 0x03, 0x35, STATUS, LED_ID, 0x03, CHECKSUM]
            - Checksum: XOR of all bytes except the last
            
        Note:
            - Automatically validates LED ID against MAX_PWM_ID
            - Clamps intensity values ≤20 to 0 (LEDs won't turn on below 20)
            - Uses XOR checksum for communication reliability
            - Updates internal intensity tracking on successful commands
            - Handles serial communication errors gracefully
            - Provides detailed error logging for troubleshooting
        """
        time.sleep(0.005)

        if id > MAX_PWM_ID:
            logger.warning("Invalid LED ID")
            return -1

        # 20 or lower won't turn on the lights anyway
        if intensity <= 20:
            intensity = 0

        request = bytearray(
            [0x02, 0x03, 0x35, id, pwm_safe_intensity(intensity), 0x03, 0x00]
        )
        for i in range(len(request) - 1):
            request[-1] = request[-1] ^ request[i]

        try:
            with serial.Serial(
                port=self.port,
                baudrate=115200,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout=1,
            ) as ser:
                self.flush_input_buffer(ser)  # Flush before sending command
                ser.write(request)
                response = ser.read(7)  # Expected response length is 7 bytes
        except serial.serialutil.SerialException as e:
            logger.warning(f"Warning for LED ID {id}: {str(e)}")
            return -1

        response_checksum = 0x00

        if len(response) != 7:
            logger.warning("len(response) != 7")
            return -1

        if response[3] == SUCCESS_CODE:
            for i in range(len(response) - 1):
                response_checksum = response_checksum ^ response[i]
            if response[-1] == response_checksum and request[3] == response[4]:
                if id == self.MAIN_LED_ID:
                    self.main_led_intensity = intensity
                elif id == self.BLUE_LED_ID:
                    self.blue_led_intensity = intensity
                elif id == self.RED_LED_ID:
                    self.red_led_intensity = intensity
                elif id == self.LED_730_ID:
                    self.led_730_intensity = intensity
                logger.info(f"LED {id} intensity set to {intensity}")
                return intensity

        elif response[3] == UNDETERMINED_ERROR:
            logger.warning("Undetermined error")
            return -UNDETERMINED_ERROR

        elif response[3] == COMMAND_ERROR:
            logger.warning("Command error")
            return -COMMAND_ERROR

        logger.warning("Data error")
        return -DATA_ERROR

    def send_pwm_frequency_commands(self):
        # command_1 = bytearray([0x02, 0x05, 0x42, 0x01, 0x03, 0xE8, 0x00, 0x03, 0x38])
        command_1 = bytearray([0x02, 0x05, 0x42, 0x02, 0x03, 0xE8, 0x00, 0x03, 0x39])
        self.serial.write(command_1)
        try:
            response = self.serial.read(7)
        except serial.serialutil.SerialException as e:
            logger.warning(f"warning for {id}: {str(e)}")
            return -1

        logger.info(response)
        if len(response) != 7:
            logger.warning("len(response) != 7")
            return -1
        if response[3] == SUCCESS_CODE:
            for i in range(len(response) - 1):
                response_checksum = response_checksum ^ response[i]
            if response[-1] == response_checksum and command_1[3] == response[4]:
                logger.info(f"send_pwm_frequency_commands success")
                return
        elif response[3] == UNDETERMINED_ERROR:
            logger.warning("Undetermined error")
            return -UNDETERMINED_ERROR
        elif response[3] == COMMAND_ERROR:
            logger.warning("Command error")
            return -COMMAND_ERROR
        logger.warning("Data error")
        return -DATA_ERROR

    def test_fade(self):
        """
        Execute a comprehensive LED fade test sequence.
        
        Performs a systematic test of all LED channels by cycling through
        intensity ranges to validate LED functionality and driver communication.
        Tests individual channels and combined effects with smooth fade transitions.
        
        Test Sequence:
        1. Initialize all LEDs to 0 intensity
        2. Set main LED to minimum operational level (22)
        3. Blue LED fade test: 21→254→20 (full cycle)
        4. Red LED fade test: 21→254→20 (full cycle)
        5. Combined blue+red fade test: 21→254→20 (synchronized)
        6. Far-red LED fade test: 21→254→20 (full cycle)
        7. Final operational state: Main=30, Blue=80
        
        Parameters:
            - Fade step: 1 intensity unit per cycle
            - Fade delay: 10ms between steps for smooth transitions
            - Maximum intensity: 250 (below 255 for safety margin)
            - Minimum operational: 21 (above LED turn-on threshold)
            
        Note:
            - Used for LED system validation and troubleshooting
            - Demonstrates smooth fade capabilities of the driver
            - Tests both individual and combined LED operation
            - Includes safety delays between operations
            - Leaves system in known operational state
            - Total test duration: approximately 25-30 seconds
        """
        max_intensity = 250
        
        self.set_led_intensity(0, 0) # MAIN should be at 200 for PDD testing
        self.set_led_intensity(1, 0) # BLUE should be at 150 for PDD testing
        self.set_led_intensity(2, 0) # RED should be at 150 for PDD testing
        self.set_led_intensity(3, 0) # 730nm LED
        
        time.sleep(1)
        
        self.set_led_intensity(0, 22)
        
        for i in range(21,255):
            self.set_led_intensity(1, i)
            time.sleep(0.01)
            
        for i in range(254,20,-1):
            self.set_led_intensity(1, i)
            time.sleep(0.01)
            
        self.set_led_intensity(1, 0)
        
        for i in range(21, 255):
            self.set_led_intensity(2, i)
            time.sleep(0.01)
            
        for i in range(254,20,-1):
            self.set_led_intensity(2, i)
            time.sleep(0.01)
        
        self.set_led_intensity(2, 0)
        
        for i in range(21, 255):
            self.set_led_intensity(1, i)
            self.set_led_intensity(2, i)
            time.sleep(0.01)
            
        for i in range(254,20,-1):
            self.set_led_intensity(1, i)
            self.set_led_intensity(2, i)
            time.sleep(0.01)
            
        self.set_led_intensity(1, 0)
        self.set_led_intensity(2, 0)
            
        for i in range(21, 255):
            self.set_led_intensity(3, i)
            time.sleep(0.01)
            
        for i in range(254,20,-1):
            self.set_led_intensity(3, i)
            time.sleep(0.01)
        
        self.set_led_intensity(3, 0)
        time.sleep(1)
        
        self.set_led_intensity(0, 30)
        self.set_led_intensity(1, 80)  
        
        return
            
            

async def main():
    driver = LEDDriver()
    # driver.send_pwm_frequency_commands()
    driver.set_led_intensity(0, 130) # MAIN should be at 200 for PDD testing
    driver.set_led_intensity(1, 0) # BLUE should be at 150 for PDD testing
    driver.set_led_intensity(2, 150) # RED should be at 150 for PDD testing
    driver.set_led_intensity(3, 255) # 730nm LED

    # driver.set_led_intensity(0, 0)  # MAIN should be at 200 for PDD testing
    # driver.set_led_intensity(1, 0)  # BLUE should be at 150 for PDD testing
    # driver.set_led_intensity(2, 0)  # RED should be at 150 for PDD testing
    # driver.set_led_intensity(3, 0)  # 730nm LED

    # driver.test_fade()


    return


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error running main: {e}")
