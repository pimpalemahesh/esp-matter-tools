import pytest
import json
import os
import sys
from unittest.mock import patch, Mock, mock_open

# Add current directory to sys.path to ensure core modules can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.compliance_checker import (
    validate_device_compliance,
    validate_single_device_type,
    validate_cluster,
    load_element_requirements,
    find_client_cluster,
    validate_feature_map,
    validate_feature_specific_elements,
    validate_revisions,
    validate_events_with_warnings,
)


class TestLoadElementRequirements:
    """Test the load_element_requirements function"""

    def test_load_valid_requirements(self, temp_requirements_file):
        """Test loading valid element requirements"""
        requirements = load_element_requirements("1.4.1")

        assert isinstance(requirements, list)
        assert len(requirements) == 2
        assert requirements[0]["id"] == 22
        assert requirements[1]["id"] == 256

    def test_load_nonexistent_file(self):
        """Test loading non-existent requirements file"""
        requirements = load_element_requirements("nonexistent_version")

        assert requirements == []

    def test_load_invalid_json(self):
        """Test loading invalid JSON file"""
        with patch("builtins.open", mock_open(read_data="invalid json")):
            with patch("os.path.exists", return_value=True):
                requirements = load_element_requirements("1.4.1")

                assert requirements == []

    def test_load_empty_file(self):
        """Test loading empty requirements file"""
        with patch("builtins.open", mock_open(read_data="")):
            with patch("os.path.exists", return_value=True):
                requirements = load_element_requirements("1.4.1")

                assert requirements == []

    @patch("core.compliance_checker.logger")
    def test_load_with_logging(self, mock_logger, temp_requirements_file):
        """Test that loading logs appropriately"""
        requirements = load_element_requirements("1.4.1")

        # Should log info about loaded requirements
        mock_logger.info.assert_called()
        assert "Loaded" in str(mock_logger.info.call_args)


class TestValidateDeviceCompliance:
    """Test the main validate_device_compliance function"""

    def test_validate_compliant_device(self, sample_parsed_data, sample_element_requirements):
        """Test validating a compliant device"""
        result = validate_device_compliance(sample_parsed_data, sample_element_requirements, "1.4.1")

        assert "endpoints" in result
        assert "summary" in result
        assert isinstance(result["endpoints"], list)
        assert len(result["endpoints"]) == 2

        summary = result["summary"]
        assert "total_endpoints" in summary
        assert "compliant_endpoints" in summary
        assert "non_compliant_endpoints" in summary
        assert summary["total_endpoints"] == 2

    def test_validate_invalid_parsed_data(self, invalid_parsed_data, sample_element_requirements):
        """Test validating invalid parsed data"""
        # Test empty dict
        with pytest.raises(ValueError, match="parsed_data must be a dictionary"):
            validate_device_compliance("not a dict", sample_element_requirements, "1.4.1")

        # Test missing endpoints
        with pytest.raises(ValueError, match="parsed_data must contain 'endpoints' key"):
            validate_device_compliance(
                invalid_parsed_data["no_endpoints"],
                sample_element_requirements,
                "1.4.1",
            )

    def test_validate_empty_requirements(self, sample_parsed_data):
        """Test validating with empty requirements"""
        result = validate_device_compliance(sample_parsed_data, [], "1.4.1")

        assert "endpoints" in result
        assert "summary" in result
        # Should handle gracefully
        assert result["summary"]["total_endpoints"] == 2

    def test_validate_invalid_requirements(self, sample_parsed_data, invalid_requirements):
        """Test validating with invalid requirements"""
        # The function handles invalid requirements gracefully rather than raising ValueError
        result = validate_device_compliance(sample_parsed_data, invalid_requirements["not_list"], "1.4.1")
        assert "endpoints" in result
        assert "summary" in result

        # Test invalid device type should handle gracefully
        result = validate_device_compliance(sample_parsed_data, invalid_requirements["invalid_device_type"], "1.4.1")
        assert "endpoints" in result

    def test_validate_device_without_descriptor(self, sample_element_requirements):
        """Test validating device without descriptor cluster"""
        parsed_data = {
            "endpoints": [
                {
                    "endpoint": 0,
                    "clusters": {
                        "0x0028": {
                            "attributes": {},
                            "events": {},
                            "commands": {},
                            "features": {},
                        }
                    },
                }
            ]
        }

        result = validate_device_compliance(parsed_data, sample_element_requirements, "1.4.1")

        assert not result["endpoints"][0]["is_compliant"]
        assert "error" in result["endpoints"][0]["device_types"][0]

    def test_validate_large_dataset(self, sample_element_requirements):
        """Test validating large dataset for performance"""
        # Create a large dataset
        large_parsed_data = {"endpoints": []}

        # Add many endpoints
        for i in range(10):
            large_parsed_data["endpoints"].append(
                {
                    "endpoint": i,
                    "clusters": {
                        "0x001D": {
                            "attributes": {"0x0000": {"DeviceTypeList": [{"DeviceType": "0x0016", "Revision": 1}]}},
                            "events": {},
                            "commands": {},
                            "features": {},
                        }
                    },
                }
            )

        result = validate_device_compliance(large_parsed_data, sample_element_requirements, "1.4.1")

        assert len(result["endpoints"]) == 10
        assert result["summary"]["total_endpoints"] == 10


