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

import logging
import os
import pytest

from dmv_tool.validators.composition_checker import (
    check_endpoint_exists,
    check_root_node_device_type,
    check_descriptor_on_all_endpoints,
    check_required_root_node_clusters,
    check_global_attributes,
    check_parts_list,
    check_device_type_list_validity,
    check_root_node_restricted_clusters,
    check_no_application_device_types_on_root,
    check_parts_list_endpoint_range,
    validate_device_composition,
)
from dmv_tool.parsers.wildcard_logs import parse_datamodel_logs

logging.basicConfig(level=logging.INFO, format="%(message)s")


def _make_cluster(
    attribute_list=None,
    accepted_commands=None,
    generated_commands=None,
    feature_map=0,
    cluster_revision=1,
    extra_attributes=None,
):
    """Helper to create a minimal cluster data structure for testing."""
    cluster = {
        "attributes": {},
        "events": {},
        "commands": {},
        "features": {
            "FeatureMap": {"FeatureMap": feature_map}
        },
        "revisions": {
            "ClusterRevision": {"ClusterRevision": cluster_revision}
        },
    }

    if attribute_list is not None:
        cluster["attributes"]["AttributeList"] = {
            "AttributeList": attribute_list
        }
    else:
        cluster["attributes"]["AttributeList"] = {
            "AttributeList": [
                {"id": "0x0000", "name": "test_attr"},
            ]
        }

    if accepted_commands is not None:
        cluster["commands"]["AcceptedCommandList"] = {
            "AcceptedCommandList": accepted_commands
        }
    else:
        cluster["commands"]["AcceptedCommandList"] = {
            "AcceptedCommandList": []
        }

    if generated_commands is not None:
        cluster["commands"]["GeneratedCommandList"] = {
            "GeneratedCommandList": generated_commands
        }
    else:
        cluster["commands"]["GeneratedCommandList"] = {
            "GeneratedCommandList": []
        }

    if extra_attributes:
        cluster["attributes"].update(extra_attributes)

    return cluster


def _make_descriptor_cluster(device_types, server_list=None, client_list=None, parts_list=None):
    """Helper to create a Descriptor cluster data structure."""
    attrs = {
        "0x0000": {
            "DeviceTypeList": device_types
        },
    }
    if server_list is not None:
        attrs["0x0001"] = {"ServerList": server_list}
    if client_list is not None:
        attrs["0x0002"] = {"ClientList": client_list}
    if parts_list is not None:
        attrs["0x0003"] = {"PartsList": parts_list}
    else:
        attrs["0x0003"] = {"PartsList": []}

    attrs["AttributeList"] = {
        "AttributeList": [
            {"id": "0x0000", "name": "device_type_list"},
            {"id": "0x0001", "name": "server_list"},
            {"id": "0x0002", "name": "client_list"},
            {"id": "0x0003", "name": "parts_list"},
        ]
    }

    return {
        "attributes": attrs,
        "events": {},
        "commands": {
            "AcceptedCommandList": {"AcceptedCommandList": []},
            "GeneratedCommandList": {"GeneratedCommandList": []},
        },
        "features": {"FeatureMap": {"FeatureMap": 0}},
        "revisions": {"ClusterRevision": {"ClusterRevision": 2}},
    }


