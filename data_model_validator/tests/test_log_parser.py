import json
import os
import sys
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from core.log_parser import convert_cluster_list_to_objects
from core.log_parser import convert_value
from core.log_parser import parse_block
from core.log_parser import parse_datamodel_logs
from core.log_parser import parse_id_name_string
from core.log_parser import parse_input
from core.log_parser import parse_metadata_line
from core.log_parser import process_attribute_data

# Add current directory to sys.path to ensure core modules can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestParseDatamodelLogs:
    """Test the main parse_datamodel_logs function"""

    def test_parse_valid_log_data(self, sample_log_data):
        """Test parsing valid log data

        :param sample_log_data:

        """
        result = parse_datamodel_logs(sample_log_data)

        assert "endpoints" in result
        assert len(result["endpoints"]) == 2

        # Check endpoint 0
        endpoint_0 = result["endpoints"][0]
        assert endpoint_0["endpoint"] == 0
        assert "clusters" in endpoint_0
        assert "0x001D" in endpoint_0["clusters"]
        assert "0x0028" in endpoint_0["clusters"]

        # Check endpoint 1
        endpoint_1 = result["endpoints"][1]
        assert endpoint_1["endpoint"] == 1
        assert "clusters" in endpoint_1
        assert "0x001D" in endpoint_1["clusters"]

    def test_parse_empty_data(self, invalid_log_data):
        """Test parsing empty data raises ValueError

        :param invalid_log_data:

        """
        with pytest.raises(ValueError, match="No \\[TOO\\] entries found"):
            parse_datamodel_logs(invalid_log_data["empty"])

    def test_parse_no_too_entries(self, invalid_log_data):
        """Test parsing data without [TOO] entries raises ValueError

        :param invalid_log_data:

        """
        # Use data that truly doesn't contain [TOO] entries
        clean_data = "Random log data with no special markers"
        with pytest.raises(ValueError, match="No \\[TOO\\] entries found"):
            parse_datamodel_logs(clean_data)

    def test_parse_malformed_data_continues(self, invalid_log_data):
        """Test parsing continues even with some malformed data

        :param invalid_log_data:

        """
        # This should not raise an exception but should handle gracefully
        result = parse_datamodel_logs(invalid_log_data["mixed_valid_invalid"])
        assert "endpoints" in result

    def test_parse_single_endpoint(self):
        """Test parsing data with single endpoint"""
        single_endpoint_data = """[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0000 DataVersion: 1
DeviceTypeList: 1 entries
[0]: {
  DeviceType: 22
  Revision: 1
}"""
        result = parse_datamodel_logs(single_endpoint_data)

        assert len(result["endpoints"]) == 1
        assert result["endpoints"][0]["endpoint"] == 0

    def test_parse_multiple_attributes_same_cluster(self):
        """Test parsing multiple attributes for the same cluster"""
        multi_attr_data = """[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0000 DataVersion: 1
DeviceTypeList: 1 entries
[0]: {
  DeviceType: 22
  Revision: 1
}
[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0001 DataVersion: 1
ServerList: 2 entries
[0]: 29
[1]: 40"""
        result = parse_datamodel_logs(multi_attr_data)

        cluster_data = result["endpoints"][0]["clusters"]["0x001D"]
        assert "0x0000" in cluster_data["attributes"]
        assert "0x0001" in cluster_data["attributes"]


class TestParseInput:
    """Test the parse_input function"""

    def test_parse_input_with_metadata(self):
        """Test parsing input with metadata line"""
        input_text = """Endpoint: 0 Cluster: 0x001D Attribute 0x0000 DataVersion: 1
DeviceTypeList: 1 entries
[0]: {
  DeviceType: 22
  Revision: 1
}"""
        result = parse_input(input_text)

        assert result["Endpoint"] == 0
        assert result["Cluster"] == "0x001D"
        assert result["Attribute"] == "0x0000"
        assert "DeviceTypeList" in result

    def test_parse_input_without_metadata(self):
        """Test parsing input without metadata line"""
        input_text = """DeviceTypeList: 1 entries
[0]: {
  DeviceType: 22
  Revision: 1
}"""
        result = parse_input(input_text)

        # The function parses the list but only returns the inner object
        assert result["DeviceType"] == 22
        assert result["Revision"] == 1

    def test_parse_input_empty(self):
        """Test parsing empty input"""
        result = parse_input("")
        assert result == {}

    def test_parse_input_whitespace_only(self):
        """Test parsing whitespace-only input"""
        result = parse_input("   \n\t  \n")
        assert result == {}