class TestValidateSingleDeviceType:
    """Test the validate_single_device_type function"""

    def test_validate_compliant_device_type(self, sample_parsed_data, sample_element_requirements):
        """Test validating compliant device type"""
        endpoint = sample_parsed_data["endpoints"][0]
        device_requirements = sample_element_requirements[0]  # Root Node

        result = validate_single_device_type(endpoint, 22, device_requirements)

        assert "device_type_id" in result
        assert "device_type_name" in result
        assert "is_compliant" in result
        assert "cluster_validations" in result
        assert result["device_type_id"] == 22
        assert result["device_type_name"] == "Root Node"

    def test_validate_invalid_parameters(self, sample_parsed_data):
        """Test validating with invalid parameters"""
        endpoint = sample_parsed_data["endpoints"][0]

        # Test invalid device_requirements
        with pytest.raises(ValueError, match="device_requirements must be a dict"):
            validate_single_device_type(endpoint, 22, "not a dict")

        # Test invalid endpoint
        with pytest.raises(ValueError, match="endpoint must be a dict"):
            validate_single_device_type("not a dict", 22, {"id": 22})

    def test_validate_missing_clusters(self, sample_element_requirements):
        """Test validating device type with missing clusters"""
        endpoint = {
            "endpoint": 0,
            "clusters": {
                "0x001D": {
                    "attributes": {"0x0000": {"DeviceTypeList": [{"DeviceType": "0x0016", "Revision": 1}]}},
                    "events": {},
                    "commands": {},
                    "features": {},
                }
                # Missing 0x0028 cluster
            },
        }

        device_requirements = sample_element_requirements[0]  # Root Node
        result = validate_single_device_type(endpoint, 22, device_requirements)

        assert not result["is_compliant"]
        assert len(result["missing_elements"]) > 0

    def test_validate_revision_mismatch(self, sample_element_requirements):
        """Test validating device type with revision mismatch"""
        endpoint = {
            "endpoint": 0,
            "clusters": {
                "0x001D": {
                    "attributes": {
                        "0x0000": {
                            "DeviceTypeList": [
                                {
                                    "DeviceType": "0x0016",
                                    "Revision": 2,
                                }  # Wrong revision
                            ]
                        }
                    },
                    "events": {},
                    "commands": {},
                    "features": {},
                }
            },
        }

        device_requirements = sample_element_requirements[0]  # Root Node
        result = validate_single_device_type(endpoint, 22, device_requirements)

        assert not result["is_compliant"]
        assert len(result["revision_issues"]) > 0

    def test_validate_device_type_not_found(self, sample_element_requirements):
        """Test validating device type not found in descriptor"""
        endpoint = {
            "endpoint": 0,
            "clusters": {
                "0x001D": {
                    "attributes": {
                        "0x0000": {
                            "DeviceTypeList": [
                                {
                                    "DeviceType": "0x0100",
                                    "Revision": 1,
                                }  # Different device type
                            ]
                        }
                    },
                    "events": {},
                    "commands": {},
                    "features": {},
                }
            },
        }

        device_requirements = sample_element_requirements[0]  # Root Node (22)
        result = validate_single_device_type(endpoint, 22, device_requirements)

        # Should still validate the clusters but may have issues
        assert "cluster_validations" in result