def _build_compliant_parsed_data():
    """Build a minimal compliant parsed data structure for testing."""
    return {
        "endpoints": [
            {
                "id": 0,
                "clusters": {
                    "0x001D": _make_descriptor_cluster(
                        device_types=[
                            {
                                "DeviceType": {"id": "0x0016", "name": "root_node"},
                                "Revision": 3,
                            },
                        ],
                        server_list=[
                            {"id": "0x001D", "name": "descriptor"},
                            {"id": "0x0028", "name": "basic_information"},
                            {"id": "0x001F", "name": "access_control"},
                            {"id": "0x003F", "name": "group_key_management"},
                            {"id": "0x0030", "name": "general_commissioning"},
                            {"id": "0x003C", "name": "administrator_commissioning"},
                            {"id": "0x003E", "name": "operational_credentials"},
                            {"id": "0x0033", "name": "general_diagnostics"},
                        ],
                        parts_list=[1],
                    ),
                    "0x0028": _make_cluster(cluster_revision=3),
                    "0x001F": _make_cluster(),
                    "0x003F": _make_cluster(),
                    "0x0030": _make_cluster(),
                    "0x003C": _make_cluster(),
                    "0x003E": _make_cluster(),
                    "0x0033": _make_cluster(),
                },
            },
            {
                "id": 1,
                "clusters": {
                    "0x001D": _make_descriptor_cluster(
                        device_types=[
                            {
                                "DeviceType": {"id": "0x0100", "name": "on_off_light"},
                                "Revision": 3,
                            },
                        ],
                        server_list=[
                            {"id": "0x001D", "name": "descriptor"},
                            {"id": "0x0006", "name": "on_off"},
                        ],
                        parts_list=[],
                    ),
                    "0x0006": _make_cluster(),
                },
            },
        ]
    }


class TestCheckEndpointExists:
    """Test the check_endpoint_exists function."""

    def test_endpoint_0_exists(self):
        data = _build_compliant_parsed_data()
        success, problems = check_endpoint_exists(data, 0)
        assert success is True
        assert len(problems) == 0

    def test_endpoint_0_missing(self):
        data = {"endpoints": [{"id": 1, "clusters": {}}]}
        success, problems = check_endpoint_exists(data, 0)
        assert success is False
        assert len(problems) == 1
        assert "does not exist" in problems[0]["message"]

    def test_empty_endpoints(self):
        data = {"endpoints": []}
        success, problems = check_endpoint_exists(data, 0)
        assert success is False

    def test_non_zero_endpoint_exists(self):
        data = _build_compliant_parsed_data()
        success, problems = check_endpoint_exists(data, 1)
        assert success is True

    def test_non_zero_endpoint_missing(self):
        data = _build_compliant_parsed_data()
        success, problems = check_endpoint_exists(data, 99)
        assert success is False


class TestCheckRootNodeDeviceType:
    """Test the check_root_node_device_type function."""

    def test_compliant_root_node(self):
        data = _build_compliant_parsed_data()
        success, problems = check_root_node_device_type(data)
        assert success is True
        assert len(problems) == 0

    def test_missing_root_node_device_type(self):
        data = _build_compliant_parsed_data()
        # Remove root node device type from EP0
        data["endpoints"][0]["clusters"]["0x001D"]["attributes"]["0x0000"] = {
            "DeviceTypeList": [
                {"DeviceType": {"id": "0x0100", "name": "on_off_light"}, "Revision": 1}
            ]
        }
        success, problems = check_root_node_device_type(data)
        assert success is False
        # Should have 2 problems: root node not listed on EP0, and app device type on EP0
        error_messages = [p["message"] for p in problems]
        assert any("Root node device type" in m for m in error_messages)

    def test_root_node_on_non_zero_endpoint(self):
        data = _build_compliant_parsed_data()
        # Add root node device type to EP1
        data["endpoints"][1]["clusters"]["0x001D"]["attributes"]["0x0000"] = {
            "DeviceTypeList": [
                {"DeviceType": {"id": "0x0016", "name": "root_node"}, "Revision": 3},
                {"DeviceType": {"id": "0x0100", "name": "on_off_light"}, "Revision": 1},
            ]
        }
        success, problems = check_root_node_device_type(data)
        assert success is False
        error_messages = [p["message"] for p in problems]
        assert any("non-zero endpoint" in m for m in error_messages)

    def test_no_descriptor_on_ep0(self):
        data = {"endpoints": [{"id": 0, "clusters": {}}]}
        success, problems = check_root_node_device_type(data)
        assert success is False
        assert any("Descriptor" in p["message"] for p in problems)

    def test_ep0_missing(self):
        data = {"endpoints": [{"id": 1, "clusters": {}}]}
        success, problems = check_root_node_device_type(data)
        assert success is False

    def test_disallowed_device_type_on_ep0(self):
        """EP0 should only have node-scoped device types."""
        data = _build_compliant_parsed_data()
        # Add application device type to EP0
        data["endpoints"][0]["clusters"]["0x001D"]["attributes"]["0x0000"] = {
            "DeviceTypeList": [
                {"DeviceType": {"id": "0x0016", "name": "root_node"}, "Revision": 3},
                {"DeviceType": {"id": "0x0100", "name": "on_off_light"}, "Revision": 1},
            ]
        }
        success, problems = check_root_node_device_type(data)
        assert success is False
        assert any("not allowed" in p["message"] for p in problems)


