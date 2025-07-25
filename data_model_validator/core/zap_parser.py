import json
import logging
import time
from typing import Dict, List, Any, Union

from utils.helper import convert_to_snake_case

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_zap_file(zap_content: str) -> Dict[str, Any]:
    """Parse ZAP file content and convert to parsed_data format compatible with wildcard logs.
    
    :param zap_content: Raw ZAP file content as string
    :type zap_content: str
    :returns: Parsed data in the same format as wildcard logs parser
    :rtype: Dict[str, Any]
    :raises ValueError: If ZAP file format is invalid or unsupported
    """
    start_time = time.time()
    logger.info("Starting ZAP file parsing...")
    
    try:
        # Parse JSON content
        zap_data = json.loads(zap_content)
        logger.info("ZAP JSON parsed successfully")
        
        # Validate basic structure
        if "endpointTypes" not in zap_data or "endpoints" not in zap_data:
            raise ValueError("Invalid ZAP file: missing endpointTypes or endpoints")
        
        endpoint_types = zap_data["endpointTypes"]
        endpoints = zap_data["endpoints"]
        
        logger.info(f"Found {len(endpoint_types)} endpoint types and {len(endpoints)} endpoints")
        
        # Build the result in wildcard log format
        result = {"endpoints": []}
        
        # Process each endpoint instance
        for endpoint_instance in endpoints:
            endpoint_id = endpoint_instance["endpointId"]
            endpoint_type_index = endpoint_instance.get("endpointTypeIndex", 0)
            
            # Find the corresponding endpoint type
            if endpoint_type_index >= len(endpoint_types):
                logger.warning(f"Endpoint {endpoint_id} references invalid endpoint type index {endpoint_type_index}")
                continue
                
            endpoint_type = endpoint_types[endpoint_type_index]
            
            # Convert endpoint to parsed format
            parsed_endpoint = convert_endpoint_to_parsed_format(endpoint_id, endpoint_type)
            result["endpoints"].append(parsed_endpoint)
        
        logger.info(f"ZAP parsing completed in {time.time() - start_time:.2f}s")
        return result
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in ZAP file: {str(e)}")
    except Exception as e:
        logger.error(f"Error parsing ZAP file: {str(e)}")
        raise ValueError(f"Failed to parse ZAP file: {str(e)}")