class TestValidateCluster:
    """Test the validate_cluster function"""

    def test_validate_compliant_cluster(self, sample_parsed_data):
        """Test validating compliant cluster"""
        endpoint_clusters = sample_parsed_data["endpoints"][0]["clusters"]
        required_cluster = {
            "id": "0x001D",
            "name": "Descriptor",
            "type": "server",
            "attributes": [{"id": "0x0000", "name": "DeviceTypeList"}],
        }

        result = validate_cluster(endpoint_clusters, required_cluster)

        assert result["cluster_id"] == "0x001D"
        assert result["cluster_name"] == "Descriptor"
        assert result["cluster_type"] == "server"
        assert result["is_compliant"]
        assert len(result["missing_elements"]) == 0

    def test_validate_missing_cluster(self, sample_parsed_data):
        """Test validating missing cluster"""
        endpoint_clusters = sample_parsed_data["endpoints"][0]["clusters"]
        required_cluster = {
            "id": "0x0006",  # Missing cluster
            "name": "On/Off",
            "type": "server",
            "attributes": [{"id": "0x0000", "name": "OnOff"}],
        }

        result = validate_cluster(endpoint_clusters, required_cluster)

        assert not result["is_compliant"]
        assert len(result["missing_elements"]) == 1
        assert result["missing_elements"][0]["type"] == "cluster"

    def test_validate_client_cluster(self, sample_parsed_data):
        """Test validating client cluster"""
        endpoint_clusters = sample_parsed_data["endpoints"][0]["clusters"]
        required_cluster = {
            "id": "0x0006",
            "name": "On/Off",
            "type": "client",
            "attributes": [],
        }

        result = validate_cluster(endpoint_clusters, required_cluster)

        # Should check for client cluster in ClientList
        assert result["cluster_type"] == "client"

    def test_validate_missing_attributes(self, sample_parsed_data):
        """Test validating cluster with missing attributes"""
        endpoint_clusters = sample_parsed_data["endpoints"][0]["clusters"]
        required_cluster = {
            "id": "0x001D",
            "name": "Descriptor",
            "type": "server",
            "attributes": [
                {"id": "0x0000", "name": "DeviceTypeList"},
                {"id": "0x0099", "name": "MissingAttribute"},  # Missing attribute
            ],
        }

        result = validate_cluster(endpoint_clusters, required_cluster)

        assert not result["is_compliant"]
        assert len(result["missing_elements"]) == 1
        assert result["missing_elements"][0]["type"] == "attribute"

    def test_validate_missing_commands(self, sample_parsed_data):
        """Test validating cluster with missing commands"""
        endpoint_clusters = sample_parsed_data["endpoints"][0]["clusters"]
        required_cluster = {
            "id": "0x001D",
            "name": "Descriptor",
            "type": "server",
            "attributes": [],
            "commands": [{"id": "0x0000", "name": "TestCommand"}],  # Missing command
        }

        result = validate_cluster(endpoint_clusters, required_cluster)

        assert not result["is_compliant"]
        assert len(result["missing_elements"]) == 1
        assert result["missing_elements"][0]["type"] == "command"

    def test_validate_invalid_required_cluster(self, sample_parsed_data):
        """Test validating with invalid required cluster"""
        endpoint_clusters = sample_parsed_data["endpoints"][0]["clusters"]

        with pytest.raises(ValueError, match="required_cluster must be a dict"):
            validate_cluster(endpoint_clusters, "not a dict")

    def test_validate_cluster_revision(self, sample_parsed_data):
        """Test validating cluster revision"""
        endpoint_clusters = {
            "0x0028": {
                "attributes": {},
                "events": {},
                "commands": {},
                "features": {"ClusterRevision": {"ClusterRevision": 1}},
            }
        }

        required_cluster = {
            "id": "0x0028",
            "name": "Basic Information",
            "type": "server",
            "revision": 2,  # Different revision
            "attributes": [],
        }

        result = validate_cluster(endpoint_clusters, required_cluster)

        assert not result["is_compliant"]
        assert len(result["revision_issues"]) > 0