class TestCheckDescriptorOnAllEndpoints:
    """Test the check_descriptor_on_all_endpoints function."""

    def test_all_endpoints_have_descriptor(self):
        data = _build_compliant_parsed_data()
        success, problems = check_descriptor_on_all_endpoints(data)
        assert success is True
        assert len(problems) == 0

    def test_missing_descriptor_on_endpoint(self):
        data = _build_compliant_parsed_data()
        # Remove descriptor from EP1
        del data["endpoints"][1]["clusters"]["0x001D"]
        success, problems = check_descriptor_on_all_endpoints(data)
        assert success is False
        assert any("Endpoint 1" in p["message"] for p in problems)

    def test_empty_clusters(self):
        data = {"endpoints": [{"id": 0, "clusters": {}}]}
        success, problems = check_descriptor_on_all_endpoints(data)
        assert success is False


class TestCheckRequiredRootNodeClusters:
    """Test the check_required_root_node_clusters function."""

    def test_all_required_clusters_present(self):
        data = _build_compliant_parsed_data()
        success, problems = check_required_root_node_clusters(data)
        assert success is True
        assert len(problems) == 0

    def test_missing_basic_information(self):
        data = _build_compliant_parsed_data()
        # Remove BasicInformation cluster from EP0
        del data["endpoints"][0]["clusters"]["0x0028"]
        # Also remove from server list
        server_list = data["endpoints"][0]["clusters"]["0x001D"]["attributes"]["0x0001"]["ServerList"]
        data["endpoints"][0]["clusters"]["0x001D"]["attributes"]["0x0001"]["ServerList"] = [
            s for s in server_list if s.get("id") != "0x0028"
        ]
        success, problems = check_required_root_node_clusters(data)
        assert success is False
        assert any("Basic Information" in p["message"] for p in problems)

    def test_missing_access_control(self):
        data = _build_compliant_parsed_data()
        del data["endpoints"][0]["clusters"]["0x001F"]
        server_list = data["endpoints"][0]["clusters"]["0x001D"]["attributes"]["0x0001"]["ServerList"]
        data["endpoints"][0]["clusters"]["0x001D"]["attributes"]["0x0001"]["ServerList"] = [
            s for s in server_list if s.get("id") != "0x001F"
        ]
        success, problems = check_required_root_node_clusters(data)
        assert success is False
        assert any("Access Control" in p["message"] for p in problems)

    def test_ep0_missing(self):
        data = {"endpoints": [{"id": 1, "clusters": {}}]}
        success, problems = check_required_root_node_clusters(data)
        assert success is False

    def test_cluster_in_server_list_but_not_direct(self):
        """Cluster exists in ServerList but not directly as a key - should still pass."""
        data = _build_compliant_parsed_data()
        # Remove direct cluster key but keep in ServerList
        del data["endpoints"][0]["clusters"]["0x0033"]
        success, problems = check_required_root_node_clusters(data)
        assert success is True  # Still in ServerList


