import json
import logging
import sys
import os

# Add current directory to sys.path to ensure utils modules can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.helper import convert_to_snake_case

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Load element requirements
def load_element_requirements():
    """Load element requirements from JSON file"""
    try:
        with open("element_requirement.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("element_requirement.json file not found")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing element_requirement.json: {e}")
        return []


def validate_device_compliance(parsed_data, element_requirements):
    """Validate if the device meets all requirements for its device types"""
    validation_results = {
        "endpoints": [],
        "summary": {
            "total_endpoints": 0,
            "compliant_endpoints": 0,
            "non_compliant_endpoints": 0,
        },
    }

    # Create a lookup dictionary for requirements by device type ID
    requirements_lookup = {}
    for device in element_requirements:
        device_id = device.get("id")
        if device_id:
            # Handle both hex string and integer formats
            if isinstance(device_id, str) and device_id.startswith("0x"):
                # Convert hex string to integer for lookup
                requirements_lookup[int(device_id, 16)] = device
            elif isinstance(device_id, int):
                requirements_lookup[device_id] = device

    for endpoint in parsed_data.get("endpoints", []):
        endpoint_result = {
            "endpoint": endpoint["endpoint"],
            "device_types": [],
            "is_compliant": True,
            "missing_elements": [],
            "extra_elements": [],
        }

        # Find device types from descriptor cluster
        descriptor_cluster = endpoint.get("clusters", {}).get("0x001D", {})
        device_type_list = None

        # Look for DeviceTypeList in attributes
        for attr_id, attr_data in descriptor_cluster.get("attributes", {}).items():
            if "DeviceTypeList" in attr_data:
                device_type_list = attr_data["DeviceTypeList"]
                break

        if not device_type_list:
            endpoint_result["device_types"].append({"error": "No DeviceTypeList found in descriptor cluster"})
            endpoint_result["is_compliant"] = False
        else:
            # Validate each device type
            for device_type_info in device_type_list:
                device_type_id = device_type_info.get("DeviceType")

                # Handle both hex string and integer formats
                if isinstance(device_type_id, str) and device_type_id.startswith("0x"):
                    device_type_id = int(device_type_id, 16)
                elif isinstance(device_type_id, int):
                    device_type_id = device_type_id

                if device_type_id in requirements_lookup:
                    device_validation = validate_single_device_type(endpoint, device_type_id, requirements_lookup[device_type_id])
                    endpoint_result["device_types"].append(device_validation)
                    if not device_validation["is_compliant"]:
                        endpoint_result["is_compliant"] = False
                        endpoint_result["missing_elements"].extend(device_validation["missing_elements"])
                else:
                    endpoint_result["device_types"].append(
                        {
                            "device_type_id": (f"0x{device_type_id:04X}" if isinstance(device_type_id, int) else device_type_id),
                            "device_type_name": "unknown",
                            "error": f"Device type {device_type_id} not found in requirements",
                        }
                    )

        validation_results["endpoints"].append(endpoint_result)
        validation_results["summary"]["total_endpoints"] += 1
        if endpoint_result["is_compliant"]:
            validation_results["summary"]["compliant_endpoints"] += 1
        else:
            validation_results["summary"]["non_compliant_endpoints"] += 1

    return validation_results


def validate_single_device_type(endpoint, device_type_id, device_requirements):
    """Validate a single device type against its requirements"""
    result = {
        "device_type_id": device_type_id,
        "device_type_name": device_requirements.get("name", "unknown"),
        "is_compliant": True,
        "missing_elements": [],
        "cluster_validations": [],
    }

    required_clusters = device_requirements.get("clusters", [])
    endpoint_clusters = endpoint.get("clusters", {})

    for required_cluster in required_clusters:
        cluster_validation = validate_cluster(endpoint_clusters, required_cluster)
        result["cluster_validations"].append(cluster_validation)

        if not cluster_validation["is_compliant"]:
            result["is_compliant"] = False
            result["missing_elements"].extend(cluster_validation["missing_elements"])

    return result


