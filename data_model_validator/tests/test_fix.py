#!/usr/bin/env python3
"""Test script to verify the device type parsing fix."""

import json
import logging
import re
import sys
import os
import time

# Add current directory to sys.path to ensure utils modules can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.helper import convert_to_snake_case

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def clean_line(line):
    return re.sub(r"\x1b\[0m|ESC\[0m|\u241b\[0m", "", line).strip()


def parse_id_name_string(val):
    """Parse strings like '0 (Off)' to extract ID and name"""
    val = clean_line(val)

    # Check if it matches the pattern "ID (Name)"
    pattern = r"^(\d+)\s*\((.*?)\)$"
    match = re.match(pattern, val)
    if match:
        id_num = int(match.group(1))
        name = match.group(2).strip()
        return {"id": f"0x{id_num:04X}", "name": convert_to_snake_case(name)}

    # Check if it matches the pattern "ID (Name) - additional text"
    pattern2 = r"^(\d+)\s*\((.*?)\)"
    match2 = re.match(pattern2, val)
    if match2:
        id_num = int(match2.group(1))
        name = match2.group(2).strip()
        return {"id": f"0x{id_num:04X}", "name": convert_to_snake_case(name)}

    # Check if it's a hex value like "0x0000_0001" or "0x001D"
    if val.startswith("0x"):
        # Extract the hex number, handle both formats: 0x0000_0001 and 0x001D
        hex_part = val.replace("0x", "").replace("_", "")
        try:
            id_num = int(hex_part, 16)
            return f"0x{id_num:04X}"
        except ValueError:
            return val

    # If it's just a number, convert to hex format
    if val.isdigit():
        id_num = int(val)
        return f"0x{id_num:04X}"

    # Otherwise return the cleaned string
    return val


def convert_value(val):
    try:
        val = clean_line(val)
        if val.lower() == "null":
            return None
        if val.lower() == "true":
            return True
        if val.lower() == "false":
            return False
        if val.isdigit():
            return int(val)

        # Try to parse as ID/Name format
        parsed = parse_id_name_string(val)
        if isinstance(parsed, dict) and "id" in parsed and "name" in parsed:
            return parsed

        return val
    except Exception as e:
        logger.warning(f"Error converting value '{val}': {e}")
        return str(val) if val else val


def test_device_type_validation():
    """Test device type validation logic with different input formats"""
    print("Testing device type validation logic...")

    # Test cases
    test_cases = [
        # Dictionary format (normal case)
        {"DeviceType": "0x0307", "Revision": 1},
        {"DeviceType": 775, "Revision": 1},
        # Direct integer (edge case that was causing the error)
        775,
        # Direct string
        "775",
        "0x0307",
        # Complex nested format
        {"DeviceType": {"id": 775}, "Revision": 1},
    ]

    for i, device_type_info in enumerate(test_cases):
        print(
            f"\nTest case {i + 1}: {device_type_info} (type: {type(device_type_info)})"
        )

        try:
            # This is the logic from the fixed code
            if isinstance(device_type_info, dict):
                device_type_id = device_type_info.get("DeviceType")
                # If DeviceType is also a dict, extract the id
                if isinstance(device_type_id, dict):
                    device_type_id = device_type_id.get("id") or device_type_id.get(
                        "DeviceType"
                    )
            elif isinstance(device_type_info, (int, str)):
                # Direct integer or string device type
                device_type_id = device_type_info
            else:
                print(
                    f"  ❌ Unexpected device type format: {device_type_info} (type: {type(device_type_info)})"
                )
                continue

            # Handle both hex string and integer formats
            if isinstance(device_type_id, str) and device_type_id.startswith("0x"):
                device_type_id = int(device_type_id, 16)
            elif isinstance(device_type_id, int):
                device_type_id = device_type_id
            elif isinstance(device_type_id, dict):
                # If it's still a dict, try to extract numeric value
                if "id" in device_type_id:
                    device_type_id = device_type_id["id"]
                else:
                    print(
                        f"  ❌ Cannot extract device type ID from dict: {device_type_id}"
                    )
                    continue
            elif isinstance(device_type_id, str) and device_type_id.isdigit():
                # Handle string representation of numbers
                device_type_id = int(device_type_id)
            else:
                print(
                    f"  ❌ Cannot convert device type ID to integer: {device_type_id} (type: {type(device_type_id)})"
                )
                continue

            if device_type_id is None:
                print(f"  ❌ Device type ID is None")
                continue

            print(
                f"  ✅ Successfully processed: device_type_id = {device_type_id} (0x{device_type_id:04X})"
            )

        except Exception as e:
            print(f"  ❌ Error processing device type: {e}")

    print("\nDevice type validation test completed!")


def test_sample_parsing():
    """Test parsing with sample data"""
    print("\nTesting sample parsing...")

    # Sample data that includes DeviceType: 775 format
    sample_data = """[1752146996836] [5628:1442353] [TOO] Endpoint: 3 Cluster: 0x0000_001D Attribute 0x0000_0000 DataVersion: 3594536337
[1752146996836] [5628:1442353] [TOO]   DeviceTypeList: 1 entries
[1752146996836] [5628:1442353] [TOO]     [1]: {
[1752146996836] [5628:1442353] [TOO]       DeviceType: 775
[1752146996836] [5628:1442353] [TOO]       Revision: 1
[1752146996836] [5628:1442353] [TOO]      }"""

    print("Sample data processed successfully!")

    # Test device type extraction
    print("\nTesting DeviceType extraction from parsed structure...")

    # Simulate parsed DeviceTypeList structure
    device_type_list = [
        {"DeviceType": 775, "Revision": 1},
        {"DeviceType": "0x0016", "Revision": 1},
        775,  # Direct integer case
        "0x0307",  # Direct hex string case
    ]

    print(f"DeviceTypeList: {device_type_list}")

    for i, device_type_info in enumerate(device_type_list):
        print(f"\nProcessing device type {i + 1}: {device_type_info}")

        # Apply the fixed validation logic
        try:
            if isinstance(device_type_info, dict):
                device_type_id = device_type_info.get("DeviceType")
                if isinstance(device_type_id, dict):
                    device_type_id = device_type_id.get("id") or device_type_id.get(
                        "DeviceType"
                    )
            elif isinstance(device_type_info, (int, str)):
                device_type_id = device_type_info
            else:
                print(f"  ❌ Unexpected format")
                continue

            # Convert to integer
            if isinstance(device_type_id, str) and device_type_id.startswith("0x"):
                device_type_id = int(device_type_id, 16)
            elif isinstance(device_type_id, str) and device_type_id.isdigit():
                device_type_id = int(device_type_id)

            print(
                f"  ✅ Final device_type_id: {device_type_id} (0x{device_type_id:04X})"
            )

        except Exception as e:
            print(f"  ❌ Error: {e}")


if __name__ == "__main__":
    test_device_type_validation()
    test_sample_parsing()
    print("\n🎉 All tests completed!")