class TestCheckGlobalAttributes:
    """Test the check_global_attributes function."""

    def test_all_global_attributes_present(self):
        data = _build_compliant_parsed_data()
        success, problems = check_global_attributes(data)
        assert success is True

    def test_missing_cluster_revision(self):
        data = _build_compliant_parsed_data()
        # Remove ClusterRevision from a cluster on EP1
        data["endpoints"][1]["clusters"]["0x0006"]["revisions"] = {}
        success, problems = check_global_attributes(data)
        assert success is False
        assert any("ClusterRevision not found" in p["message"] for p in problems)

    def test_missing_feature_map(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][1]["clusters"]["0x0006"]["features"] = {}
        success, problems = check_global_attributes(data)
        assert success is False
        assert any("FeatureMap not found" in p["message"] for p in problems)

    def test_missing_attribute_list(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][1]["clusters"]["0x0006"]["attributes"] = {}
        success, problems = check_global_attributes(data)
        assert success is False
        assert any("AttributeList" in p["message"] for p in problems)

    def test_duplicate_in_attribute_list(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][1]["clusters"]["0x0006"]["attributes"]["AttributeList"] = {
            "AttributeList": [
                {"id": "0x0000", "name": "on_off"},
                {"id": "0x0000", "name": "on_off"},  # duplicate
            ]
        }
        success, problems = check_global_attributes(data)
        assert success is False
        assert any("Duplicate attribute" in p["message"] for p in problems)

    def test_duplicate_in_accepted_command_list(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][1]["clusters"]["0x0006"]["commands"]["AcceptedCommandList"] = {
            "AcceptedCommandList": [
                {"id": "0x0000", "name": "off"},
                {"id": "0x0000", "name": "off"},  # duplicate
            ]
        }
        success, problems = check_global_attributes(data)
        assert success is False
        assert any("Duplicate command" in p["message"] for p in problems)

    def test_cluster_revision_less_than_1(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][1]["clusters"]["0x0006"]["revisions"] = {
            "ClusterRevision": {"ClusterRevision": 0}
        }
        success, problems = check_global_attributes(data)
        assert success is False
        assert any("less than 1" in p["message"] for p in problems)


class TestCheckPartsList:
    """Test the check_parts_list function."""

    def test_valid_parts_list(self):
        data = _build_compliant_parsed_data()
        success, problems = check_parts_list(data)
        assert success is True
        assert len(problems) == 0

    def test_missing_endpoint_in_parts_list(self):
        data = _build_compliant_parsed_data()
        # EP0 PartsList should list [1] but we set it empty
        data["endpoints"][0]["clusters"]["0x001D"]["attributes"]["0x0003"] = {
            "PartsList": []
        }
        success, problems = check_parts_list(data)
        assert success is False
        assert any("does not match" in p["message"] for p in problems)

    def test_extra_endpoint_in_parts_list(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][0]["clusters"]["0x001D"]["attributes"]["0x0003"] = {
            "PartsList": [1, 99]
        }
        success, problems = check_parts_list(data)
        assert success is False
        assert any("extra endpoints" in p["message"] for p in problems)

    def test_self_reference_in_parts_list(self):
        data = _build_compliant_parsed_data()
        # EP1 includes itself in its PartsList
        data["endpoints"][1]["clusters"]["0x001D"]["attributes"]["0x0003"] = {
            "PartsList": [1]
        }
        success, problems = check_parts_list(data)
        assert success is False
        assert any("self-reference" in p["message"] for p in problems)

    def test_duplicate_in_parts_list(self):
        data = _build_compliant_parsed_data()
        # Add a second endpoint
        data["endpoints"].append({
            "id": 2,
            "clusters": {
                "0x001D": _make_descriptor_cluster(
                    device_types=[
                        {"DeviceType": {"id": "0x0100", "name": "on_off_light"}, "Revision": 1}
                    ],
                    parts_list=[],
                ),
            },
        })
        # Set EP0 PartsList with duplicates
        data["endpoints"][0]["clusters"]["0x001D"]["attributes"]["0x0003"] = {
            "PartsList": [1, 2, 1]  # duplicate 1
        }
        success, problems = check_parts_list(data)
        assert success is False
        assert any("Duplicate" in p["message"] for p in problems)

    def test_ep0_missing(self):
        data = {"endpoints": [{"id": 1, "clusters": {}}]}
        success, problems = check_parts_list(data)
        assert success is False


