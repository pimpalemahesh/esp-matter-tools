import json
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------- Validation-Specific Functions -------------


def find_client_cluster(endpoint_clusters, client_cluster_id):
    """Find a client cluster by searching through all server clusters' ClientList

    :param endpoint_clusters: param client_cluster_id:
    :param client_cluster_id:

    """
    for server_cluster_id, server_cluster_data in endpoint_clusters.items():
        client_lists_to_check = []

        # Check all possible locations where ClientList might be stored
        if "ClientList" in server_cluster_data:
            client_lists_to_check.append(
                ("top-level", server_cluster_data["ClientList"]))

        if ("attributes" in server_cluster_data
                and "ClientList" in server_cluster_data["attributes"]):
            client_lists_to_check.append(
                ("attributes-direct",
                 server_cluster_data["attributes"]["ClientList"]))

        if "attributes" in server_cluster_data:
            for attr_id, attr_data in server_cluster_data["attributes"].items(
            ):
                if isinstance(attr_data, dict) and "ClientList" in attr_data:
                    client_lists_to_check.append(
                        (f"attribute-{attr_id}", attr_data["ClientList"]))

        # Check each potential ClientList
        for location, client_list in client_lists_to_check:
            if isinstance(client_list, list):
                for client_ref in client_list:
                    if (isinstance(client_ref, dict)
                            and client_ref.get("id") == client_cluster_id):
                        return True
            elif isinstance(client_list, dict) and "ClientList" in client_list:
                nested_list = client_list["ClientList"]
                if isinstance(nested_list, list):
                    for client_ref in nested_list:
                        if (isinstance(client_ref, dict)
                                and client_ref.get("id") == client_cluster_id):
                            return True

    return False


def validate_feature_map(actual_feature_map, required_features, cluster_id,
                         cluster_name):
    """Validate features using bitwise operations on feature_map

    :param actual_feature_map: param required_features:
    :param cluster_id: param cluster_name:
    :param required_features:
    :param cluster_name:

    """
    if not required_features:
        return True, []

    missing_features = []

    try:
        # Convert feature_map to integer if it's a string
        if isinstance(actual_feature_map, str):
            if actual_feature_map.startswith("0x"):
                feature_map_value = int(actual_feature_map, 16)
            else:
                feature_map_value = int(actual_feature_map)
        elif isinstance(actual_feature_map, int):
            feature_map_value = actual_feature_map
        else:
            return False, [{
                "type":
                "feature",
                "message":
                f"Invalid feature_map format in cluster {cluster_id}",
            }]

        for required_feature in required_features:
            feature_id = required_feature.get("id")
            feature_name = required_feature.get("name", "unknown")

            # Convert feature ID to integer bitmask
            if isinstance(feature_id, str) and feature_id.startswith("0x"):
                feature_bitmask = int(feature_id, 16)
            elif isinstance(feature_id, int):
                feature_bitmask = feature_id
            else:
                continue

            # Check if the feature bitmask is set in the feature_map
            if not (feature_map_value & feature_bitmask):
                missing_features.append({
                    "type":
                    "feature",
                    "id":
                    feature_id,
                    "name":
                    feature_name,
                    "cluster_id":
                    cluster_id,
                    "cluster_name":
                    cluster_name,
                    "feature_bitmask":
                    f"0x{feature_bitmask:X}",
                    "feature_map_value":
                    f"0x{feature_map_value:X}",
                    "check_result":
                    f"0x{feature_map_value:X} & 0x{feature_bitmask:X} = 0x{feature_map_value & feature_bitmask:X}",
                })

        return len(missing_features) == 0, missing_features

    except Exception as e:
        return False, [{
            "type": "feature",
            "message": f"Feature validation error: {str(e)}"
        }]


