#!/usr/bin/env python3
"""
Test PWM across all ttyAMA ports to find which one works
"""

import time
import serial
import os

# Test all ports
PORTS = ["/dev/ttyAMA1", "/dev/ttyAMA2", "/dev/ttyAMA3", "/dev/ttyAMA4"]
BAUDRATE = 115200

# LED IDs
MAIN_LED = 0
BLUE_LED = 1
RED_LED = 2
LED_730 = 3

def create_pwm_command(led_id, intensity):
    """Create PWM command with checksum"""
    command = bytearray([0x02, 0x03, 0x35, led_id, intensity, 0x03, 0x00])
    
    # Calculate checksum (XOR all bytes except last)
    checksum = 0
    for i in range(len(command) - 1):
        checksum ^= command[i]
    command[-1] = checksum
    
    return command

def test_port(port):
    """Test if a port responds to PWM commands"""
    print(f"\n=== Testing {port} ===")
    
    # Check if port exists
    if not os.path.exists(port):
        print(f"  ❌ Port {port} does not exist")
        return False
    
    try:
        with serial.Serial(port, BAUDRATE, timeout=1) as ser:
            print(f"  ✅ Port {port} opened successfully")
            
            # Test basic PWM command
            cmd = create_pwm_command(BLUE_LED, 100)
            print(f"  Sending command: {cmd.hex()}")
            
            ser.write(cmd)
            response = ser.read(7)
            
            if len(response) == 7:
                print(f"  ✅ Got response: {response.hex()}")
                
                # Check if response looks valid (should start with 0x02)
                if response[0] == 0x02:
                    print(f"  ✅ Valid response format")
                    
                    # Test turning LED off
                    cmd_off = create_pwm_command(BLUE_LED, 0)
                    ser.write(cmd_off)
                    ser.read(7)
                    print(f"  ✅ LED off command sent")
                    
                    return True
                else:
                    print(f"  ❌ Invalid response format")
                    return False
            else:
                print(f"  ❌ No response or wrong length: {len(response)} bytes")
                return False
                
    except serial.serialutil.SerialException as e:
        print(f"  ❌ Serial error: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Unexpected error: {e}")
        return False

def main():
    print("Testing PWM functionality across all ttyAMA ports...")
    
    working_ports = []
    
    for port in PORTS:
        if test_port(port):
            working_ports.append(port)
            print(f"  🎉 {port} WORKS!")
        else:
            print(f"  💥 {port} FAILED")
    
    print(f"\n=== RESULTS ===")
    if working_ports:
        print(f"✅ Working ports: {working_ports}")
        print(f"🎯 Recommended port: {working_ports[0]}")
    else:
        print("❌ No working ports found")
        print("💡 Check if:")
        print("   - Hardware is connected")
        print("   - Permissions are correct (try running with sudo)")
        print("   - Port names are correct for your system")

if __name__ == "__main__":
    main()