class TestCheckDeviceTypeListValidity:
    """Test the check_device_type_list_validity function."""

    def test_valid_device_type_list(self):
        data = _build_compliant_parsed_data()
        success, problems = check_device_type_list_validity(data)
        assert success is True
        assert len(problems) == 0

    def test_empty_device_type_list(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][1]["clusters"]["0x001D"]["attributes"]["0x0000"] = {
            "DeviceTypeList": []
        }
        success, problems = check_device_type_list_validity(data)
        assert success is False
        assert any("empty" in p["message"] for p in problems)

    def test_revision_less_than_1(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][1]["clusters"]["0x001D"]["attributes"]["0x0000"] = {
            "DeviceTypeList": [
                {"DeviceType": {"id": "0x0100", "name": "on_off_light"}, "Revision": 0}
            ]
        }
        success, problems = check_device_type_list_validity(data)
        assert success is False
        assert any("less than 1" in p["message"] for p in problems)


class TestCheckRootNodeRestrictedClusters:
    """Test the check_root_node_restricted_clusters function."""

    def test_no_restricted_on_non_root(self):
        data = _build_compliant_parsed_data()
        success, problems = check_root_node_restricted_clusters(data)
        assert success is True
        assert len(problems) == 0

    def test_acl_on_non_root_endpoint(self):
        data = _build_compliant_parsed_data()
        # Add Access Control cluster on EP1
        data["endpoints"][1]["clusters"]["0x001F"] = _make_cluster()
        success, problems = check_root_node_restricted_clusters(data)
        assert success is False
        assert any("Access Control" in p["message"] for p in problems)

    def test_time_sync_on_non_root_endpoint(self):
        data = _build_compliant_parsed_data()
        # Add Time Synchronization cluster on EP1
        data["endpoints"][1]["clusters"]["0x0038"] = _make_cluster()
        success, problems = check_root_node_restricted_clusters(data)
        assert success is False
        assert any("Time Synchronization" in p["message"] for p in problems)

    def test_restricted_cluster_in_server_list(self):
        data = _build_compliant_parsed_data()
        # Add Access Control to EP1 ServerList
        data["endpoints"][1]["clusters"]["0x001D"]["attributes"]["0x0001"] = {
            "ServerList": [
                {"id": "0x001D", "name": "descriptor"},
                {"id": "0x001F", "name": "access_control"},
            ]
        }
        success, problems = check_root_node_restricted_clusters(data)
        assert success is False


class TestCheckNoApplicationDeviceTypesOnRoot:
    """Test the check_no_application_device_types_on_root function."""

    def test_only_node_device_types_on_ep0(self):
        data = _build_compliant_parsed_data()
        success, problems = check_no_application_device_types_on_root(data)
        assert success is True

    def test_application_device_type_on_ep0(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][0]["clusters"]["0x001D"]["attributes"]["0x0000"] = {
            "DeviceTypeList": [
                {"DeviceType": {"id": "0x0016", "name": "root_node"}, "Revision": 3},
                {"DeviceType": {"id": "0x0100", "name": "on_off_light"}, "Revision": 1},
            ]
        }
        success, problems = check_no_application_device_types_on_root(data)
        assert success is False
        assert any("Application device type" in p["message"] for p in problems)


class TestCheckPartsListEndpointRange:
    """Test the check_parts_list_endpoint_range function."""

    def test_valid_range(self):
        data = _build_compliant_parsed_data()
        success, problems = check_parts_list_endpoint_range(data)
        assert success is True

    def test_endpoint_0_in_parts_list(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][1]["clusters"]["0x001D"]["attributes"]["0x0003"] = {
            "PartsList": [0]
        }
        success, problems = check_parts_list_endpoint_range(data)
        assert success is False
        assert any("outside valid range" in p["message"] for p in problems)

    def test_endpoint_too_large(self):
        data = _build_compliant_parsed_data()
        data["endpoints"][1]["clusters"]["0x001D"]["attributes"]["0x0003"] = {
            "PartsList": [65535]
        }
        success, problems = check_parts_list_endpoint_range(data)
        assert success is False