def validate_cluster(endpoint_clusters, required_cluster):
    """Validate a cluster against its requirements"""
    cluster_id = required_cluster["id"]
    cluster_name = required_cluster["name"]
    cluster_type = required_cluster.get("type", "server")

    result = {
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "cluster_type": cluster_type,
        "is_compliant": True,
        "missing_elements": [],
    }

    # Check if cluster exists
    if cluster_id not in endpoint_clusters:
        result["is_compliant"] = False
        result["missing_elements"].append(
            {
                "type": "cluster",
                "id": cluster_id,
                "name": cluster_name,
                "cluster_type": cluster_type,
            }
        )
        return result

    actual_cluster = endpoint_clusters[cluster_id]

    # Validate attributes
    for required_attr in required_cluster.get("attributes", []):
        attr_id = required_attr["id"]
        attr_name = required_attr["name"]

        # Check in regular attributes and also in AttributeList
        found = False
        if attr_id in actual_cluster.get("attributes", {}):
            found = True
        # Also check in AttributeList for reference
        attr_list = actual_cluster.get("attributes", {}).get("AttributeList", {}).get("AttributeList", [])
        for attr_ref in attr_list:
            if attr_ref.get("id") == attr_id:
                found = True
                break

        if not found:
            result["is_compliant"] = False
            result["missing_elements"].append(
                {
                    "type": "attribute",
                    "id": attr_id,
                    "name": attr_name,
                    "cluster_id": cluster_id,
                    "cluster_name": cluster_name,
                }
            )

    # Validate commands
    for required_cmd in required_cluster.get("commands", []):
        cmd_id = required_cmd["id"]
        cmd_name = required_cmd["name"]

        # Check in both GeneratedCommandList and AcceptedCommandList
        found = False
        for cmd_list_name in ["GeneratedCommandList", "AcceptedCommandList"]:
            cmd_list = actual_cluster.get("commands", {}).get(cmd_list_name, {}).get(cmd_list_name, [])
            for cmd in cmd_list:
                if cmd.get("id") == cmd_id:
                    found = True
                    break
            if found:
                break

        if not found:
            result["is_compliant"] = False
            result["missing_elements"].append(
                {
                    "type": "command",
                    "id": cmd_id,
                    "name": cmd_name,
                    "cluster_id": cluster_id,
                    "cluster_name": cluster_name,
                }
            )

    return result


if __name__ == "__main__":
    # Load requirements
    requirements = load_element_requirements()
    print(f"Loaded {len(requirements)} device type requirements")

    # Test with parsed data from file
    try:
        with open("parsed_data.json", "r") as f:
            parsed_data = json.load(f)

        print(f"Loaded parsed data with {len(parsed_data['endpoints'])} endpoints")

        # Run validation
        validation_result = validate_device_compliance(parsed_data, requirements)

        print("\n=== VALIDATION SUMMARY ===")
        print(f"Total Endpoints: {validation_result['summary']['total_endpoints']}")
        print(f"Compliant: {validation_result['summary']['compliant_endpoints']}")
        print(f"Non-Compliant: {validation_result['summary']['non_compliant_endpoints']}")

        for endpoint in validation_result["endpoints"]:
            print(f"\nEndpoint {endpoint['endpoint']}: {'✅ COMPLIANT' if endpoint['is_compliant'] else '❌ NON-COMPLIANT'}")
            for device_type in endpoint["device_types"]:
                if "device_type_name" in device_type:
                    print(f"  Device Type: {device_type['device_type_name']} ({device_type['device_type_id']})")
                    if not device_type.get("is_compliant", True):
                        print(f"    Missing {len(device_type['missing_elements'])} elements")
                        for missing in device_type["missing_elements"][:3]:  # Show first 3
                            print(f"      - {missing['type']}: {missing['name']} ({missing['id']})")
                        if len(device_type["missing_elements"]) > 3:
                            print(f"      ... and {len(device_type['missing_elements']) - 3} more")

        # Save validation results
        with open("validation_results.json", "w") as f:
            json.dump(validation_result, f, indent=2)
        print("\nValidation results saved to validation_results.json")

    except FileNotFoundError:
        print("parsed_data.json file not found")
    except Exception as e:
        print(f"Error: {e}")
