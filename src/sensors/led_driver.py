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
        """Flush the input buffer of the serial port."""
        ser.reset_input_buffer()
        time.sleep(0.005)  # Short delay to ensure buffer is cleared

    def set_led_intensity(self, id, intensity):
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
    driver.set_led_intensity(0, 0) # MAIN should be at 200 for PDD testing
    driver.set_led_intensity(1, 0) # BLUE should be at 150 for PDD testing
    driver.set_led_intensity(2, 0) # RED should be at 150 for PDD testing
    driver.set_led_intensity(3, 0) # 730nm LED

    # driver.set_led_intensity(0, 80)  # MAIN should be at 200 for PDD testing
    # driver.set_led_intensity(1, 40)  # BLUE should be at 150 for PDD testing
    # driver.set_led_intensity(2, 120)  # RED should be at 150 for PDD testing
    # driver.set_led_intensity(3, 00)  # 730nm LED

    # driver.test_fade()


    return


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error running main: {e}")
