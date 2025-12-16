#!/usr/bin/env python3
"""
Relay Address Scanner - Verbose Mode
More detailed scanning with raw data inspection.
"""

import serial
import time
import struct

# Configuration from device.conf line 12
PORT = '/dev/ttyAMA1'
BAUDRATE = 9600
TIMEOUT = 0.2  # 200ms timeout

def calculate_crc16(data):
    """Calculate Modbus CRC16."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc

def scan_address_verbose(ser, address):
    """
    Test a single address with verbose output.
    Returns (found, response, raw_bytes_received).
    """
    # Create Modbus RTU command: Read Coil Status (0x01)
    command = bytearray([address, 0x01, 0x00, 0x00, 0x00, 0x10])
    
    # Calculate and append CRC
    crc = calculate_crc16(command)
    command.append(crc & 0xFF)
    command.append((crc >> 8) & 0xFF)
    
    try:
        # Flush buffers
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        # Send command
        ser.write(command)
        
        # Wait for response
        time.sleep(TIMEOUT)
        
        # Check if ANY data available
        bytes_waiting = ser.in_waiting
        if bytes_waiting > 0:
            response = ser.read(bytes_waiting)
            
            # Check if it looks like a valid Modbus response
            if len(response) >= 5 and response[0] == address:
                return "VALID", response, bytes_waiting
            elif len(response) > 0:
                return "PARTIAL", response, bytes_waiting
        
        return "NONE", None, 0
        
    except Exception as e:
        return "ERROR", str(e).encode(), 0

def test_common_bauds(port):
    """Test common baud rates."""
    common_bauds = [9600, 19200, 38400, 57600, 115200]
    print("\nTesting common baud rates at address 0x01:")
    print("-" * 60)
    
    for baud in common_bauds:
        try:
            ser = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=TIMEOUT
            )
            time.sleep(0.2)
            
            status, response, _ = scan_address_verbose(ser, 0x01)
            
            if status == "VALID":
                print(f"  {baud:6d} baud: ✓ VALID RESPONSE FOUND!")
            elif status == "PARTIAL":
                print(f"  {baud:6d} baud: ⚠ Partial response (might be noise)")
            else:
                print(f"  {baud:6d} baud: ✗ No response")
            
            ser.close()
            time.sleep(0.1)
            
        except Exception as e:
            print(f"  {baud:6d} baud: ERROR - {e}")
    
    print("-" * 60)

def main():
    """Main scanner function."""
    print("=" * 70)
    print("Relay Address Scanner - VERBOSE MODE")
    print("=" * 70)
    print(f"Port: {PORT}")
    print(f"Baud Rate: {BAUDRATE}")
    print(f"Timeout: {TIMEOUT}s")
    print("=" * 70)
    
    # Test different baud rates first
    test_common_bauds(PORT)
    
    print(f"\nNow scanning addresses 0x01 to 0xFF at {BAUDRATE} baud...")
    print()
    
    found_addresses = []
    partial_responses = []
    
    try:
        # Open serial port
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=TIMEOUT
        )
        
        time.sleep(0.5)
        
        # Scan addresses with more detail
        for address in range(0x01, 0x100):
            status, response, bytes_count = scan_address_verbose(ser, address)
            
            if status == "VALID":
                found_addresses.append(address)
                print(f"\n✓✓✓ VALID DEVICE AT 0x{address:02X} (decimal: {address}) ✓✓✓")
                print(f"    Response: {' '.join([f'0x{b:02X}' for b in response])}")
                print(f"    Length: {len(response)} bytes")
                print()
            elif status == "PARTIAL":
                partial_responses.append((address, response))
                print(f"\n⚠ Partial response at 0x{address:02X}:")
                print(f"    Data: {' '.join([f'0x{b:02X}' for b in response])}")
                print(f"    (Might be noise or wrong baud rate)")
            elif status == "ERROR":
                print(f"\n✗ Error at 0x{address:02X}: {response.decode('utf-8', errors='ignore')}")
            
            # Progress indicator every 32 addresses
            if address % 32 == 0:
                print(f"Progress: {address}/255 ({int(address/255*100)}%)")
            
            time.sleep(0.05)
        
        ser.close()
        
        # Print results
        print()
        print("=" * 70)
        print("SCAN COMPLETE")
        print("=" * 70)
        
        if found_addresses:
            print(f"\n✓ Found {len(found_addresses)} valid device(s):")
            for addr in found_addresses:
                print(f"    0x{addr:02X} (decimal: {addr})")
            print()
            print("Recommended device.conf line 12:")
            print(f"  relayone = relay, ripple, \"Ripple Relay\", {PORT}, 0x{found_addresses[0]:02X}, {BAUDRATE}")
        else:
            print("\n✗ No valid devices found at current baud rate.")
        
        if partial_responses:
            print(f"\n⚠ Found {len(partial_responses)} partial response(s):")
            for addr, resp in partial_responses[:5]:  # Show first 5
                print(f"    0x{addr:02X}: {' '.join([f'0x{b:02X}' for b in resp])}")
            print("\n  This might indicate:")
            print("    - Wrong baud rate (try the baud test results above)")
            print("    - Electrical noise on the line")
            print("    - Device using non-standard protocol")
        
        if not found_addresses and not partial_responses:
            print("\nNo responses at all. Check:")
            print("  1. Device power - is it ON?")
            print("  2. Wiring - A to A, B to B (or try swapping)")
            print("  3. Port - is {PORT} the correct port?".format(PORT=PORT))
            print("  4. Termination resistor if line is long")
        
        print()
        
    except serial.SerialException as e:
        print(f"\n✗ Error: Could not open serial port {PORT}")
        print(f"Details: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user.")
        return 130
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())