class TestParseBlock:
    """Test the parse_block function"""

    def test_parse_simple_key_value(self):
        """Test parsing simple key-value pairs"""
        lines = ["Key1: Value1", "Key2: Value2"]
        result, _ = parse_block(lines)

        assert result["Key1"] == "Value1"
        assert result["Key2"] == "Value2"

    def test_parse_list_entries(self):
        """Test parsing list entries"""
        lines = ["TestList: 2 entries", "[0]: FirstItem", "[1]: SecondItem"]
        result, _ = parse_block(lines)

        assert "TestList" in result
        assert len(result["TestList"]) == 2
        assert result["TestList"][0] == "FirstItem"
        assert result["TestList"][1] == "SecondItem"

    def test_parse_nested_objects(self):
        """Test parsing nested objects"""
        lines = ["NestedObject: {", "  InnerKey: InnerValue", "}"]
        result, _ = parse_block(lines)

        assert "NestedObject" in result
        assert result["NestedObject"]["InnerKey"] == "InnerValue"

    def test_parse_list_with_objects(self):
        """Test parsing list with nested objects"""
        lines = [
            "ObjectList: 1 entries",
            "[0]: {",
            "  DeviceType: 22",
            "  Revision: 1",
            "}",
        ]
        result, _ = parse_block(lines)

        assert "ObjectList" in result
        assert len(result["ObjectList"]) == 1
        assert result["ObjectList"][0]["DeviceType"] == 22
        assert result["ObjectList"][0]["Revision"] == 1

    def test_parse_empty_lines(self):
        """Test parsing with empty lines"""
        lines = ["", "Key: Value", "", ""]
        result, _ = parse_block(lines)

        assert result["Key"] == "Value"

    def test_parse_malformed_lines(self):
        """Test parsing with malformed lines"""
        lines = ["Key: Value", "MalformedLine", "Key2: Value2"]
        result, _ = parse_block(lines)

        assert result["Key"] == "Value"
        assert result["Key2"] == "Value2"


class TestConvertValue:
    """Test the convert_value function"""

    def test_convert_null_values(self):
        """Test converting null values"""
        assert convert_value("null") is None
        assert convert_value("NULL") is None
        assert convert_value("Null") is None

    def test_convert_boolean_values(self):
        """Test converting boolean values"""
        assert convert_value("true") is True
        assert convert_value("TRUE") is True
        assert convert_value("True") is True
        assert convert_value("false") is False
        assert convert_value("FALSE") is False
        assert convert_value("False") is False

    def test_convert_numeric_values(self):
        """Test converting numeric values"""
        assert convert_value("123") == 123
        assert convert_value("0") == 0
        assert convert_value("999") == 999

    def test_convert_id_name_strings(self):
        """Test converting ID/Name format strings"""
        result = convert_value("0 (Off)")
        assert result["id"] == "0x0000"
        assert result["name"] == "off"

        result = convert_value("1 (On)")
        assert result["id"] == "0x0001"
        assert result["name"] == "on"

    def test_convert_regular_strings(self):
        """Test converting regular strings"""
        assert convert_value("regular string") == "regular string"
        assert convert_value("0x1234") == "0x1234"

    def test_convert_empty_values(self):
        """Test converting empty values"""
        assert convert_value("") == ""
        assert convert_value(None) is None

    def test_convert_invalid_values(self):
        """Test converting invalid values gracefully"""
        # Should not raise exception, just return string
        result = convert_value("invalid{format")
        assert isinstance(result, str)


