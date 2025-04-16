import serial
import time
import sys
import os
import struct

# Function to calculate Modbus CRC
def calculate_crc(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, byteorder='little')

# Function to send a command and get the response
def send_command(port, command, expected_length=10, timeout=1.0):
    try:
        # Open serial port
        ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout
        )
        
        # Send the command
        print(f"Sending: {command.hex(' ')}")
        ser.write(command)
        
        # Read the response
        response = ser.read(expected_length)
        print(f"Received: {response.hex(' ')}")
        
        # Close the port
        ser.close()
        
        return response
    
    except Exception as e:
        print(f"Error: {e}")
        return None

# Function to parse and display register values
def parse_registers(data):
    if len(data) < 7:  # Need at least 7 bytes (addr + func + len + 2 regs + crc)
        print("Response too short to contain register data")
        return
    
    addr = data[0]
    func = data[1]
    byte_count = data[2]
    
    print(f"Address: {addr}")
    print(f"Function: {func}")
    print(f"Byte count: {byte_count}")
    
    if byte_count >= 4:  # At least 2 registers
        reg1 = int.from_bytes(data[3:5], byteorder='big')
        reg2 = int.from_bytes(data[5:7], byteorder='big')
        
        print(f"Register 1 raw: {reg1}")
        print(f"Register 2 raw: {reg2}")
        
        # Check CRC
        data_without_crc = data[:-2]
        received_crc = data[-2:]
        calculated_crc = calculate_crc(data_without_crc)
        
        if received_crc == calculated_crc:
            print("CRC: Valid")
        else:
            print(f"CRC: Invalid. Received {received_crc.hex(' ')}, Calculated {calculated_crc.hex(' ')}")
        
        return reg1, reg2
    
    return None, None

# Function to convert two 16-bit registers to IEEE 754 floating point with different byte orderings
def regs_to_float(reg1, reg2):
    # Approach 1: Big endian (reg1, reg2)
    combined1 = (reg1 << 16) | reg2
    b1 = combined1.to_bytes(4, byteorder='big')
    float1 = struct.unpack('>f', b1)[0]
    
    # Approach 2: Little endian (reg2, reg1)
    combined2 = (reg2 << 16) | reg1
    b2 = combined2.to_bytes(4, byteorder='big')
    float2 = struct.unpack('>f', b2)[0]
    
    # Approach 3: Big endian but swap bytes within each register
    r1_bytes = reg1.to_bytes(2, byteorder='big')
    r2_bytes = reg2.to_bytes(2, byteorder='big')
    r1_swapped = int.from_bytes(r1_bytes, byteorder='little')
    r2_swapped = int.from_bytes(r2_bytes, byteorder='little')
    combined3 = (r1_swapped << 16) | r2_swapped
    b3 = combined3.to_bytes(4, byteorder='big')
    float3 = struct.unpack('>f', b3)[0]
    
    # Approach 4: Little endian overall
    combined4 = (reg1 << 16) | reg2
    b4 = combined4.to_bytes(4, byteorder='big')
    float4 = struct.unpack('<f', b4)[0]
    
    # Direct approach from 4 bytes
    bytes_array = bytearray([
        (reg1 >> 8) & 0xFF,
        reg1 & 0xFF,
        (reg2 >> 8) & 0xFF,
        reg2 & 0xFF
    ])
    float5 = struct.unpack('>f', bytes_array)[0]
    
    return {
        "big_endian": float1,
        "little_endian_regs": float2,
        "swapped_bytes": float3,
        "little_endian_all": float4,
        "direct_bytes": float5
    }

# Main function
def main():
    port = '/dev/ttyAMA2'  # Update as needed
    
    # First command: Read 2 registers from address 0x0000 (EC and temperature)
    # 01 03 00 00 00 02 C4 0B - Read 2 registers from 0x0000
    cmd1 = bytearray([0x01, 0x03, 0x00, 0x00, 0x00, 0x02, 0xC4, 0x0B])
    print("\n=== Command 1: Read EC and Temperature (0x0000-0x0001) ===")
    response1 = send_command(port, cmd1, expected_length=9)
    
    if response1 and len(response1) >= 7:
        ec_raw, temp_raw = parse_registers(response1)
        
        if ec_raw is not None:
            # Interpret as EC and temperature
            ec_value = ec_raw / 10.0
            print(f"EC value: {ec_value} µS/cm")
            
            # Try multiple temperature interpretations
            temp1 = temp_raw / 10.0
            temp2 = temp_raw / 100.0
            temp3 = (temp_raw - 10000) / 100.0 if temp_raw > 10000 else None
            
            print(f"Temperature interpretations:")
            print(f"  - Raw/10: {temp1}°C")
            print(f"  - Raw/100: {temp2}°C")
            print(f"  - (Raw-10000)/100: {temp3}°C")
    
    # Second command: Read 2 registers from address 0x0004
    # 01 03 00 04 00 02 85 CA - Read 2 registers from 0x0004
    cmd2 = bytearray([0x01, 0x03, 0x00, 0x04, 0x00, 0x02, 0x85, 0xCA])
    print("\n=== Command 2: Read Registers 0x0004-0x0005 ===")
    response2 = send_command(port, cmd2, expected_length=9)
    
    if response2 and len(response2) >= 7:
        reg4, reg5 = parse_registers(response2)
        
        if reg4 is not None:
            print(f"Register 0x0004 value: {reg4}")
            print(f"Register 0x0005 value: {reg5}")
            
            # IEEE 754 floating point interpretation
            float_values = regs_to_float(reg4, reg5)
            print(f"\nIEEE 754 floating point interpretations:")
            print(f"  - Big endian: {float_values['big_endian']}°C")
            print(f"  - Little endian registers: {float_values['little_endian_regs']}°C")
            print(f"  - Swapped bytes: {float_values['swapped_bytes']}°C")
            print(f"  - Little endian all: {float_values['little_endian_all']}°C")
            print(f"  - Direct bytes: {float_values['direct_bytes']}°C")
            
            # Test interpreting as temperature values
            print("\nTemperature interpretations for register 0x0004:")
            temp1 = reg4 / 10.0
            temp2 = reg4 / 100.0
            temp3 = (reg4 - 10000) / 100.0 if reg4 > 10000 else None
            print(f"  - Raw/10: {temp1}°C")
            print(f"  - Raw/100: {temp2}°C")
            print(f"  - (Raw-10000)/100: {temp3}°C")
            
            print("\nTemperature interpretations for register 0x0005:")
            temp1 = reg5 / 10.0
            temp2 = reg5 / 100.0
            temp3 = (reg5 - 10000) / 100.0 if reg5 > 10000 else None
            print(f"  - Raw/10: {temp1}°C")
            print(f"  - Raw/100: {temp2}°C")
            print(f"  - (Raw-10000)/100: {temp3}°C")
    
    print("\nTest complete.")

if __name__ == "__main__":
    main() 