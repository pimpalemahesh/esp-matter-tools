import re
import json
import logging
import time

# Import common utility functions
from utils.helper import (
    clean_line,
    convert_cluster_id_to_hex,
    convert_device_type_to_hex,
    convert_to_snake_case,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------- Parsing-Specific Functions -------------


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

    return val


def convert_value(val):
    """Convert string values to appropriate types (with parsing-specific logic)"""
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


def convert_cluster_list_to_objects(cluster_list):
    """Convert a list of cluster IDs to objects with id fields"""
    if not isinstance(cluster_list, list):
        return cluster_list

    result = []
    for item in cluster_list:
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, int):
            hex_id = f"0x{item:04X}"
            result.append({"id": hex_id})
        elif isinstance(item, str):
            if item.isdigit():
                int_val = int(item)
                hex_id = f"0x{int_val:04X}"
                result.append({"id": hex_id})
            else:
                result.append({"id": item})
        else:
            result.append(item)

    return result


def parse_metadata_line(line):
    """Parse metadata line to extract endpoint, cluster, and attribute info"""
    pattern = r"Endpoint:\s*(\d+)\s+Cluster:\s*(0x[\dA-Fa-f_]+)\s+Attribute\s*(0x[\dA-Fa-f_]+)\s+DataVersion:\s*(\d+)"
    match = re.match(pattern, line.strip())
    if match:
        return {
            "Endpoint": int(match.group(1)),
            "Cluster": match.group(2),
            "Attribute": match.group(3),
        }
    return {}


def parse_block(lines, index=0):
    """Parse a block of structured text into a dictionary"""
    result = {}
    lines_len = len(lines)

    # Pre-compile regex patterns for better performance
    list_pattern = re.compile(r"(\w+):\s+\d+\s+entries")
    item_pattern = re.compile(r"\[\d+\]:\s*\{?")
    value_pattern = re.compile(r"\[\d+\]:\s*(.+)")
    inline_obj_pattern = re.compile(r"(\w+):\s*\{")
    kv_pattern = re.compile(r"(\w+):\s*(.*)")

    while index < lines_len:
        line = clean_line(lines[index])
        if not line:
            index += 1
            continue

        m_list = list_pattern.match(line)
        if m_list:
            key = m_list.group(1)
            index += 1
            items = []
            while index < lines_len:
                sub_line = clean_line(lines[index])
                if item_pattern.match(sub_line):
                    if "{" in sub_line:
                        index += 1
                        item, index = parse_block(lines, index)
                        items.append(item)
                    else:
                        val_match = value_pattern.match(sub_line)
                        if val_match:
                            items.append(convert_value(val_match.group(1)))
                        index += 1
                else:
                    break
            result[key] = items
            continue

        if line == "}":
            return result, index + 1

        m_inline_obj = inline_obj_pattern.match(line)
        if m_inline_obj:
            key = m_inline_obj.group(1)
            index += 1
            nested_obj, index = parse_block(lines, index)
            result[key] = nested_obj
            continue

        kv_match = kv_pattern.match(line)
        if kv_match:
            key, val = kv_match.groups()
            val = val.strip()
            if val != "":
                result[key] = convert_value(val)
            index += 1
        else:
            index += 1

    return result, index


def parse_input(text):
    """Parse input text containing metadata and structured data"""
    lines = text.strip().splitlines()
    top_level = {}

    if lines:
        metadata_line = clean_line(lines[0])
        top_level = parse_metadata_line(metadata_line)
        lines = lines[1:]

    parsed_body, _ = parse_block(lines)
    top_level.update(parsed_body)
    return top_level


def process_attribute_data(attribute_lines, endpoints):
    """Process a single attribute's data and add it to the endpoints structure"""
    if not attribute_lines:
        return

    try:
        # Parse the attribute data
        input_str = "\n".join(attribute_lines)
        parsed = parse_input(input_str)

        endpoint_id = parsed.get("Endpoint", 0)
        cluster_id = parsed.get("Cluster", "unknown")

        # Format cluster ID consistently
        if cluster_id != "unknown":
            cluster_id = parse_id_name_string(cluster_id)
            if not isinstance(cluster_id, str):
                cluster_id = str(cluster_id)

        # Initialize structures if needed
        if endpoint_id not in endpoints:
            endpoints[endpoint_id] = {}
        if cluster_id not in endpoints[endpoint_id]:
            endpoints[endpoint_id][cluster_id] = []

        # Add the parsed data
        endpoints[endpoint_id][cluster_id].append(parsed)

    except Exception as e:
        logger.error(f"Error processing attribute data: {e}")


