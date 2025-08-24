#!/usr/bin/env python3
"""
Simple PWM Test - Stripped down version for basic functionality testing
"""

import time
import serial

# Simple constants
PORT = "/dev/ttyAMA4"  # This port works!
BAUDRATE = 115200
MAX_PWM_ID = 5

# LED IDs
MAIN_LED = 0
BLUE_LED = 1
RED_LED = 2
LED_730 = 3

def create_pwm_command(led_id, intensity):
    """Create PWM command with checksum"""
    # Basic command structure: [STX, LEN, CMD, ID, INTENSITY, ETX, CHECKSUM]
    command = bytearray([0x02, 0x03, 0x35, led_id, intensity, 0x03, 0x00])
    
    # Calculate checksum (XOR all bytes except last)
    checksum = 0
    for i in range(len(command) - 1):
        checksum ^= command[i]
    command[-1] = checksum
    
    return command

def test_pwm_basic():
    """Basic PWM test - just turn on/off each LED"""
    print("=== Basic PWM Test ===")
    
    try:
        with serial.Serial(PORT, BAUDRATE, timeout=1) as ser:
            # Test each LED
            for led_id in [MAIN_LED, BLUE_LED, RED_LED, LED_730]:
                print(f"Testing LED {led_id}...")
                
                # Turn on (intensity 100)
                cmd = create_pwm_command(led_id, 100)
                ser.write(cmd)
                response = ser.read(7)
                print(f"  ON response: {response.hex()}")
                time.sleep(1)
                
                # Turn off
                cmd = create_pwm_command(led_id, 0)
                ser.write(cmd)
                response = ser.read(7)
                print(f"  OFF response: {response.hex()}")
                time.sleep(0.5)
                
    except Exception as e:
        print(f"Serial error: {e}")

def test_pwm_quick():
    """Quick on/off test"""
    print("\n=== Quick PWM Test ===")
    
    try:
        with serial.Serial(PORT, BAUDRATE, timeout=1) as ser:
            # Quick sequence
            for _ in range(5):
                # All on
                for led_id in [MAIN_LED, BLUE_LED, RED_LED, LED_730]:
                    cmd = create_pwm_command(led_id, 150)
                    ser.write(cmd)
                    ser.read(7)
                time.sleep(0.5)
                
                # All off
                for led_id in [MAIN_LED, BLUE_LED, RED_LED, LED_730]:
                    cmd = create_pwm_command(led_id, 0)
                    ser.write(cmd)
                    ser.read(7)
                time.sleep(0.5)
                
    except Exception as e:
        print(f"Serial error: {e}")

if __name__ == "__main__":
    print("Simple PWM Test Starting...")
    
    # Run tests
    test_pwm_basic()
    test_pwm_quick()
    
    print("\nPWM Test Complete!")