class TestParseIdNameString:
    """Test the parse_id_name_string function"""

    def test_parse_standard_format(self):
        """Test parsing standard ID (Name) format"""
        result = parse_id_name_string("0 (Off)")
        assert result["id"] == "0x0000"
        assert result["name"] == "off"

        result = parse_id_name_string("255 (MaxValue)")
        assert result["id"] == "0x00FF"
        assert result["name"] == "max_value"

    def test_parse_hex_values(self):
        """Test parsing hex values"""
        result = parse_id_name_string("0x001D")
        assert result == "0x001D"

        result = parse_id_name_string("0x0000_0001")
        assert result == "0x0001"

    def test_parse_numeric_strings(self):
        """Test parsing numeric strings"""
        result = parse_id_name_string("123")
        assert result == "0x007B"

        result = parse_id_name_string("0")
        assert result == "0x0000"

    def test_parse_regular_strings(self):
        """Test parsing regular strings"""
        result = parse_id_name_string("regular string")
        assert result == "regular string"

    def test_parse_empty_string(self):
        """Test parsing empty string"""
        result = parse_id_name_string("")
        assert result == ""

    def test_parse_whitespace_handling(self):
        """Test parsing with extra whitespace"""
        result = parse_id_name_string("  1 (On)  ")
        assert result["id"] == "0x0001"
        assert result["name"] == "on"

    def test_parse_invalid_hex(self):
        """Test parsing invalid hex values"""
        result = parse_id_name_string("0xInvalid")
        assert result == "0xInvalid"  # Should return as-is


class TestConvertClusterListToObjects:
    """Test the convert_cluster_list_to_objects function"""

    def test_convert_integer_list(self):
        """Test converting list of integers"""
        input_list = [29, 40, 1029]
        result = convert_cluster_list_to_objects(input_list)

        expected = [{"id": "0x001D"}, {"id": "0x0028"}, {"id": "0x0405"}]
        assert result == expected

    def test_convert_string_list(self):
        """Test converting list of strings"""
        input_list = ["29", "40", "1029"]
        result = convert_cluster_list_to_objects(input_list)

        expected = [{"id": "0x001D"}, {"id": "0x0028"}, {"id": "0x0405"}]
        assert result == expected

    def test_convert_mixed_list(self):
        """Test converting mixed list of integers and strings"""
        input_list = [29, "40", 1029]
        result = convert_cluster_list_to_objects(input_list)

        expected = [{"id": "0x001D"}, {"id": "0x0028"}, {"id": "0x0405"}]
        assert result == expected

    def test_convert_existing_objects(self):
        """Test converting list that already contains objects"""
        input_list = [{"id": "0x001D"}, 40, {"id": "0x0405"}]
        result = convert_cluster_list_to_objects(input_list)

        expected = [{"id": "0x001D"}, {"id": "0x0028"}, {"id": "0x0405"}]
        assert result == expected

    def test_convert_empty_list(self):
        """Test converting empty list"""
        result = convert_cluster_list_to_objects([])
        assert result == []

    def test_convert_non_list_input(self):
        """Test converting non-list input"""
        result = convert_cluster_list_to_objects("not a list")
        assert result == "not a list"

    def test_convert_hex_strings(self):
        """Test converting hex string values"""
        input_list = ["0x001D", "0x0028"]
        result = convert_cluster_list_to_objects(input_list)

        expected = [{"id": "0x001D"}, {"id": "0x0028"}]
        assert result == expected


class TestParseMetadataLine:
    """Test the parse_metadata_line function"""

    def test_parse_valid_metadata(self):
        """Test parsing valid metadata line"""
        line = "Endpoint: 0 Cluster: 0x001D Attribute 0x0000 DataVersion: 1"
        result = parse_metadata_line(line)

        assert result["Endpoint"] == 0
        assert result["Cluster"] == "0x001D"
        assert result["Attribute"] == "0x0000"

    def test_parse_different_values(self):
        """Test parsing metadata with different values"""
        line = "Endpoint: 1 Cluster: 0x0028 Attribute 0xFFFC DataVersion: 5"
        result = parse_metadata_line(line)

        assert result["Endpoint"] == 1
        assert result["Cluster"] == "0x0028"
        assert result["Attribute"] == "0xFFFC"

    def test_parse_hex_with_underscores(self):
        """Test parsing hex values with underscores"""
        line = "Endpoint: 0 Cluster: 0x001D_0001 Attribute 0x0000_0001 DataVersion: 1"
        result = parse_metadata_line(line)

        assert result["Endpoint"] == 0
        assert result["Cluster"] == "0x001D_0001"
        assert result["Attribute"] == "0x0000_0001"

    def test_parse_invalid_metadata(self):
        """Test parsing invalid metadata line"""
        line = "Invalid metadata format"
        result = parse_metadata_line(line)

        assert result == {}

    def test_parse_empty_metadata(self):
        """Test parsing empty metadata line"""
        result = parse_metadata_line("")
        assert result == {}

    def test_parse_partial_metadata(self):
        """Test parsing partial metadata line"""
        line = "Endpoint: 0 Cluster: 0x001D"
        result = parse_metadata_line(line)

        assert (
            result == {}
        )  # Should return empty dict if pattern doesn't match completely