def parse_datamodel_logs(data):
    """Parse the complete datamodel logs and organize by endpoint and cluster.

    Args:
        data (str): Raw log data containing [TOO] entries

    Returns:
        dict: Structured data organized by endpoints and clusters
    """
    start_time = time.time()
    logger.info("Starting datamodel parsing...")

    endpoints = {}

    # Split lines and filter [TOO] entries
    lines = data.split("\n")
    too_lines = [line for line in lines if "[TOO]" in line]
    logger.info(f"Found {len(too_lines)} [TOO] entries to process")

    # Check if this is a compatible file format
    if len(too_lines) == 0:
        logger.error("No [TOO] entries found in the file")
        raise ValueError(
            "No [TOO] entries found in the file. This appears to be a different type of log file that is not compatible with this parser."
        )

    # Extract all [TOO] entries
    endpoint_attribute_data = []
    processed_count = 0

    try:
        for line in too_lines:
            processed_count += 1
            if processed_count % 500 == 0:
                logger.info(f"Processed {processed_count}/{len(too_lines)} entries")

            info = line.split("[TOO]", 1)[-1]
            if "Endpoint" in info:
                if endpoint_attribute_data:
                    process_attribute_data(endpoint_attribute_data, endpoints)
                endpoint_attribute_data = [f"{info}"]
            else:
                if endpoint_attribute_data:
                    endpoint_attribute_data.append(f"{info}")

        # Process the last attribute data
        if endpoint_attribute_data:
            process_attribute_data(endpoint_attribute_data, endpoints)

        logger.info(
            f"Parsed {len(endpoints)} endpoints in {time.time() - start_time:.2f}s"
        )

    except Exception as e:
        logger.error(f"Error during parsing: {str(e)}")
        raise

    # Convert to the desired format
    logger.info("Converting to final format...")
    result = {"endpoints": []}

    # Pre-compile the exclusion set for faster lookups
    exclude_keys = {"Endpoint", "Cluster", "Attribute"}

    # Pre-compile attribute type mappings
    attr_type_mapping = {
        "0xFFFC": ("features", "FeatureMap"),
        "0xFFFD": ("features", "ClusterRevision"),
        "0xFFF8": ("commands", "GeneratedCommandList"),
        "0xFFF9": ("commands", "AcceptedCommandList"),
        "0xFFFA": ("events", "EventList"),
        "0xFFFB": ("attributes", "AttributeList"),
    }

    for endpoint_id in sorted(endpoints.keys()):
        endpoint_data = {"endpoint": endpoint_id, "clusters": {}}

        # Group clusters properly
        for cluster_id in sorted(endpoints[endpoint_id].keys()):
            # Convert cluster ID to hex format consistently
            hex_cluster_id = convert_cluster_id_to_hex(cluster_id)

            cluster_data = {
                "attributes": {},
                "events": {},
                "commands": {},
                "features": {},
            }

            # Add all attributes for this cluster
            for attr_data in endpoints[endpoint_id][cluster_id]:
                attr_id = attr_data.get("Attribute", "unknown")

                # Format attribute ID consistently
                if attr_id != "unknown":
                    attr_id = parse_id_name_string(attr_id)
                    if not isinstance(attr_id, str):
                        attr_id = str(attr_id)

                # Remove the endpoint, cluster, and attribute metadata keys
                clean_attr_data = {
                    k: v for k, v in attr_data.items() if k not in exclude_keys
                }

                # Post-process certain attributes to ensure consistent formatting
                for key, value in clean_attr_data.items():
                    if key in ["ServerList", "ClientList"] and isinstance(value, list):
                        clean_attr_data[key] = convert_cluster_list_to_objects(value)
                    elif key == "DeviceTypeList" and isinstance(value, list):
                        formatted_device_types = []
                        for device_type in value:
                            if isinstance(device_type, dict):
                                device_type_obj = device_type.copy()
                                if "DeviceType" in device_type_obj:
                                    dt_val = device_type_obj["DeviceType"]
                                    if isinstance(dt_val, int):
                                        device_type_obj["DeviceType"] = (
                                            f"0x{dt_val:04X}"
                                        )
                                formatted_device_types.append(device_type_obj)
                            else:
                                formatted_device_types.append(device_type)
                        clean_attr_data[key] = formatted_device_types

                # Determine the category for this attribute
                if attr_id in attr_type_mapping:
                    category, attr_name = attr_type_mapping[attr_id]
                    cluster_data[category][attr_name] = clean_attr_data
                else:
                    cluster_data["attributes"][attr_id] = clean_attr_data

            # Only add cluster if it has data
            if any(cluster_data.values()):
                endpoint_data["clusters"][hex_cluster_id] = cluster_data

        result["endpoints"].append(endpoint_data)

    # Convert DeviceType values to hex format
    result = convert_device_type_to_hex(result)

    logger.info(f"Total parsing time: {time.time() - start_time:.2f}s")

    return result