def validate_feature_specific_elements(actual_cluster, required_features,
                                       cluster_id, cluster_name):
    """Validate feature-specific attributes, commands, and events when features are present

    :param actual_cluster: param required_features:
    :param cluster_id: param cluster_name:
    :param required_features:
    :param cluster_name:

    """
    if not required_features:
        return True, []

    missing_elements = []

    try:
        # Get the actual feature map value
        feature_map_data = actual_cluster.get("features",
                                              {}).get("FeatureMap", {})
        if (not isinstance(feature_map_data, dict)
                or "FeatureMap" not in feature_map_data):
            return True, []  # No feature map, skip feature-specific validation

        actual_feature_map = feature_map_data["FeatureMap"]

        # Convert feature_map to integer
        if isinstance(actual_feature_map, str):
            if actual_feature_map.startswith("0x"):
                feature_map_value = int(actual_feature_map, 16)
            else:
                feature_map_value = int(actual_feature_map)
        elif isinstance(actual_feature_map, int):
            feature_map_value = actual_feature_map
        else:
            return True, []  # Invalid format, skip validation

        # Check each required feature
        for required_feature in required_features:
            feature_id = required_feature.get("id")
            feature_name = required_feature.get("name", "unknown")

            # Convert feature ID to integer bitmask
            if isinstance(feature_id, str) and feature_id.startswith("0x"):
                feature_bitmask = int(feature_id, 16)
            elif isinstance(feature_id, int):
                feature_bitmask = feature_id
            else:
                continue

            # Check if this feature is present (bit is set in feature map)
            if feature_map_value & feature_bitmask:
                # Feature is present, validate its specific attributes, commands, and events

                # Validate feature-specific attributes
                for required_attr in required_feature.get("attributes", []):
                    if not isinstance(required_attr, dict):
                        continue

                    attr_id = required_attr["id"]
                    attr_name = required_attr["name"]

                    # Check if attribute exists
                    found = False

                    # Check in regular attributes
                    if attr_id in actual_cluster.get("attributes", {}):
                        found = True

                    # Also check in AttributeList for reference
                    attr_list = (actual_cluster.get("attributes", {}).get(
                        "AttributeList", {}).get("AttributeList", []))
                    if not found and isinstance(attr_list, list):
                        for attr_ref in attr_list:
                            if (isinstance(attr_ref, dict)
                                    and attr_ref.get("id") == attr_id):
                                found = True
                                break
                            elif isinstance(attr_ref, (int, str)):
                                attr_ref_hex = (f"0x{int(attr_ref):04X}"
                                                if isinstance(attr_ref, int)
                                                else attr_ref)
                                if attr_ref_hex == attr_id:
                                    found = True
                                    break

                    if not found:
                        missing_elements.append({
                            "type":
                            "feature_attribute",
                            "id":
                            attr_id,
                            "name":
                            attr_name,
                            "cluster_id":
                            cluster_id,
                            "cluster_name":
                            cluster_name,
                            "feature_id":
                            feature_id,
                            "feature_name":
                            feature_name,
                            "message":
                            f"Feature '{feature_name}' is present but required attribute '{attr_name}' ({attr_id}) is missing",
                        })

                # Validate feature-specific commands
                for required_cmd in required_feature.get("commands", []):
                    if not isinstance(required_cmd, dict):
                        continue

                    cmd_id = required_cmd["id"]
                    cmd_name = required_cmd["name"]

                    # Check if command exists
                    found = False
                    for cmd_list_name in [
                            "GeneratedCommandList",
                            "AcceptedCommandList",
                    ]:
                        cmd_list = (actual_cluster.get("commands", {}).get(
                            cmd_list_name, {}).get(cmd_list_name, []))
                        if isinstance(cmd_list, list):
                            for cmd in cmd_list:
                                if isinstance(
                                        cmd, dict) and cmd.get("id") == cmd_id:
                                    found = True
                                    break
                                elif isinstance(cmd, (int, str)):
                                    cmd_hex = (f"0x{int(cmd):04X}" if
                                               isinstance(cmd, int) else cmd)
                                    if cmd_hex == cmd_id:
                                        found = True
                                        break
                        if found:
                            break

                    if not found:
                        missing_elements.append({
                            "type":
                            "feature_command",
                            "id":
                            cmd_id,
                            "name":
                            cmd_name,
                            "cluster_id":
                            cluster_id,
                            "cluster_name":
                            cluster_name,
                            "feature_id":
                            feature_id,
                            "feature_name":
                            feature_name,
                            "message":
                            f"Feature '{feature_name}' is present but required command '{cmd_name}' ({cmd_id}) is missing",
                        })

                # Validate feature-specific events
                for required_event in required_feature.get("events", []):
                    if not isinstance(required_event, dict):
                        continue

                    event_id = required_event["id"]
                    event_name = required_event["name"]

                    # Check if event exists
                    found = False
                    event_list = (actual_cluster.get("events", {}).get(
                        "EventList", {}).get("EventList", []))
                    if isinstance(event_list, list):
                        for event in event_list:
                            if isinstance(
                                    event,
                                    dict) and event.get("id") == event_id:
                                found = True
                                break
                            elif isinstance(event, (int, str)):
                                event_hex = (f"0x{int(event):04X}" if
                                             isinstance(event, int) else event)
                                if event_hex == event_id:
                                    found = True
                                    break

                    if not found:
                        missing_elements.append({
                            "type":
                            "feature_event",
                            "id":
                            event_id,
                            "name":
                            event_name,
                            "cluster_id":
                            cluster_id,
                            "cluster_name":
                            cluster_name,
                            "feature_id":
                            feature_id,
                            "feature_name":
                            feature_name,
                            "message":
                            f"Feature '{feature_name}' is present but required event '{event_name}' ({event_id}) is missing",
                        })

        return len(missing_elements) == 0, missing_elements

    except Exception as e:
        return False, [{
            "type":
            "feature_validation",
            "message":
            f"Feature-specific validation error: {str(e)}",
        }]