class TestFindClientCluster:
    """Test the find_client_cluster function"""

    def test_find_existing_client_cluster(self):
        """Test finding existing client cluster"""
        endpoint_clusters = {
            "0x001D": {
                "attributes": {"0x0002": {"ClientList": [{"id": "0x0006"}]}},
                "events": {},
                "commands": {},
                "features": {},
            }
        }

        result = find_client_cluster(endpoint_clusters, "0x0006")
        assert result is True

    def test_find_nonexistent_client_cluster(self):
        """Test finding non-existent client cluster"""
        endpoint_clusters = {
            "0x001D": {
                "attributes": {"0x0002": {"ClientList": [{"id": "0x0006"}]}},
                "events": {},
                "commands": {},
                "features": {},
            }
        }

        result = find_client_cluster(endpoint_clusters, "0x0008")
        assert result is False

    def test_find_client_cluster_in_top_level(self):
        """Test finding client cluster in top level ClientList"""
        endpoint_clusters = {
            "0x001D": {
                "ClientList": [{"id": "0x0006"}],
                "attributes": {},
                "events": {},
                "commands": {},
                "features": {},
            }
        }

        result = find_client_cluster(endpoint_clusters, "0x0006")
        assert result is True

    def test_find_client_cluster_nested(self):
        """Test finding client cluster in nested structure"""
        endpoint_clusters = {
            "0x001D": {
                "attributes": {"0x0002": {"ClientList": {"ClientList": [{"id": "0x0006"}]}}},
                "events": {},
                "commands": {},
                "features": {},
            }
        }

        result = find_client_cluster(endpoint_clusters, "0x0006")
        assert result is True

    def test_find_client_cluster_empty_clusters(self):
        """Test finding client cluster in empty clusters"""
        endpoint_clusters = {}

        result = find_client_cluster(endpoint_clusters, "0x0006")
        assert result is False


class TestValidateFeatureMap:
    """Test the validate_feature_map function"""

    def test_validate_compliant_features(self):
        """Test validating compliant features"""
        actual_feature_map = "0x0003"  # Binary: 0011 (features 0 and 1)
        required_features = [
            {"id": "0x0001", "name": "Feature1"},  # Bit 0
            {"id": "0x0002", "name": "Feature2"},  # Bit 1
        ]

        is_compliant, missing_features = validate_feature_map(actual_feature_map, required_features, "0x0028", "Basic Information")

        assert is_compliant
        assert len(missing_features) == 0

    def test_validate_missing_features(self):
        """Test validating missing features"""
        actual_feature_map = "0x0001"  # Binary: 0001 (only feature 0)
        required_features = [
            {"id": "0x0001", "name": "Feature1"},  # Bit 0 - present
            {"id": "0x0002", "name": "Feature2"},  # Bit 1 - missing
        ]

        is_compliant, missing_features = validate_feature_map(actual_feature_map, required_features, "0x0028", "Basic Information")

        assert not is_compliant
        assert len(missing_features) == 1
        assert missing_features[0]["name"] == "Feature2"

    def test_validate_no_required_features(self):
        """Test validating when no features are required"""
        actual_feature_map = "0x0000"
        required_features = []

        is_compliant, missing_features = validate_feature_map(actual_feature_map, required_features, "0x0028", "Basic Information")

        assert is_compliant
        assert len(missing_features) == 0

    def test_validate_integer_feature_map(self):
        """Test validating integer feature map"""
        actual_feature_map = 3  # Binary: 0011
        required_features = [
            {"id": 1, "name": "Feature1"},
            {"id": 2, "name": "Feature2"},
        ]

        is_compliant, missing_features = validate_feature_map(actual_feature_map, required_features, "0x0028", "Basic Information")

        assert is_compliant
        assert len(missing_features) == 0

    def test_validate_invalid_feature_map(self):
        """Test validating invalid feature map"""
        actual_feature_map = "invalid"
        required_features = [{"id": "0x0001", "name": "Feature1"}]

        is_compliant, missing_features = validate_feature_map(actual_feature_map, required_features, "0x0028", "Basic Information")

        assert not is_compliant
        assert len(missing_features) == 1
        assert "Feature validation error" in missing_features[0]["message"]

    def test_validate_feature_map_exception(self):
        """Test feature map validation exception handling"""
        actual_feature_map = None
        required_features = [{"id": "0x0001", "name": "Feature1"}]

        is_compliant, missing_features = validate_feature_map(actual_feature_map, required_features, "0x0028", "Basic Information")

        assert not is_compliant
        assert len(missing_features) == 1
        assert "Invalid feature_map format" in missing_features[0]["message"]


