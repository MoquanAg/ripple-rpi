#!/usr/bin/env python3
"""
Relay Address Scanner
Scans Modbus addresses 0x01 to 0xFF to find the correct relay address.
Based on device.conf line 12 settings.
"""

import serial
import time
import struct

# Configuration from device.conf line 12
PORT = '/dev/ttyAMA2'
BAUDRATE = 9600
TIMEOUT = 0.2  # 200ms timeout

def calculate_crc16(data):
    """
    Calculate Modbus CRC16.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc

def scan_address(ser, address):
    """
    Test a single address by sending a read coil status command.
    Returns True if response received, False otherwise.
    """
    # Create Modbus RTU command: Read Coil Status (0x01)
    # Read 16 coils starting from 0x0000
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
        
        # Check if data available
        if ser.in_waiting > 0:
            response = ser.read(ser.in_waiting)
            
            # Valid response should have at least:
            # [address, function_code, byte_count, data..., crc_low, crc_high]
            if len(response) >= 5 and response[0] == address:
                return True, response
        
        return False, None
        
    except Exception as e:
        print(f"Error scanning address 0x{address:02X}: {e}")
        return False, None

def main():
    """Main scanner function."""
    print("=" * 60)
    print("Relay Address Scanner")
    print("=" * 60)
    print(f"Port: {PORT}")
    print(f"Baud Rate: {BAUDRATE}")
    print(f"Timeout: {TIMEOUT}s")
    print(f"Scanning range: 0x01 to 0xFF")
    print("=" * 60)
    print()
    
    found_addresses = []
    
    try:
        # Open serial port
        print(f"Opening serial port {PORT}...")
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=TIMEOUT
        )
        
        print(f"Serial port opened successfully.")
        print()
        
        # Give hardware time to stabilize
        time.sleep(0.5)
        
        # Scan all addresses
        print("Starting scan...")
        print()
        
        for address in range(0x01, 0x100):
            # Print progress every 16 addresses
            if address % 16 == 1:
                print(f"Scanning 0x{address:02X} - 0x{min(address+15, 0xFF):02X}...", end='', flush=True)
            
            found, response = scan_address(ser, address)
            
            if found:
                found_addresses.append(address)
                print(f"\n✓ FOUND DEVICE AT ADDRESS: 0x{address:02X} (decimal: {address})")
                print(f"  Response: {' '.join([f'0x{b:02X}' for b in response])}")
                print(f"  Response length: {len(response)} bytes")
                print()
            
            # Print newline after each block
            if address % 16 == 0:
                print()
            
            # Small delay between scans to avoid overwhelming the bus
            time.sleep(0.05)
        
        # Close serial port
        ser.close()
        
        # Print results
        print()
        print("=" * 60)
        print("SCAN COMPLETE")
        print("=" * 60)
        
        if found_addresses:
            print(f"\nFound {len(found_addresses)} device(s):")
            for addr in found_addresses:
                print(f"  - 0x{addr:02X} (decimal: {addr})")
            print()
            print("Update device.conf line 12 with the correct address:")
            print(f"  relayone = relay, ripple, \"Ripple Relay\", {PORT}, 0x{found_addresses[0]:02X}, {BAUDRATE}")
        else:
            print("\nNo devices found.")
            print("\nPossible issues:")
            print("  1. Wrong port (currently: {})".format(PORT))
            print("  2. Wrong baud rate (currently: {})".format(BAUDRATE))
            print("  3. Device not powered or not connected")
            print("  4. Wrong wiring (check A/B terminals)")
            print("  5. Device using non-standard protocol")
        
        print()
        
    except serial.SerialException as e:
        print(f"\nError: Could not open serial port {PORT}")
        print(f"Details: {e}")
        print("\nCheck:")
        print("  1. Is the device connected?")
        print("  2. Do you have permissions? (try: sudo)")
        print("  3. Is another program using this port?")
        return 1
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user.")
        return 130
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())