def validate_revisions(actual_revision, required_revision, item_type, item_id,
                       item_name):
    """Validate revision compatibility - revisions must match exactly

    :param actual_revision: param required_revision:
    :param item_type: param item_id:
    :param item_name:
    :param required_revision:
    :param item_id:

    """
    revision_issues = []

    try:
        # Convert revisions to integers for comparison
        if isinstance(actual_revision, str):
            actual_rev = int(actual_revision)
        elif isinstance(actual_revision, int):
            actual_rev = actual_revision
        else:
            return True, []

        if isinstance(required_revision, str):
            required_rev = int(required_revision)
        elif isinstance(required_revision, int):
            required_rev = required_revision
        else:
            return True, []

        # Check if actual revision exactly matches required revision
        if actual_rev != required_rev:
            revision_issues.append({
                "type":
                "revision_mismatch",
                "item_type":
                item_type,
                "item_id":
                item_id,
                "item_name":
                item_name,
                "actual_revision":
                actual_rev,
                "required_revision":
                required_rev,
                "severity":
                "error",
                "message":
                f"{item_type.title()} {item_name} has revision {actual_rev}, but requires exactly revision {required_rev}",
            })

        return actual_rev == required_rev, revision_issues

    except Exception as e:
        return False, [{
            "type":
            "revision_error",
            "message":
            f"Revision validation error for {item_type} {item_name}: {str(e)}",
        }]


def validate_events_with_warnings(actual_cluster, required_events, cluster_id,
                                  cluster_name):
    """Validate events and provide warnings (not compliance failures)

    :param actual_cluster: param required_events:
    :param cluster_id: param cluster_name:
    :param required_events:
    :param cluster_name:

    """
    event_warnings = []

    if not required_events:
        return event_warnings

    # Check what events are actually present (if any)
    actual_events = actual_cluster.get("events", {})
    present_events = []

    # Look for EventList or direct event entries
    if "EventList" in actual_events:
        event_list = actual_events["EventList"].get("EventList", [])
        if isinstance(event_list, list):
            for event in event_list:
                if isinstance(event, dict):
                    present_events.append(event.get("id", "unknown"))
                elif isinstance(event, (int, str)):
                    present_events.append(f"0x{int(event):04X}" if isinstance(
                        event, int) else event)

    # Add general warning about event validation
    event_warnings.append({
        "type":
        "event_info",
        "cluster_id":
        cluster_id,
        "cluster_name":
        cluster_name,
        "severity":
        "info",
        "message":
        f"Event validation skipped for cluster {cluster_name} - wildcard logs don't typically contain events",
    })

    # List required events as informational
    for required_event in required_events:
        event_id = required_event.get("id")
        event_name = required_event.get("name", "unknown")

        is_present = event_id in present_events

        event_warnings.append({
            "type":
            "event_requirement",
            "cluster_id":
            cluster_id,
            "cluster_name":
            cluster_name,
            "event_id":
            event_id,
            "event_name":
            event_name,
            "is_present":
            is_present,
            "severity":
            "warning" if not is_present else "info",
            "message":
            f"Required event {event_name} ({event_id}) {'found' if is_present else 'not found in wildcard logs'}",
        })

    # If any events are present, note them
    if present_events:
        event_warnings.append({
            "type":
            "event_found",
            "cluster_id":
            cluster_id,
            "cluster_name":
            cluster_name,
            "present_events":
            present_events,
            "severity":
            "info",
            "message":
            f"Found {len(present_events)} events in wildcard logs: {', '.join(present_events)}",
        })

    return event_warnings