class TestValidateFeatureSpecificElements:
    """Test the validate_feature_specific_elements function"""

    def test_validate_feature_specific_elements_with_present_feature(self):
        """Test validating feature-specific elements when feature is present"""
        actual_cluster = {
            "features": {"FeatureMap": {"FeatureMap": 1}},  # Feature 0x0001 is present (bit 0 set)
            "attributes": {
                "0x4000": {"global_scene_control": True},
                "0x4001": {"on_time": 0},
                # Missing 0x4002 (off_wait_time) and 0x4003 (start_up_on_off)
            },
            "commands": {
                "AcceptedCommandList": {
                    "AcceptedCommandList": [
                        {"id": "0x0040", "name": "off_with_effect"}
                        # Missing 0x0041 and 0x0042
                    ]
                }
            },
            "events": {"EventList": {"EventList": []}},
        }

        required_features = [
            {
                "id": "0x0001",
                "name": "lighting",
                "attributes": [{"id": "0x4000", "name": "global_scene_control"}, {"id": "0x4001", "name": "on_time"}, {"id": "0x4002", "name": "off_wait_time"}, {"id": "0x4003", "name": "start_up_on_off"}],
                "commands": [{"id": "0x0040", "name": "off_with_effect"}, {"id": "0x0041", "name": "on_with_recall_global_scene"}, {"id": "0x0042", "name": "on_with_timed_off"}],
                "events": [],
            }
        ]

        is_compliant, missing_elements = validate_feature_specific_elements(actual_cluster, required_features, "0x0006", "On/Off")

        assert not is_compliant
        assert len(missing_elements) == 4

        # Check for missing feature attributes
        feature_attrs = [e for e in missing_elements if e["type"] == "feature_attribute"]
        assert len(feature_attrs) == 2
        assert any(e["id"] == "0x4002" and e["name"] == "off_wait_time" for e in feature_attrs)
        assert any(e["id"] == "0x4003" and e["name"] == "start_up_on_off" for e in feature_attrs)

        # Check for missing feature commands
        feature_cmds = [e for e in missing_elements if e["type"] == "feature_command"]
        assert len(feature_cmds) == 2
        assert any(e["id"] == "0x0041" and e["name"] == "on_with_recall_global_scene" for e in feature_cmds)
        assert any(e["id"] == "0x0042" and e["name"] == "on_with_timed_off" for e in feature_cmds)

    def test_validate_feature_specific_elements_with_absent_feature(self):
        """Test validating feature-specific elements when feature is not present"""
        actual_cluster = {
            "features": {"FeatureMap": {"FeatureMap": 0}},  # No features present
            "attributes": {},
            "commands": {"AcceptedCommandList": {"AcceptedCommandList": []}},
            "events": {"EventList": {"EventList": []}},
        }

        required_features = [{"id": "0x0001", "name": "lighting", "attributes": [{"id": "0x4000", "name": "global_scene_control"}], "commands": [{"id": "0x0040", "name": "off_with_effect"}], "events": []}]

        is_compliant, missing_elements = validate_feature_specific_elements(actual_cluster, required_features, "0x0006", "On/Off")

        # Should be compliant because feature is not present, so no feature-specific validation needed
        assert is_compliant
        assert len(missing_elements) == 0

    def test_validate_feature_specific_elements_no_feature_map(self):
        """Test validating feature-specific elements when no FeatureMap exists"""
        actual_cluster = {"attributes": {}, "commands": {}, "events": {}}

        required_features = [{"id": "0x0001", "name": "lighting", "attributes": [{"id": "0x4000", "name": "global_scene_control"}]}]

        is_compliant, missing_elements = validate_feature_specific_elements(actual_cluster, required_features, "0x0006", "On/Off")

        # Should be compliant because no FeatureMap means no feature-specific validation
        assert is_compliant
        assert len(missing_elements) == 0

    def test_validate_feature_specific_elements_empty_requirements(self):
        """Test validating feature-specific elements with empty requirements"""
        actual_cluster = {"features": {"FeatureMap": {"FeatureMap": 1}}}

        is_compliant, missing_elements = validate_feature_specific_elements(actual_cluster, [], "0x0006", "On/Off")

        assert is_compliant
        assert len(missing_elements) == 0


class TestValidateRevisions:
    """Test the validate_revisions function"""

    def test_validate_matching_revisions(self):
        """Test validating matching revisions"""
        is_compliant, issues = validate_revisions(1, 1, "cluster", "0x0028", "Basic Information")

        assert is_compliant
        assert len(issues) == 0

    def test_validate_mismatched_revisions(self):
        """Test validating mismatched revisions"""
        is_compliant, issues = validate_revisions(1, 2, "cluster", "0x0028", "Basic Information")

        assert not is_compliant
        assert len(issues) == 1
        assert issues[0]["severity"] == "error"
        assert "revision 1" in issues[0]["message"]
        assert "requires exactly revision 2" in issues[0]["message"]

    def test_validate_string_revisions(self):
        """Test validating string revisions"""
        is_compliant, issues = validate_revisions("1", "1", "device_type", "0x0016", "Root Node")

        assert is_compliant
        assert len(issues) == 0

    def test_validate_none_revisions(self):
        """Test validating None revisions"""
        is_compliant, issues = validate_revisions(None, 1, "cluster", "0x0028", "Basic Information")

        assert is_compliant  # Should return True when actual is None
        assert len(issues) == 0

    def test_validate_revision_exception(self):
        """Test revision validation exception handling"""
        is_compliant, issues = validate_revisions("invalid", 1, "cluster", "0x0028", "Basic Information")

        assert not is_compliant
        assert len(issues) == 1
        assert "Revision validation error" in issues[0]["message"]


