#!/usr/bin/env python3

# Copyright 2025 Espressif Systems (Shanghai) PTE LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Device composition validation checks inspired by TC_DeviceBasicComposition
and TC_DeviceConformance from the connectedhomeip test suite.

These checks validate the structural correctness of a Matter device's data model
using only wildcard read data (no live device needed).
"""

import logging
from typing import List, Tuple

from dmv_tool.utils.helpers import convert_to_int, convert_to_hex

from .utils import (
    get_nested_list,
    find_element_in_list,
    find_duplicates_in_element_list,
    extract_id_from_element,
)
from .constants import (
    DESCRIPTOR_CLUSTER_ID,
    DESCRIPTOR_SERVER_LIST_ATTRIBUTE_ID,
    DESCRIPTOR_PARTS_LIST_ATTRIBUTE_ID,
    DEVICE_TYPE_LIST_ATTRIBUTE_ID,
    ROOT_NODE_DEVICE_TYPE_ID,
    ROOT_NODE_ALLOWED_DEVICE_TYPES,
    NON_APPLICATION_DEVICE_TYPES,
    REQUIRED_ROOT_NODE_CLUSTER_IDS,
    REQUIRED_ROOT_NODE_CLUSTER_NAMES,
    ROOT_NODE_RESTRICTED_CLUSTER_IDS,
    ROOT_NODE_RESTRICTED_CLUSTER_NAMES,
)

logger = logging.getLogger(__name__)


def _get_endpoint_by_id(parsed_data, endpoint_id):
    """Get an endpoint by its ID from parsed data.

    Args:
        parsed_data: Parsed device data
        endpoint_id: Endpoint ID to find

    Returns:
        Endpoint dict or None
    """
    for ep in parsed_data.get("endpoints", []):
        if ep.get("id") == endpoint_id:
            return ep
    return None


def _get_device_type_ids_for_endpoint(endpoint):
    """Extract device type IDs from an endpoint's Descriptor DeviceTypeList.

    Args:
        endpoint: Endpoint dict

    Returns:
        List of device type IDs as integers
    """
    descriptor_cluster = endpoint.get("clusters", {}).get(DESCRIPTOR_CLUSTER_ID, {})
    descriptor_attrs = descriptor_cluster.get("attributes", {})
    device_type_list = descriptor_attrs.get(DEVICE_TYPE_LIST_ATTRIBUTE_ID, {}).get(
        "DeviceTypeList", []
    )

    device_type_ids = []
    for dt_info in device_type_list:
        if isinstance(dt_info, dict):
            dt = dt_info.get("DeviceType")
            if isinstance(dt, dict):
                dt_id_val = dt.get("id") or dt.get("DeviceType")
            elif isinstance(dt, (int, str)):
                dt_id_val = dt
            else:
                continue
            dt_id_int = convert_to_int(dt_id_val)
            if dt_id_int is not None:
                device_type_ids.append(dt_id_int)
    return device_type_ids


def _get_device_type_revisions_for_endpoint(endpoint):
    """Extract device type revisions from an endpoint's Descriptor DeviceTypeList.

    Args:
        endpoint: Endpoint dict

    Returns:
        List of (device_type_id_int, revision) tuples
    """
    descriptor_cluster = endpoint.get("clusters", {}).get(DESCRIPTOR_CLUSTER_ID, {})
    descriptor_attrs = descriptor_cluster.get("attributes", {})
    device_type_list = descriptor_attrs.get(DEVICE_TYPE_LIST_ATTRIBUTE_ID, {}).get(
        "DeviceTypeList", []
    )

    result = []
    for dt_info in device_type_list:
        if isinstance(dt_info, dict):
            dt = dt_info.get("DeviceType")
            if isinstance(dt, dict):
                dt_id_val = dt.get("id") or dt.get("DeviceType")
            elif isinstance(dt, (int, str)):
                dt_id_val = dt
            else:
                continue
            dt_id_int = convert_to_int(dt_id_val)
            revision = dt_info.get("Revision")
            if dt_id_int is not None:
                result.append((dt_id_int, revision))
    return result


def _get_server_cluster_ids(endpoint):
    """Get server cluster IDs present on an endpoint.

    This gets cluster IDs from the Descriptor ServerList attribute.

    Args:
        endpoint: Endpoint dict

    Returns:
        Set of cluster ID strings (hex format)
    """
    descriptor_cluster = endpoint.get("clusters", {}).get(DESCRIPTOR_CLUSTER_ID, {})
    descriptor_attrs = descriptor_cluster.get("attributes", {})
    server_list_attr = descriptor_attrs.get(DESCRIPTOR_SERVER_LIST_ATTRIBUTE_ID, {})
    server_list = server_list_attr.get("ServerList", [])

    cluster_ids = set()
    for server in server_list:
        if isinstance(server, dict):
            sid = server.get("id")
            if sid:
                cluster_ids.add(sid)
        elif isinstance(server, (int, str)):
            hex_id = convert_to_hex(server)
            if hex_id:
                cluster_ids.add(hex_id)
    return cluster_ids


def _get_parts_list(endpoint):
    """Get PartsList from an endpoint's Descriptor cluster.

    Args:
        endpoint: Endpoint dict

    Returns:
        List of endpoint IDs in PartsList
    """
    descriptor_cluster = endpoint.get("clusters", {}).get(DESCRIPTOR_CLUSTER_ID, {})
    descriptor_attrs = descriptor_cluster.get("attributes", {})
    parts_list_attr = descriptor_attrs.get(DESCRIPTOR_PARTS_LIST_ATTRIBUTE_ID, {})
    return parts_list_attr.get("PartsList", [])


def check_endpoint_exists(parsed_data, endpoint_id=0):
    """Check that a specific endpoint exists.

    Corresponds to TC_SM_1_1 Step 2.

    Args:
        parsed_data: Parsed device data
        endpoint_id: Endpoint ID to check (default 0)

    Returns:
        Tuple of (success, list of problem dicts)
    """
    problems = []
    ep = _get_endpoint_by_id(parsed_data, endpoint_id)
    if ep is None:
        problems.append({
            "check": "endpoint_exists",
            "endpoint": endpoint_id,
            "severity": "error",
            "message": f"Endpoint {endpoint_id} does not exist",
        })
    return len(problems) == 0, problems


def check_root_node_device_type(parsed_data):
    """Validate root node device type on EP0.

    Corresponds to TC_SM_1_1 Steps 3-4:
    - EP0 must have root node device type (0x0016)
    - Root node device type must not appear on non-zero endpoints

    Args:
        parsed_data: Parsed device data

    Returns:
        Tuple of (success, list of problem dicts)
    """
    problems = []

    ep0 = _get_endpoint_by_id(parsed_data, 0)
    if ep0 is None:
        problems.append({
            "check": "root_node_device_type",
            "endpoint": 0,
            "severity": "error",
            "message": "Endpoint 0 does not exist, cannot check root node device type",
        })
        return False, problems

    # Check EP0 has Descriptor cluster
    if DESCRIPTOR_CLUSTER_ID not in ep0.get("clusters", {}):
        problems.append({
            "check": "root_node_device_type",
            "endpoint": 0,
            "severity": "error",
            "message": "No Descriptor cluster on Endpoint 0",
        })
        return False, problems

    # Check EP0 DeviceTypeList includes root node
    ep0_device_types = _get_device_type_ids_for_endpoint(ep0)
    if ROOT_NODE_DEVICE_TYPE_ID not in ep0_device_types:
        problems.append({
            "check": "root_node_device_type",
            "endpoint": 0,
            "severity": "error",
            "message": f"Root node device type ({convert_to_hex(ROOT_NODE_DEVICE_TYPE_ID)}) not listed on Endpoint 0",
        })

    # Check EP0 only has allowed device types (node-scoped types)
    for dt_id in ep0_device_types:
        if dt_id not in ROOT_NODE_ALLOWED_DEVICE_TYPES:
            problems.append({
                "check": "root_node_device_type",
                "endpoint": 0,
                "severity": "error",
                "message": (
                    f"Endpoint 0 has device type {convert_to_hex(dt_id)} which is not allowed. "
                    f"Only Root Node, Power Source, OTA Requestor, and OTA Provider are allowed on EP0."
                ),
            })

    # Check root node device type does not appear on non-zero endpoints
    for ep in parsed_data.get("endpoints", []):
        ep_id = ep.get("id")
        if ep_id == 0:
            continue
        ep_device_types = _get_device_type_ids_for_endpoint(ep)
        if ROOT_NODE_DEVICE_TYPE_ID in ep_device_types:
            problems.append({
                "check": "root_node_device_type",
                "endpoint": ep_id,
                "severity": "error",
                "message": f"Root node device type listed on non-zero endpoint {ep_id}",
            })

    return len(problems) == 0, problems


def check_descriptor_on_all_endpoints(parsed_data):
    """Verify that every endpoint has a Descriptor cluster.

    Corresponds to TC_DT_1_1 Step 2.

    Args:
        parsed_data: Parsed device data

    Returns:
        Tuple of (success, list of problem dicts)
    """
    problems = []

    for ep in parsed_data.get("endpoints", []):
        ep_id = ep.get("id")
        clusters = ep.get("clusters", {})
        if DESCRIPTOR_CLUSTER_ID not in clusters:
            problems.append({
                "check": "descriptor_present",
                "endpoint": ep_id,
                "severity": "error",
                "message": f"Endpoint {ep_id} does not have a Descriptor cluster",
            })

    return len(problems) == 0, problems


def check_required_root_node_clusters(parsed_data):
    """Verify required clusters on root node endpoint (EP0).

    Corresponds to TC_SM_1_1 Step 5.

    Args:
        parsed_data: Parsed device data

    Returns:
        Tuple of (success, list of problem dicts)
    """
    problems = []

    ep0 = _get_endpoint_by_id(parsed_data, 0)
    if ep0 is None:
        problems.append({
            "check": "required_root_clusters",
            "endpoint": 0,
            "severity": "error",
            "message": "Endpoint 0 does not exist, cannot check required root node clusters",
        })
        return False, problems

    ep0_clusters = ep0.get("clusters", {})
    server_cluster_ids = _get_server_cluster_ids(ep0)

    for required_id in REQUIRED_ROOT_NODE_CLUSTER_IDS:
        cluster_name = REQUIRED_ROOT_NODE_CLUSTER_NAMES.get(required_id, "Unknown")
        # Check both direct cluster presence and ServerList
        found = required_id in ep0_clusters or required_id in server_cluster_ids
        if not found:
            problems.append({
                "check": "required_root_clusters",
                "endpoint": 0,
                "cluster_id": required_id,
                "cluster_name": cluster_name,
                "severity": "error",
                "message": f"Required root node cluster {cluster_name} ({required_id}) not found on Endpoint 0",
            })

    return len(problems) == 0, problems


def check_global_attributes(parsed_data):
    """Validate mandatory global attributes presence and validity on all clusters.

    Corresponds to TC_IDM_10_1 Steps 2-3:
    - ClusterRevision, FeatureMap, AttributeList, AcceptedCommandList,
      GeneratedCommandList must be present on every cluster
    - No duplicates in list-type global attributes
    - ClusterRevision >= 1
    - FeatureMap is a valid integer

    Args:
        parsed_data: Parsed device data

    Returns:
        Tuple of (success, list of problem dicts)
    """
    problems = []

    for ep in parsed_data.get("endpoints", []):
        ep_id = ep.get("id")
        for cluster_id, cluster_data in ep.get("clusters", {}).items():
            # Check ClusterRevision present
            revision_data = cluster_data.get("revisions", {}).get("ClusterRevision", {})
            has_revision = (
                isinstance(revision_data, dict)
                and "ClusterRevision" in revision_data
            )
            if not has_revision:
                problems.append({
                    "check": "global_attributes",
                    "endpoint": ep_id,
                    "cluster_id": cluster_id,
                    "severity": "error",
                    "message": f"ClusterRevision not found on cluster {cluster_id} (endpoint {ep_id})",
                })
            else:
                raw_rev = revision_data["ClusterRevision"]
                # convert_to_int returns None for 0 due to falsy check,
                # so handle integer 0 explicitly
                rev_val = raw_rev if isinstance(raw_rev, int) else convert_to_int(raw_rev)
                if rev_val is not None and rev_val < 1:
                    problems.append({
                        "check": "global_attributes",
                        "endpoint": ep_id,
                        "cluster_id": cluster_id,
                        "severity": "error",
                        "message": f"ClusterRevision value {rev_val} is less than 1 on cluster {cluster_id} (endpoint {ep_id})",
                    })

            # Check FeatureMap present
            feature_data = cluster_data.get("features", {}).get("FeatureMap", {})
            has_feature_map = (
                isinstance(feature_data, dict) and "FeatureMap" in feature_data
            )
            if not has_feature_map:
                problems.append({
                    "check": "global_attributes",
                    "endpoint": ep_id,
                    "cluster_id": cluster_id,
                    "severity": "error",
                    "message": f"FeatureMap not found on cluster {cluster_id} (endpoint {ep_id})",
                })
            else:
                raw_fm = feature_data["FeatureMap"]
                fm_val = raw_fm if isinstance(raw_fm, int) else convert_to_int(raw_fm)
                if fm_val is not None and (fm_val < 0 or fm_val > 0xFFFFFFFF):
                    problems.append({
                        "check": "global_attributes",
                        "endpoint": ep_id,
                        "cluster_id": cluster_id,
                        "severity": "error",
                        "message": f"FeatureMap value {fm_val} out of range [0, 0xFFFFFFFF] on cluster {cluster_id} (endpoint {ep_id})",
                    })

            # Check AttributeList present and no duplicates
            attr_list = get_nested_list(
                cluster_data, "attributes", "AttributeList", "AttributeList"
            )
            if not attr_list:
                problems.append({
                    "check": "global_attributes",
                    "endpoint": ep_id,
                    "cluster_id": cluster_id,
                    "severity": "error",
                    "message": f"AttributeList not found or empty on cluster {cluster_id} (endpoint {ep_id})",
                })
            else:
                duplicates = find_duplicates_in_element_list(attr_list)
                for dup in duplicates:
                    problems.append({
                        "check": "global_attributes",
                        "endpoint": ep_id,
                        "cluster_id": cluster_id,
                        "severity": "error",
                        "message": (
                            f"Duplicate attribute {dup['name']} ({dup['id']}) found "
                            f"{dup['count']} times in AttributeList on cluster {cluster_id} (endpoint {ep_id})"
                        ),
                    })

            # Check AcceptedCommandList present and no duplicates
            accepted_list = get_nested_list(
                cluster_data, "commands", "AcceptedCommandList", "AcceptedCommandList"
            )
            # AcceptedCommandList can be empty (no accepted commands), but should exist
            # In parsed data, if the attribute exists it will be in the commands section
            has_accepted = "AcceptedCommandList" in cluster_data.get("commands", {})
            if not has_accepted:
                problems.append({
                    "check": "global_attributes",
                    "endpoint": ep_id,
                    "cluster_id": cluster_id,
                    "severity": "warning",
                    "message": f"AcceptedCommandList not found on cluster {cluster_id} (endpoint {ep_id})",
                })
            else:
                duplicates = find_duplicates_in_element_list(accepted_list)
                for dup in duplicates:
                    problems.append({
                        "check": "global_attributes",
                        "endpoint": ep_id,
                        "cluster_id": cluster_id,
                        "severity": "error",
                        "message": (
                            f"Duplicate command {dup['name']} ({dup['id']}) found "
                            f"{dup['count']} times in AcceptedCommandList on cluster {cluster_id} (endpoint {ep_id})"
                        ),
                    })

            # Check GeneratedCommandList present and no duplicates
            generated_list = get_nested_list(
                cluster_data, "commands", "GeneratedCommandList", "GeneratedCommandList"
            )
            has_generated = "GeneratedCommandList" in cluster_data.get("commands", {})
            if not has_generated:
                problems.append({
                    "check": "global_attributes",
                    "endpoint": ep_id,
                    "cluster_id": cluster_id,
                    "severity": "warning",
                    "message": f"GeneratedCommandList not found on cluster {cluster_id} (endpoint {ep_id})",
                })
            else:
                duplicates = find_duplicates_in_element_list(generated_list)
                for dup in duplicates:
                    problems.append({
                        "check": "global_attributes",
                        "endpoint": ep_id,
                        "cluster_id": cluster_id,
                        "severity": "error",
                        "message": (
                            f"Duplicate command {dup['name']} ({dup['id']}) found "
                            f"{dup['count']} times in GeneratedCommandList on cluster {cluster_id} (endpoint {ep_id})"
                        ),
                    })

    return len([p for p in problems if p["severity"] == "error"]) == 0, problems


def check_parts_list(parsed_data):
    """Validate PartsList consistency across endpoints.

    Corresponds to TC_SM_1_2 Steps 2-3:
    - EP0 PartsList matches all non-zero endpoints
    - No endpoint includes itself in its PartsList
    - No duplicate endpoint IDs in PartsList

    Args:
        parsed_data: Parsed device data

    Returns:
        Tuple of (success, list of problem dicts)
    """
    problems = []

    ep0 = _get_endpoint_by_id(parsed_data, 0)
    if ep0 is None:
        problems.append({
            "check": "parts_list",
            "endpoint": 0,
            "severity": "error",
            "message": "Endpoint 0 does not exist, cannot validate PartsList",
        })
        return False, problems

    # Get all endpoint IDs
    all_endpoint_ids = set()
    for ep in parsed_data.get("endpoints", []):
        all_endpoint_ids.add(ep.get("id"))

    # Check for duplicate endpoint IDs
    endpoint_ids_list = [ep.get("id") for ep in parsed_data.get("endpoints", [])]
    if len(endpoint_ids_list) != len(set(endpoint_ids_list)):
        problems.append({
            "check": "parts_list",
            "endpoint": 0,
            "severity": "error",
            "message": "Duplicate endpoint IDs found in device data",
        })

    # Get EP0 PartsList
    parts_list_0 = _get_parts_list(ep0)

    # Check for duplicates in EP0 PartsList
    if len(parts_list_0) != len(set(parts_list_0)):
        problems.append({
            "check": "parts_list",
            "endpoint": 0,
            "severity": "error",
            "message": "Duplicate endpoint IDs found in EP0 PartsList",
        })

    # EP0 PartsList should match all non-zero endpoints
    expected_parts = all_endpoint_ids - {0}
    actual_parts = set()
    for p in parts_list_0:
        p_int = convert_to_int(p) if not isinstance(p, int) else p
        if p_int is not None:
            actual_parts.add(p_int)

    if actual_parts != expected_parts:
        missing = expected_parts - actual_parts
        extra = actual_parts - expected_parts
        msg_parts = []
        if missing:
            msg_parts.append(f"missing endpoints: {sorted(missing)}")
        if extra:
            msg_parts.append(f"extra endpoints: {sorted(extra)}")
        problems.append({
            "check": "parts_list",
            "endpoint": 0,
            "severity": "error",
            "message": f"EP0 PartsList does not match non-zero endpoints. {', '.join(msg_parts)}",
        })

    # Check no endpoint includes itself in PartsList
    for ep in parsed_data.get("endpoints", []):
        ep_id = ep.get("id")
        parts = _get_parts_list(ep)
        for p in parts:
            p_int = convert_to_int(p) if not isinstance(p, int) else p
            if p_int == ep_id:
                problems.append({
                    "check": "parts_list",
                    "endpoint": ep_id,
                    "severity": "error",
                    "message": f"Endpoint {ep_id} PartsList includes itself (self-reference)",
                })

    return len(problems) == 0, problems


def check_device_type_list_validity(parsed_data):
    """Validate DeviceTypeList structure on all endpoints.

    Corresponds to TC_DESC_2_1 Step 1a/1b:
    - DeviceTypeList must be non-empty on every endpoint
    - Device type revisions must be >= 1

    Args:
        parsed_data: Parsed device data

    Returns:
        Tuple of (success, list of problem dicts)
    """
    problems = []

    for ep in parsed_data.get("endpoints", []):
        ep_id = ep.get("id")
        device_types = _get_device_type_ids_for_endpoint(ep)

        if not device_types:
            problems.append({
                "check": "device_type_list",
                "endpoint": ep_id,
                "severity": "error",
                "message": f"DeviceTypeList is empty on endpoint {ep_id}",
            })
            continue

        # Check revisions >= 1
        dt_revisions = _get_device_type_revisions_for_endpoint(ep)
        for dt_id, revision in dt_revisions:
            if revision is not None:
                rev_int = convert_to_int(revision) if not isinstance(revision, int) else revision
                if rev_int is not None and rev_int < 1:
                    problems.append({
                        "check": "device_type_list",
                        "endpoint": ep_id,
                        "severity": "error",
                        "message": f"Device type {convert_to_hex(dt_id)} revision {rev_int} is less than 1 on endpoint {ep_id}",
                    })

    return len(problems) == 0, problems


def check_root_node_restricted_clusters(parsed_data):
    """Validate that root-node-restricted clusters only appear on EP0.

    Corresponds to TC_IDM_14_1 Step 1:
    - ACL and Time Synchronization clusters must only be on EP0

    Args:
        parsed_data: Parsed device data

    Returns:
        Tuple of (success, list of problem dicts)
    """
    problems = []

    for ep in parsed_data.get("endpoints", []):
        ep_id = ep.get("id")
        if ep_id == 0:
            continue

        ep_clusters = ep.get("clusters", {})
        server_cluster_ids = _get_server_cluster_ids(ep)

        for restricted_id in ROOT_NODE_RESTRICTED_CLUSTER_IDS:
            cluster_name = ROOT_NODE_RESTRICTED_CLUSTER_NAMES.get(restricted_id, "Unknown")
            if restricted_id in ep_clusters or restricted_id in server_cluster_ids:
                problems.append({
                    "check": "restricted_clusters",
                    "endpoint": ep_id,
                    "cluster_id": restricted_id,
                    "cluster_name": cluster_name,
                    "severity": "error",
                    "message": (
                        f"Root-node-restricted cluster {cluster_name} ({restricted_id}) "
                        f"found on non-root endpoint {ep_id}"
                    ),
                })

    return len(problems) == 0, problems


def check_no_application_device_types_on_root(parsed_data):
    """Validate that EP0 has no application device types.

    Corresponds to TC_DESC_2_3 Step 1.

    Args:
        parsed_data: Parsed device data

    Returns:
        Tuple of (success, list of problem dicts)
    """
    problems = []

    ep0 = _get_endpoint_by_id(parsed_data, 0)
    if ep0 is None:
        return True, problems  # Checked elsewhere

    ep0_device_types = _get_device_type_ids_for_endpoint(ep0)
    for dt_id in ep0_device_types:
        if dt_id not in NON_APPLICATION_DEVICE_TYPES:
            problems.append({
                "check": "no_app_device_types_on_root",
                "endpoint": 0,
                "severity": "error",
                "message": (
                    f"Application device type {convert_to_hex(dt_id)} found on "
                    f"root endpoint (EP0). Only node-scoped device types are allowed."
                ),
            })

    return len(problems) == 0, problems


def check_parts_list_endpoint_range(parsed_data):
    """Validate PartsList endpoint IDs are in valid range (1-65534).

    Corresponds to TC_DESC_2_1 Step 4.

    Args:
        parsed_data: Parsed device data

    Returns:
        Tuple of (success, list of problem dicts)
    """
    problems = []
    EP_RANGE_MIN = 1
    EP_RANGE_MAX = 65534

    for ep in parsed_data.get("endpoints", []):
        ep_id = ep.get("id")
        if ep_id == 0:
            continue

        parts = _get_parts_list(ep)
        for p in parts:
            p_int = convert_to_int(p) if not isinstance(p, int) else p
            if p_int is not None and (p_int < EP_RANGE_MIN or p_int > EP_RANGE_MAX):
                problems.append({
                    "check": "parts_list_range",
                    "endpoint": ep_id,
                    "severity": "error",
                    "message": (
                        f"Endpoint {ep_id} PartsList contains endpoint ID {p_int} "
                        f"outside valid range [{EP_RANGE_MIN}, {EP_RANGE_MAX}]"
                    ),
                })

    return len(problems) == 0, problems


def validate_device_composition(parsed_data):
    """Run all device composition validation checks.

    This is the main entry point for composition validation, running checks
    inspired by TC_DeviceBasicComposition and TC_DeviceConformance:
    - Root node device type validation (TC_SM_1_1)
    - Descriptor cluster presence (TC_DT_1_1)
    - Required root node clusters (TC_SM_1_1)
    - Global attributes validation (TC_IDM_10_1)
    - PartsList validation (TC_SM_1_2)
    - DeviceTypeList validation (TC_DESC_2_1)
    - Root-node-restricted clusters (TC_IDM_14_1)
    - Application device types on root (TC_DESC_2_3)

    Args:
        parsed_data: Parsed device data from wildcard logs

    Returns:
        Dict with composition validation results
    """
    composition_results = {
        "is_compliant": True,
        "checks": {},
        "summary": {
            "total_checks": 0,
            "passed_checks": 0,
            "failed_checks": 0,
            "warning_checks": 0,
            "total_problems": 0,
            "errors": 0,
            "warnings": 0,
        },
    }

    checks = [
        ("endpoint_0_exists", lambda: check_endpoint_exists(parsed_data, 0)),
        ("root_node_device_type", lambda: check_root_node_device_type(parsed_data)),
        ("descriptor_on_all_endpoints", lambda: check_descriptor_on_all_endpoints(parsed_data)),
        ("required_root_node_clusters", lambda: check_required_root_node_clusters(parsed_data)),
        ("global_attributes", lambda: check_global_attributes(parsed_data)),
        ("parts_list", lambda: check_parts_list(parsed_data)),
        ("device_type_list_validity", lambda: check_device_type_list_validity(parsed_data)),
        ("root_node_restricted_clusters", lambda: check_root_node_restricted_clusters(parsed_data)),
        ("no_app_device_types_on_root", lambda: check_no_application_device_types_on_root(parsed_data)),
        ("parts_list_endpoint_range", lambda: check_parts_list_endpoint_range(parsed_data)),
    ]

    total_checks = 0
    passed_checks = 0
    failed_checks = 0
    warning_checks = 0
    total_problems = 0
    total_errors = 0
    total_warnings = 0

    for check_name, check_fn in checks:
        try:
            success, check_problems = check_fn()
            errors = [p for p in check_problems if p.get("severity") == "error"]
            warnings = [p for p in check_problems if p.get("severity") == "warning"]

            composition_results["checks"][check_name] = {
                "passed": success,
                "problems": check_problems,
                "errors": len(errors),
                "warnings": len(warnings),
            }

            total_checks += 1
            if success:
                passed_checks += 1
            else:
                failed_checks += 1
                composition_results["is_compliant"] = False

            if warnings and not errors:
                warning_checks += 1

            total_problems += len(check_problems)
            total_errors += len(errors)
            total_warnings += len(warnings)

        except Exception as e:
            logger.error(f"Error running composition check '{check_name}': {e}")
            composition_results["checks"][check_name] = {
                "passed": False,
                "problems": [{
                    "check": check_name,
                    "severity": "error",
                    "message": f"Check failed with error: {str(e)}",
                }],
                "errors": 1,
                "warnings": 0,
            }
            total_checks += 1
            failed_checks += 1
            total_problems += 1
            total_errors += 1
            composition_results["is_compliant"] = False

    composition_results["summary"] = {
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "warning_checks": warning_checks,
        "total_problems": total_problems,
        "errors": total_errors,
        "warnings": total_warnings,
    }

    return composition_results
