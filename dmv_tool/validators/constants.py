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

DESCRIPTOR_CLUSTER_ID = "0x001D"  # Descriptor cluster ID
DESCRIPTOR_CLIENT_LIST_ATTRIBUTE_ID = "0x0002"  # Descriptor ClientList attribute ID
DESCRIPTOR_SERVER_LIST_ATTRIBUTE_ID = "0x0001"  # Descriptor ServerList attribute ID
DESCRIPTOR_PARTS_LIST_ATTRIBUTE_ID = "0x0003"  # Descriptor PartsList attribute ID
BASIC_INFORMATION_CLUSTER_ID = "0x0028"  # Basic Information cluster ID
SPECIFICATION_VERSION_ATTRIBUTE_ID = "0x0015"  # Specification Version attribute ID
DEVICE_TYPE_LIST_ATTRIBUTE_ID = "0x0000"  # Device Type List attribute ID

# Device type IDs
ROOT_NODE_DEVICE_TYPE_ID = 0x0016
POWER_SOURCE_DEVICE_TYPE_ID = 0x0011
OTA_REQUESTOR_DEVICE_TYPE_ID = 0x0012
OTA_PROVIDER_DEVICE_TYPE_ID = 0x0014
BRIDGED_NODE_DEVICE_TYPE_ID = 0x0013
AGGREGATOR_DEVICE_TYPE_ID = 0x000E
ELECTRICAL_SENSOR_DEVICE_TYPE_ID = 0x0510
DEVICE_ENERGY_MANAGEMENT_DEVICE_TYPE_ID = 0x050D
SECONDARY_NETWORK_INTERFACE_DEVICE_TYPE_ID = 0x0019
JOINT_FABRIC_ADMINISTRATOR_DEVICE_TYPE_ID = 0x0130

# Non-application device types (node-scoped or utility types)
NON_APPLICATION_DEVICE_TYPES = {
    ROOT_NODE_DEVICE_TYPE_ID,
    POWER_SOURCE_DEVICE_TYPE_ID,
    OTA_REQUESTOR_DEVICE_TYPE_ID,
    OTA_PROVIDER_DEVICE_TYPE_ID,
    BRIDGED_NODE_DEVICE_TYPE_ID,
    ELECTRICAL_SENSOR_DEVICE_TYPE_ID,
    DEVICE_ENERGY_MANAGEMENT_DEVICE_TYPE_ID,
    SECONDARY_NETWORK_INTERFACE_DEVICE_TYPE_ID,
    JOINT_FABRIC_ADMINISTRATOR_DEVICE_TYPE_ID,
}

# Root node allowed device types on EP0
ROOT_NODE_ALLOWED_DEVICE_TYPES = {
    ROOT_NODE_DEVICE_TYPE_ID,
    POWER_SOURCE_DEVICE_TYPE_ID,
    OTA_REQUESTOR_DEVICE_TYPE_ID,
    OTA_PROVIDER_DEVICE_TYPE_ID,
}

# Required clusters on root node endpoint (EP0)
REQUIRED_ROOT_NODE_CLUSTER_IDS = {
    "0x0028",  # Basic Information
    "0x001F",  # Access Control
    "0x003F",  # Group Key Management
    "0x0030",  # General Commissioning
    "0x003C",  # Administrator Commissioning
    "0x003E",  # Operational Credentials
    "0x0033",  # General Diagnostics
}

REQUIRED_ROOT_NODE_CLUSTER_NAMES = {
    "0x0028": "Basic Information",
    "0x001F": "Access Control",
    "0x003F": "Group Key Management",
    "0x0030": "General Commissioning",
    "0x003C": "Administrator Commissioning",
    "0x003E": "Operational Credentials",
    "0x0033": "General Diagnostics",
}

# Root-node-restricted clusters (must only appear on EP0)
ROOT_NODE_RESTRICTED_CLUSTER_IDS = {
    "0x001F",  # Access Control
    "0x0038",  # Time Synchronization
}

ROOT_NODE_RESTRICTED_CLUSTER_NAMES = {
    "0x001F": "Access Control",
    "0x0038": "Time Synchronization",
}

# Global attribute IDs and their valid ranges
GLOBAL_ATTRIBUTE_CLUSTER_REVISION_ID = "ClusterRevision"  # 0xFFFD
GLOBAL_ATTRIBUTE_FEATURE_MAP_ID = "FeatureMap"  # 0xFFFC
GLOBAL_ATTRIBUTE_ATTRIBUTE_LIST_ID = "AttributeList"  # 0xFFFB
GLOBAL_ATTRIBUTE_ACCEPTED_COMMAND_LIST_ID = "AcceptedCommandList"  # 0xFFF9
GLOBAL_ATTRIBUTE_GENERATED_COMMAND_LIST_ID = "GeneratedCommandList"  # 0xFFF8