class TestValidateEventsWithWarnings:
    """Test the validate_events_with_warnings function"""

    def test_validate_events_no_requirements(self):
        """Test validating events with no requirements"""
        actual_cluster = {"events": {}}
        required_events = []

        warnings = validate_events_with_warnings(actual_cluster, required_events, "0x0028", "Basic Information")

        assert len(warnings) == 0

    def test_validate_events_with_requirements(self):
        """Test validating events with requirements"""
        actual_cluster = {"events": {}}
        required_events = [{"id": "0x0000", "name": "TestEvent"}]

        warnings = validate_events_with_warnings(actual_cluster, required_events, "0x0028", "Basic Information")

        assert len(warnings) > 0
        # Should have info about event validation being skipped
        assert any("Event validation skipped" in warning["message"] for warning in warnings)

    def test_validate_events_with_event_list(self):
        """Test validating events with EventList present"""
        actual_cluster = {"events": {"EventList": {"EventList": [{"id": "0x0000"}]}}}
        required_events = [{"id": "0x0000", "name": "TestEvent"}]

        warnings = validate_events_with_warnings(actual_cluster, required_events, "0x0028", "Basic Information")

        assert len(warnings) > 0
        # Should have info about found events
        assert any("Found" in warning["message"] for warning in warnings)

    def test_validate_events_different_formats(self):
        """Test validating events with different ID formats"""
        actual_cluster = {"events": {"EventList": {"EventList": [0, "0x0001"]}}}
        required_events = [
            {"id": "0x0000", "name": "TestEvent1"},
            {"id": "0x0001", "name": "TestEvent2"},
        ]

        warnings = validate_events_with_warnings(actual_cluster, required_events, "0x0028", "Basic Information")

        assert len(warnings) > 0


class TestComplianceCheckerErrorHandling:
    """Test error handling in compliance checker"""

    def test_validate_device_compliance_exception(self, sample_element_requirements):
        """Test device compliance validation exception handling"""
        # Invalid parsed data should raise ValueError
        with pytest.raises(ValueError):
            validate_device_compliance(None, sample_element_requirements, "1.4.1")

    def test_validate_cluster_exception(self):
        """Test cluster validation exception handling"""
        endpoint_clusters = {}

        # Invalid required cluster should raise ValueError
        with pytest.raises(ValueError):
            validate_cluster(endpoint_clusters, None)

    def test_validate_single_device_type_exception(self):
        """Test single device type validation exception handling"""
        # Invalid parameters should raise ValueError
        with pytest.raises(ValueError):
            validate_single_device_type(None, 22, {"id": 22})

    @patch("core.compliance_checker.logger")
    def test_logging_on_validation_errors(self, mock_logger, sample_parsed_data):
        """Test that validation errors are logged appropriately"""
        # Test with malformed requirements
        malformed_requirements = [{"id": 22, "clusters": [{"invalid": "cluster"}]}]

        result = validate_device_compliance(sample_parsed_data, malformed_requirements, "1.4.1")

        # Should handle gracefully and log errors
        assert "endpoints" in result
        # Logger should have been called for errors
        assert mock_logger.error.called or mock_logger.info.called

    def test_performance_with_large_requirements(self, sample_parsed_data):
        """Test performance with large requirements dataset"""
        # Create large requirements
        large_requirements = []
        for i in range(100):
            large_requirements.append(
                {
                    "id": i,
                    "name": f"Device{i}",
                    "clusters": [
                        {
                            "id": "0x001D",
                            "name": "Descriptor",
                            "type": "server",
                            "attributes": [{"id": "0x0000", "name": "DeviceTypeList"}],
                        }
                    ],
                }
            )

        # Should complete without timeout
        result = validate_device_compliance(sample_parsed_data, large_requirements, "1.4.1")

        assert "endpoints" in result
        assert "summary" in result
