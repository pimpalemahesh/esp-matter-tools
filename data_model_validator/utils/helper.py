import re
import logging

# Configure logging
logger = logging.getLogger(__name__)


def convert_to_snake_case(name):
    """Convert a name to snake_case. PM2.5 Concentration Measurement -> pm2_5_concentration_measurement

    :param name:

    """
    if name.endswith("Command"):
        name = name[:-7].replace(" ", "_")
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[\/_|\{\}\(\)\\-]", "_", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"([a-zA-Z])([0-9])", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


# ------------- Common Parsing Utilities -------------


def clean_line(line):
    """Remove terminal escape sequences and clean line"""
    return re.sub(r"\x1b\[0m|ESC\[0m|\u241b\[0m", "", line).strip()


def convert_value(val):
    """Convert string values to appropriate types (basic conversion only)"""
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

        return val
    except Exception as e:
        logger.warning(f"Error converting value '{val}': {e}")
        return str(val) if val else val


def convert_cluster_id_to_hex(cluster_id):
    """Convert cluster ID to hex format consistently"""
    if isinstance(cluster_id, int):
        return f"0x{cluster_id:04X}"
    elif isinstance(cluster_id, str):
        if cluster_id.startswith("0x"):
            return cluster_id
        elif cluster_id.isdigit():
            return f"0x{int(cluster_id):04X}"
    return cluster_id


def convert_device_type_to_hex(obj):
    """Recursively convert DeviceType values to hex format"""
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key == "DeviceType" and isinstance(value, int):
                result[key] = f"0x{value:04X}"
            else:
                result[key] = convert_device_type_to_hex(value)
        return result
    elif isinstance(obj, list):
        return [convert_device_type_to_hex(item) for item in obj]
    else:
        return obj