def load_element_requirements(chip_version):
    """Load element requirements from JSON file.

    :param chip_version: Version of the chip requirements to load
    :type chip_version: str
    :returns: List of device type requirements, empty list if file not found
    :rtype: list

    """
    try:
        with open(f"data/element_requirements_{chip_version}.json", "r") as f:
            requirements = json.load(f)
            logger.info(
                f"Loaded {len(requirements)} device type requirements for version {chip_version}"
            )
            return requirements
    except FileNotFoundError:
        logger.error(
            f"Element requirements file not found for version {chip_version}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing element requirements: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error loading element requirements: {e}")
        return []


def validate_cluster(endpoint_clusters, required_cluster):
    """Validate a cluster against its requirements

    :param endpoint_clusters: Dictionary of all clusters in the endpoint
    :type endpoint_clusters: dict
    :param required_cluster: Required cluster configuration
    :type required_cluster: dict
    :returns: Validation result with compliance status and missing elements
    :rtype: dict

    """
    if not isinstance(required_cluster, dict):
        raise ValueError(
            f"required_cluster must be a dict, got {type(required_cluster)}")

    cluster_id = required_cluster["id"]
    cluster_name = required_cluster["name"]
    cluster_type = required_cluster.get("type", "server")
    required_revision = required_cluster.get("revision")

    result = {
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "cluster_type": cluster_type,
        "is_compliant": True,
        "missing_elements": [],
        "revision_issues": [],
        "event_warnings": [],
    }

    # Check if cluster exists based on its type
    if cluster_type == "client":
        if find_client_cluster(endpoint_clusters, cluster_id):
            return result
        else:
            result["is_compliant"] = False
            result["missing_elements"].append({
                "type": "cluster",
                "id": cluster_id,
                "name": cluster_name,
                "cluster_type": cluster_type,
            })
            return result
    else:
        # For server clusters, check if it exists as a top-level cluster
        if cluster_id not in endpoint_clusters:
            result["is_compliant"] = False
            result["missing_elements"].append({
                "type": "cluster",
                "id": cluster_id,
                "name": cluster_name,
                "cluster_type": cluster_type,
            })
            return result

        actual_cluster = endpoint_clusters[cluster_id]

        # Validate cluster revision
        actual_revision = None
        cluster_revision_data = actual_cluster.get("features", {}).get(
            "ClusterRevision", {})
        if (isinstance(cluster_revision_data, dict)
                and "ClusterRevision" in cluster_revision_data):
            actual_revision = cluster_revision_data["ClusterRevision"]

        if actual_revision is not None and required_revision is not None:
            revision_compliant, revision_issues = validate_revisions(
                actual_revision, required_revision, "cluster", cluster_id,
                cluster_name)
            if not revision_compliant:
                result["is_compliant"] = False
            result["revision_issues"].extend(revision_issues)

        # Validate attributes
        for required_attr in required_cluster.get("attributes", []):
            if not isinstance(required_attr, dict):
                continue

            attr_id = required_attr["id"]
            attr_name = required_attr["name"]

            # Check if attribute exists
            found = False

            # Check in regular attributes
            if attr_id in actual_cluster.get("attributes", {}):
                found = True

            # Also check in AttributeList for reference
            attr_list = (actual_cluster.get("attributes", {}).get(
                "AttributeList", {}).get("AttributeList", []))
            if not found and isinstance(attr_list, list):
                for attr_ref in attr_list:
                    if isinstance(attr_ref,
                                  dict) and attr_ref.get("id") == attr_id:
                        found = True
                        break
                    elif isinstance(attr_ref, (int, str)):
                        attr_ref_hex = (f"0x{int(attr_ref):04X}" if isinstance(
                            attr_ref, int) else attr_ref)
                        if attr_ref_hex == attr_id:
                            found = True
                            break

            if not found:
                result["is_compliant"] = False
                result["missing_elements"].append({
                    "type": "attribute",
                    "id": attr_id,
                    "name": attr_name,
                    "cluster_id": cluster_id,
                    "cluster_name": cluster_name,
                })

        # Validate commands
        for required_cmd in required_cluster.get("commands", []):
            if not isinstance(required_cmd, dict):
                continue

            cmd_id = required_cmd["id"]
            cmd_name = required_cmd["name"]

            # Check if command exists
            found = False
            for cmd_list_name in [
                    "GeneratedCommandList", "AcceptedCommandList"
            ]:
                cmd_list = (actual_cluster.get("commands", {}).get(
                    cmd_list_name, {}).get(cmd_list_name, []))
                if isinstance(cmd_list, list):
                    for cmd in cmd_list:
                        if isinstance(cmd, dict) and cmd.get("id") == cmd_id:
                            found = True
                            break
                        elif isinstance(cmd, (int, str)):
                            cmd_hex = (f"0x{int(cmd):04X}" if isinstance(
                                cmd, int) else cmd)
                            if cmd_hex == cmd_id:
                                found = True
                                break
                if found:
                    break

            if not found:
                result["is_compliant"] = False
                result["missing_elements"].append({
                    "type": "command",
                    "id": cmd_id,
                    "name": cmd_name,
                    "cluster_id": cluster_id,
                    "cluster_name": cluster_name,
                })

        # Validate features
        required_features = required_cluster.get("features", [])
        if required_features:
            feature_map_data = actual_cluster.get("features",
                                                  {}).get("FeatureMap", {})
            if isinstance(feature_map_data,
                          dict) and "FeatureMap" in feature_map_data:
                actual_feature_map = feature_map_data["FeatureMap"]
                feature_compliant, missing_features = validate_feature_map(
                    actual_feature_map, required_features, cluster_id,
                    cluster_name)
                if not feature_compliant:
                    result["is_compliant"] = False
                    result["missing_elements"].extend(missing_features)

                # Validate feature-specific attributes, commands, and events
                feature_specific_compliant, feature_specific_missing = (
                    validate_feature_specific_elements(actual_cluster,
                                                       required_features,
                                                       cluster_id,
                                                       cluster_name))
                if not feature_specific_compliant:
                    result["is_compliant"] = False
                    result["missing_elements"].extend(feature_specific_missing)
            else:
                result["is_compliant"] = False
                result["missing_elements"].append({
                    "type": "feature",
                    "message":
                    f"FeatureMap not found in cluster {cluster_name}, but features are required",
                    "cluster_id": cluster_id,
                    "cluster_name": cluster_name,
                })

        # Validate events (warnings only)
        required_events = required_cluster.get("events", [])
        event_warnings = validate_events_with_warnings(actual_cluster,
                                                       required_events,
                                                       cluster_id,
                                                       cluster_name)
        result["event_warnings"].extend(event_warnings)

    return result