class TestValidateDeviceComposition:
    """Test the validate_device_composition function."""

    def test_compliant_device(self):
        data = _build_compliant_parsed_data()
        result = validate_device_composition(data)
        assert result["is_compliant"] is True
        assert result["summary"]["failed_checks"] == 0
        assert result["summary"]["errors"] == 0

    def test_completely_empty_device(self):
        data = {"endpoints": []}
        result = validate_device_composition(data)
        assert result["is_compliant"] is False
        assert result["summary"]["failed_checks"] > 0

    def test_all_checks_run(self):
        data = _build_compliant_parsed_data()
        result = validate_device_composition(data)
        expected_checks = {
            "endpoint_0_exists",
            "root_node_device_type",
            "descriptor_on_all_endpoints",
            "required_root_node_clusters",
            "global_attributes",
            "parts_list",
            "device_type_list_validity",
            "root_node_restricted_clusters",
            "no_app_device_types_on_root",
            "parts_list_endpoint_range",
        }
        assert set(result["checks"].keys()) == expected_checks

    def test_multiple_failures(self):
        """Test with multiple issues: missing EP0, no descriptor, etc."""
        data = {
            "endpoints": [
                {
                    "id": 1,
                    "clusters": {},  # No descriptor, no clusters
                }
            ]
        }
        result = validate_device_composition(data)
        assert result["is_compliant"] is False
        assert result["summary"]["errors"] > 0

    def test_summary_counts(self):
        data = _build_compliant_parsed_data()
        result = validate_device_composition(data)
        summary = result["summary"]
        assert summary["total_checks"] == 10
        assert summary["passed_checks"] + summary["failed_checks"] == summary["total_checks"]


class TestCompositionWithRealWildcardData:
    """Integration test using real parsed wildcard data."""

    def setup_method(self):
        self.test_data_dir = os.path.join(os.path.dirname(__file__), "test_data")

    def test_compliant_logs_composition(self):
        """Test composition checks with real compliant wildcard logs."""
        log_file = os.path.join(self.test_data_dir, "wildcard_compliant_logs.txt")
        if not os.path.exists(log_file):
            pytest.skip("Test data file not found")

        with open(log_file, "r") as f:
            data = f.read()

        parsed_data = parse_datamodel_logs(data)
        result = validate_device_composition(parsed_data)

        # With compliant logs, the basic structure should be valid
        # Specifically check:
        assert result["checks"]["endpoint_0_exists"]["passed"] is True
        assert result["checks"]["descriptor_on_all_endpoints"]["passed"] is True
        assert result["checks"]["root_node_device_type"]["passed"] is True
        assert result["checks"]["device_type_list_validity"]["passed"] is True

    def test_missing_cluster_logs_composition(self):
        """Test composition checks with logs that have missing level control cluster."""
        log_file = os.path.join(
            self.test_data_dir, "wildcard_missing_level_control_cluster.txt"
        )
        if not os.path.exists(log_file):
            pytest.skip("Test data file not found")

        with open(log_file, "r") as f:
            data = f.read()

        parsed_data = parse_datamodel_logs(data)
        result = validate_device_composition(parsed_data)

        # Missing cluster is a conformance issue, not a composition issue
        # Basic structure should still be valid
        assert result["checks"]["endpoint_0_exists"]["passed"] is True
        assert result["checks"]["descriptor_on_all_endpoints"]["passed"] is True

    def test_missing_feature_attribute_logs_composition(self):
        """Test composition checks with logs that have missing feature attribute."""
        log_file = os.path.join(
            self.test_data_dir, "wildcard_missing_feature_req_attribute.txt"
        )
        if not os.path.exists(log_file):
            pytest.skip("Test data file not found")

        with open(log_file, "r") as f:
            data = f.read()

        parsed_data = parse_datamodel_logs(data)
        result = validate_device_composition(parsed_data)

        # Basic structure should still be valid
        assert result["checks"]["endpoint_0_exists"]["passed"] is True
        assert result["checks"]["descriptor_on_all_endpoints"]["passed"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