def convert_endpoint_to_parsed_format(endpoint_id: int, endpoint_type: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a ZAP endpoint type to parsed endpoint format.
    
    :param endpoint_id: The endpoint ID
    :type endpoint_id: int
    :param endpoint_type: ZAP endpoint type data
    :type endpoint_type: Dict[str, Any]
    :returns: Parsed endpoint data
    :rtype: Dict[str, Any]
    """
    logger.info(f"Converting endpoint {endpoint_id} ({endpoint_type.get('name', 'Unknown')})")
    
    parsed_endpoint = {
        "endpoint": endpoint_id,
        "clusters": {}
    }
    
    # Process clusters
    clusters = endpoint_type.get("clusters", [])
    for cluster_data in clusters:
        if not cluster_data.get("enabled", False):
            continue  # Skip disabled clusters
            
        cluster_id = f"0x{cluster_data['code']:04X}"
        side = cluster_data.get("side", "server")
        
        # Only process server-side clusters for consistency with wildcard logs
        if side != "server":
            continue
            
        # Convert cluster to parsed format
        parsed_cluster = convert_cluster_to_parsed_format(cluster_data)
        parsed_endpoint["clusters"][cluster_id] = parsed_cluster
    
    # Generate descriptor cluster data for this specific endpoint
    descriptor_data = generate_endpoint_descriptor_data(endpoint_id, endpoint_type, clusters)
    if descriptor_data:
        if "0x001D" in parsed_endpoint["clusters"]:
            # Merge with existing descriptor data
            parsed_endpoint["clusters"]["0x001D"]["attributes"].update(descriptor_data["attributes"])
        else:
            # Add descriptor cluster
            parsed_endpoint["clusters"]["0x001D"] = descriptor_data
    
    return parsed_endpoint


def convert_cluster_to_parsed_format(cluster_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a ZAP cluster to parsed cluster format.
    
    :param cluster_data: ZAP cluster data
    :type cluster_data: Dict[str, Any]
    :returns: Parsed cluster data
    :rtype: Dict[str, Any]
    """
    cluster_name = cluster_data.get("name", "Unknown")
    cluster_code = cluster_data.get("code", 0)
    
    logger.debug(f"Converting cluster {cluster_name} (0x{cluster_code:04X})")
    
    parsed_cluster = {
        "attributes": {},
        "commands": {},
        "events": {},
        "features": {}
    }
    
    # Process attributes
    attributes = cluster_data.get("attributes", [])
    attribute_list = []
    server_list = []
    client_list = []
    generated_command_list = []
    accepted_command_list = []
    event_list = []
    feature_map = None
    cluster_revision = None
    
    for attr in attributes:
        if not attr.get("included", False):
            continue  # Skip non-included attributes
            
        attr_code = attr["code"]
        attr_name = attr["name"]
        attr_id = f"0x{attr_code:04X}"
        
        # Create attribute entry for AttributeList
        attribute_list.append({
            "id": attr_id,
            "name": convert_to_snake_case(attr_name)
        })
        
        # Handle special attributes
        if attr_code == 0xFFFC:  # FeatureMap
            feature_map = attr.get("defaultValue", 0)
        elif attr_code == 0xFFFD:  # ClusterRevision
            cluster_revision = attr.get("defaultValue", 1)
        elif attr_code == 0xFFF8:  # GeneratedCommandList
            # Will be populated from commands
            pass
        elif attr_code == 0xFFF9:  # AcceptedCommandList
            # Will be populated from commands
            pass
        elif attr_code == 0xFFFA:  # EventList
            # Will be populated from events
            pass
        elif attr_code == 0xFFFB:  # AttributeList
            # Will be populated from all attributes
            pass
        elif attr_code == 0x0001 and cluster_code == 0x001D:  # ServerList in Descriptor
            # Will be populated from all server clusters
            pass
        elif attr_code == 0x0002 and cluster_code == 0x001D:  # ClientList in Descriptor
            # Will be populated from all client clusters
            pass
        else:
            # Regular attribute
            attr_data = {
                attr_name: attr.get("defaultValue", ""),
            }
            # Add additional attribute metadata if available
            if "type" in attr:
                attr_data["type"] = attr["type"]
            if "reportable" in attr:
                attr_data["reportable"] = attr["reportable"]
                
            parsed_cluster["attributes"][attr_id] = attr_data
    
    # Process commands
    commands = cluster_data.get("commands", [])
    for cmd in commands:
        if not cmd.get("isEnabled", False):
            continue  # Skip disabled commands
            
        cmd_code = cmd["code"]
        cmd_name = cmd["name"]
        cmd_id = f"0x{cmd_code:04X}"
        
        cmd_entry = {
            "id": cmd_id,
            "name": convert_to_snake_case(cmd_name)
        }
        
        # ZAP uses isIncoming (1/0) and source ("client"/"server") instead of incoming/outgoing
        is_incoming = cmd.get("isIncoming", 0)
        source = cmd.get("source", "")
        
        # For server-side clusters:
        # - isIncoming=1, source="client" means AcceptedCommandList (client->server)
        # - isIncoming=0, source="server" means GeneratedCommandList (server->client)
        if is_incoming == 1 and source == "client":
            accepted_command_list.append(cmd_entry)
        elif is_incoming == 0 and source == "server":
            generated_command_list.append(cmd_entry)
    
    # Process events
    events = cluster_data.get("events", [])
    for event in events:
        if not event.get("included", False):
            continue  # Skip non-included events
            
        event_code = event["code"]
        event_name = event["name"]
        event_id = f"0x{event_code:04X}"
        
        event_list.append({
            "id": event_id,
            "name": convert_to_snake_case(event_name)
        })
    
    # Populate special attributes
    if attribute_list:
        parsed_cluster["attributes"]["0xFFFB"] = {
            "AttributeList": attribute_list
        }
    
    if accepted_command_list:
        parsed_cluster["commands"]["AcceptedCommandList"] = {
            "AcceptedCommandList": accepted_command_list
        }
    
    if generated_command_list:
        parsed_cluster["commands"]["GeneratedCommandList"] = {
            "GeneratedCommandList": generated_command_list
        }
    
    if event_list:
        parsed_cluster["events"]["EventList"] = {
            "EventList": event_list
        }
    
    if feature_map is not None:
        parsed_cluster["features"]["FeatureMap"] = {
            "FeatureMap": feature_map
        }
    
    if cluster_revision is not None:
        parsed_cluster["features"]["ClusterRevision"] = {
            "ClusterRevision": cluster_revision
        }
    
    return parsed_cluster


def generate_endpoint_descriptor_data(endpoint_id: int, endpoint_type: Dict[str, Any], clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate descriptor cluster data for a specific endpoint.
    
    :param endpoint_id: The endpoint ID
    :type endpoint_id: int
    :param endpoint_type: ZAP endpoint type data
    :type endpoint_type: Dict[str, Any]
    :param clusters: List of clusters for this endpoint
    :type clusters: List[Dict[str, Any]]
    :returns: Descriptor cluster data
    :rtype: Dict[str, Any]
    """
    # Extract device types for this endpoint
    device_types = []
    device_type_data = endpoint_type.get("deviceTypes", [])
    
    if not device_type_data and "deviceTypeRef" in endpoint_type:
        # Fallback to deviceTypeRef if deviceTypes is not available
        device_type_ref = endpoint_type["deviceTypeRef"]
        device_types.append({
            "DeviceType": f"0x{device_type_ref['code']:04X}",
            "Revision": device_type_ref.get("revision", 1)
        })
    else:
        for dt in device_type_data:
            device_types.append({
                "DeviceType": f"0x{dt['code']:04X}",
                "Revision": dt.get("revision", 1)
            })
    
    # Extract device versions if available
    device_versions = endpoint_type.get("deviceVersions", [])
    if device_versions and len(device_versions) == len(device_types):
        for i, version in enumerate(device_versions):
            if i < len(device_types):
                device_types[i]["Revision"] = version
    
    # Generate server list from clusters in this endpoint
    server_clusters = []
    client_clusters = []
    
    for cluster in clusters:
        if cluster.get("enabled", False):
            cluster_id = f"0x{cluster['code']:04X}"
            side = cluster.get("side", "server")
            
            if side == "server":
                server_clusters.append({"id": cluster_id})
            elif side == "client":
                client_clusters.append({"id": cluster_id})
    
    # Parts list - only for root endpoint (endpoint 0)
    parts_list = []
    if endpoint_id == 0:
        # For root endpoint, parts list would contain other endpoint IDs
        # This would need to be populated from the global endpoints list
        # For now, we'll leave it empty as it should be populated at the global level
        pass
    
    descriptor_data = {
        "attributes": {
            "0x0000": {
                "DeviceTypeList": device_types
            },
            "0x0001": {
                "ServerList": server_clusters
            },
            "0x0002": {
                "ClientList": client_clusters
            },
            "0x0003": {
                "PartsList": parts_list
            }
        },
        "commands": {},
        "events": {},
        "features": {}
    }
    
    return descriptor_data


def parse_zap_file_with_descriptor_enhancement(zap_content: str) -> Dict[str, Any]:
    """Parse ZAP file and enhance with proper descriptor cluster data.
    
    :param zap_content: Raw ZAP file content as string
    :type zap_content: str
    :returns: Parsed data with enhanced descriptor cluster
    :rtype: Dict[str, Any]
    """
    # Do the parsing with per-endpoint descriptor generation
    result = parse_zap_file(zap_content)
    
    # Post-process to fix the parts list for endpoint 0
    try:
        # Find all endpoint IDs except 0
        other_endpoint_ids = []
        for endpoint in result["endpoints"]:
            if endpoint["endpoint"] != 0:
                other_endpoint_ids.append(endpoint["endpoint"])
        
        # Update the parts list for endpoint 0
        for endpoint in result["endpoints"]:
            if endpoint["endpoint"] == 0 and "0x001D" in endpoint["clusters"]:
                descriptor_cluster = endpoint["clusters"]["0x001D"]
                if "attributes" in descriptor_cluster and "0x0003" in descriptor_cluster["attributes"]:
                    descriptor_cluster["attributes"]["0x0003"]["PartsList"] = other_endpoint_ids
                    logger.info(f"Updated PartsList for endpoint 0: {other_endpoint_ids}")
                break
        
        return result
        
    except Exception as e:
        logger.error(f"Error post-processing descriptor clusters: {str(e)}")
        # Return basic parsing result if post-processing fails
        return result 