class TestProcessAttributeData:
    """Test the process_attribute_data function"""

    def test_process_valid_attribute_data(self):
        """Test processing valid attribute data"""
        attribute_lines = [
            "Endpoint: 0 Cluster: 0x001D Attribute 0x0000 DataVersion: 1",
            "DeviceTypeList: 1 entries",
            "[0]: {",
            "  DeviceType: 22",
            "  Revision: 1",
            "}",
        ]
        endpoints = {}

        process_attribute_data(attribute_lines, endpoints)

        assert 0 in endpoints
        assert "0x001D" in endpoints[0]
        assert len(endpoints[0]["0x001D"]) == 1

    def test_process_empty_attribute_data(self):
        """Test processing empty attribute data"""
        endpoints = {}
        process_attribute_data([], endpoints)

        assert endpoints == {}

    def test_process_malformed_attribute_data(self):
        """Test processing malformed attribute data"""
        attribute_lines = ["Invalid attribute data"]
        endpoints = {}

        # Should not raise exception
        process_attribute_data(attribute_lines, endpoints)

        # Should handle gracefully
        assert isinstance(endpoints, dict)

    def test_process_multiple_attributes_same_cluster(self):
        """Test processing multiple attributes for same cluster"""
        attribute_lines1 = [
            "Endpoint: 0 Cluster: 0x001D Attribute 0x0000 DataVersion: 1",
            "DeviceTypeList: 1 entries",
            "[0]: {",
            "  DeviceType: 22",
            "  Revision: 1",
            "}",
        ]
        attribute_lines2 = [
            "Endpoint: 0 Cluster: 0x001D Attribute 0x0001 DataVersion: 1",
            "ServerList: 2 entries",
            "[0]: 29",
            "[1]: 40",
        ]
        endpoints = {}

        process_attribute_data(attribute_lines1, endpoints)
        process_attribute_data(attribute_lines2, endpoints)

        assert 0 in endpoints
        assert "0x001D" in endpoints[0]
        assert len(endpoints[0]["0x001D"]) == 2


class TestLogParserErrorHandling:
    """Test error handling in log parser"""

    def test_parse_with_exception_handling(self, mock_logger):
        """Test that exceptions are handled gracefully

        :param mock_logger:

        """
        invalid_data = "[TOO] Endpoint: abc Cluster: invalid"

        # Should handle gracefully and not crash
        try:
            result = parse_datamodel_logs(invalid_data)
            # If it succeeds, it should return a valid structure
            assert "endpoints" in result
        except ValueError as e:
            # If it fails, it should be due to no valid [TOO] entries
            assert "No [TOO] entries found" in str(e)

    def test_convert_value_exception_handling(self, mock_logger):
        """Test that convert_value handles exceptions gracefully

        :param mock_logger:

        """
        # Test with various problematic inputs
        problematic_inputs = [
            "{'invalid': json}",
            "0x{invalid_hex}",
            "999999999999999999999999999",  # Very large number
            "\x00\x01\x02",  # Binary data
        ]

        for input_val in problematic_inputs:
            result = convert_value(input_val)
            # Should not raise exception and should return some valid value
            assert result is not None

    @patch("core.log_parser.logger")
    def test_logging_on_errors(self, mock_logger):
        """Test that errors are logged appropriately

        :param mock_logger:

        """
        invalid_data = "[TOO] Some malformed data that causes processing errors"

        try:
            parse_datamodel_logs(invalid_data)
        except ValueError:
            pass  # Expected for no valid [TOO] entries

        # Logger should have been called (exact calls depend on implementation)
        assert (mock_logger.info.called or mock_logger.error.called
                or mock_logger.warning.called)