def validate_single_device_type(endpoint, device_type_id, device_requirements):
    """Validate a single device type against its requirements.

    :param endpoint: The endpoint data containing clusters
    :type endpoint: dict
    :param device_type_id: The device type ID to validate
    :type device_type_id: int
    :param device_requirements: The requirements for this device type
    :type device_requirements: dict
    :returns: Validation result with compliance status and missing elements
    :rtype: dict

    """
    if not isinstance(device_requirements, dict):
        raise ValueError(
            f"device_requirements must be a dict, got {type(device_requirements)}"
        )

    if not isinstance(endpoint, dict):
        raise ValueError(f"endpoint must be a dict, got {type(endpoint)}")

    result = {
        "device_type_id": device_type_id,
        "device_type_name": device_requirements.get("name", "unknown"),
        "is_compliant": True,
        "missing_elements": [],
        "cluster_validations": [],
        "revision_issues": [],
        "event_warnings": [],
    }

    required_clusters = device_requirements.get("clusters", [])
    endpoint_clusters = endpoint.get("clusters", {})

    # Validate device type revision
    required_device_revision = device_requirements.get("revision")

    # Find device type revision from descriptor cluster
    descriptor_cluster = endpoint_clusters.get("0x001D", {})
    device_type_list = None
    actual_device_revision = None

    # Look for DeviceTypeList in descriptor cluster attributes
    descriptor_attrs = descriptor_cluster.get("attributes", {})
    for attr_id, attr_data in descriptor_attrs.items():
        if "DeviceTypeList" in attr_data:
            device_type_list = attr_data["DeviceTypeList"]
            break

    if device_type_list:
        device_type_hex = f"0x{device_type_id:04X}"
        for device_type_info in device_type_list:
            if isinstance(device_type_info, dict):
                dt_id = device_type_info.get("DeviceType")
                if dt_id == device_type_hex:
                    actual_device_revision = device_type_info.get("Revision")
                    break

    # Validate device type revision
    if actual_device_revision is not None and required_device_revision is not None:
        device_type_name = device_requirements.get("name", "unknown")
        revision_compliant, revision_issues = validate_revisions(
            actual_device_revision,
            required_device_revision,
            "device_type",
            device_type_hex,
            device_type_name,
        )
        if not revision_compliant:
            result["is_compliant"] = False
        result["revision_issues"].extend(revision_issues)

    # Validate clusters
    for required_cluster in required_clusters:
        if not isinstance(required_cluster, dict):
            continue

        cluster_name = required_cluster.get("name", "unknown")

        try:
            cluster_validation = validate_cluster(endpoint_clusters,
                                                  required_cluster)
            result["cluster_validations"].append(cluster_validation)

            # Aggregate results
            if not cluster_validation["is_compliant"]:
                result["is_compliant"] = False
                result["missing_elements"].extend(
                    cluster_validation["missing_elements"])

            # Collect revision issues and event warnings
            if "revision_issues" in cluster_validation:
                result["revision_issues"].extend(
                    cluster_validation["revision_issues"])

            if "event_warnings" in cluster_validation:
                result["event_warnings"].extend(
                    cluster_validation["event_warnings"])

        except Exception as cluster_error:
            logger.error(
                f"Error validating cluster {cluster_name}: {cluster_error}")
            result["cluster_validations"].append({
                "cluster_id":
                required_cluster.get("id", "unknown"),
                "cluster_name":
                cluster_name,
                "cluster_type":
                required_cluster.get("type", "server"),
                "is_compliant":
                False,
                "missing_elements": [{
                    "type":
                    "error",
                    "message":
                    f"Cluster validation error: {str(cluster_error)}",
                }],
                "revision_issues": [],
                "event_warnings": [],
            })
            result["is_compliant"] = False

    return result


def validate_device_compliance(parsed_data, element_requirements,
                               chip_version):
    """Validate if the device meets all requirements for its device types.

    :param parsed_data: The parsed device data containing endpoints and clusters
    :type parsed_data: dict
    :param element_requirements: List of device type requirements
    :type element_requirements: list
    :param chip_version: The chip version used for validation
    :type chip_version: str
    :returns: Validation results with compliance status and missing elements
    :rtype: dict

    """
    start_time = time.time()
    logger.info("Starting device compliance validation...")

    # Validate input parameters
    if not isinstance(parsed_data, dict):
        raise ValueError("parsed_data must be a dictionary")

    if "endpoints" not in parsed_data:
        raise ValueError("parsed_data must contain 'endpoints' key")

    validation_results = {
        "endpoints": [],
        "summary": {
            "total_endpoints": 0,
            "compliant_endpoints": 0,
            "non_compliant_endpoints": 0,
            "total_revision_issues": 0,
            "total_event_warnings": 0,
        },
    }

    # Create requirements lookup dictionary
    requirements_lookup = {}
    try:
        for i, device in enumerate(element_requirements):
            if not isinstance(device, dict):
                continue

            device_id = device.get("id")
            if device_id:
                if isinstance(device_id, str) and device_id.startswith("0x"):
                    int_id = int(device_id, 16)
                    requirements_lookup[int_id] = device
                elif isinstance(device_id, int):
                    requirements_lookup[device_id] = device

            # Progress update for large requirement sets
            if len(element_requirements) > 100 and i % 50 == 0:
                logger.info(
                    f"Processing requirement {i + 1} of {len(element_requirements)}..."
                )
    except Exception as e:
        logger.error(f"Error processing device requirements: {e}")
        raise ValueError(f"Failed to process device requirements: {e}")

    logger.info(f"Loaded {len(requirements_lookup)} device type requirements")

    endpoints_list = parsed_data.get("endpoints", [])
    total_endpoints = len(endpoints_list)

    # Counters for summary
    total_revision_issues = 0
    total_event_warnings = 0

    for i, endpoint in enumerate(endpoints_list):
        # More frequent progress updates
        logger.info(f"Validating endpoint {i + 1} of {total_endpoints}...")

        endpoint_result = {
            "endpoint": endpoint["endpoint"],
            "device_types": [],
            "is_compliant": True,
            "missing_elements": [],
            "extra_elements": [],
            "revision_issues": [],
            "event_warnings": [],
        }

        # Find device types from descriptor cluster
        descriptor_cluster = endpoint.get("clusters", {}).get("0x001D", {})
        device_type_list = None

        # Look for DeviceTypeList in attributes
        descriptor_attrs = descriptor_cluster.get("attributes", {})
        for attr_id, attr_data in descriptor_attrs.items():
            if "DeviceTypeList" in attr_data:
                device_type_list = attr_data["DeviceTypeList"]
                break

        if not device_type_list:
            endpoint_result["device_types"].append(
                {"error": "No DeviceTypeList found in descriptor cluster"})
            endpoint_result["is_compliant"] = False
        else:
            # Validate each device type
            for device_type_index, device_type_info in enumerate(
                    device_type_list):
                try:
                    # Update progress for device type validation
                    if len(device_type_list) > 1:
                        logger.info(
                            f"Endpoint {i + 1}/{total_endpoints}: Device type {device_type_index + 1}/{len(device_type_list)}"
                        )

                    # Handle different formats of device type info
                    if isinstance(device_type_info, dict):
                        device_type_id = device_type_info.get("DeviceType")
                        if isinstance(device_type_id, dict):
                            device_type_id = device_type_id.get(
                                "id") or device_type_id.get("DeviceType")
                    elif isinstance(device_type_info, (int, str)):
                        device_type_id = device_type_info
                    else:
                        endpoint_result["device_types"].append({
                            "error":
                            f"Unexpected device type format: {type(device_type_info)} - {device_type_info}"
                        })
                        endpoint_result["is_compliant"] = False
                        continue

                    # Convert device type ID to integer for lookup
                    if isinstance(device_type_id, str):
                        if device_type_id.startswith("0x"):
                            device_type_id_int = int(device_type_id, 16)
                        else:
                            device_type_id_int = int(device_type_id)
                    elif isinstance(device_type_id, int):
                        device_type_id_int = device_type_id
                    else:
                        endpoint_result["device_types"].append({
                            "error":
                            f"Invalid device type ID format: {type(device_type_id)} - {device_type_id}"
                        })
                        endpoint_result["is_compliant"] = False
                        continue

                    # Look up requirements for this device type
                    if device_type_id_int in requirements_lookup:
                        device_requirements = requirements_lookup[
                            device_type_id_int]

                        # Validate the device type
                        device_validation = validate_single_device_type(
                            endpoint, device_type_id_int, device_requirements)

                        endpoint_result["device_types"].append(
                            device_validation)

                        # Aggregate results
                        if not device_validation["is_compliant"]:
                            endpoint_result["is_compliant"] = False

                        endpoint_result["missing_elements"].extend(
                            device_validation.get("missing_elements", []))

                        endpoint_result["revision_issues"].extend(
                            device_validation.get("revision_issues", []))

                        endpoint_result["event_warnings"].extend(
                            device_validation.get("event_warnings", []))

                        # Update counters
                        total_revision_issues += len(
                            device_validation.get("revision_issues", []))
                        total_event_warnings += len(
                            device_validation.get("event_warnings", []))

                    else:
                        endpoint_result["device_types"].append({
                            "device_type_id":
                            device_type_id_int,
                            "device_type_name":
                            "unknown",
                            "error":
                            f"No requirements found for device type 0x{device_type_id_int:04X}",
                        })
                        endpoint_result["is_compliant"] = False

                except Exception as device_error:
                    logger.error(
                        f"Error validating device type {device_type_info}: {device_error}"
                    )
                    endpoint_result["device_types"].append({
                        "error":
                        f"Device type validation error: {str(device_error)}"
                    })
                    endpoint_result["is_compliant"] = False

        validation_results["endpoints"].append(endpoint_result)

        # Update progress after each endpoint
        logger.info(f"Completed endpoint {i + 1} of {total_endpoints}")

    # Calculate summary statistics
    compliant_endpoints = sum(1 for ep in validation_results["endpoints"]
                              if ep["is_compliant"])
    non_compliant_endpoints = total_endpoints - compliant_endpoints

    validation_results["summary"].update({
        "total_endpoints":
        total_endpoints,
        "compliant_endpoints":
        compliant_endpoints,
        "non_compliant_endpoints":
        non_compliant_endpoints,
        "total_revision_issues":
        total_revision_issues,
        "total_event_warnings":
        total_event_warnings,
    })

    logger.info(f"Validation completed in {time.time() - start_time:.2f}s")

    return validation_results
