import pytest
import sys
import os
from unittest.mock import patch, Mock

# Add current directory to sys.path to ensure utils modules can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.helper import (
    convert_to_snake_case,
    clean_line,
    convert_value,
    convert_cluster_id_to_hex,
    convert_device_type_to_hex,
)


class TestConvertToSnakeCase:
    """Test the convert_to_snake_case function"""

    def test_convert_basic_camel_case(self):
        """Test converting basic camel case"""
        assert convert_to_snake_case("CamelCase") == "camel_case"
        assert convert_to_snake_case("camelCase") == "camel_case"
        assert convert_to_snake_case("XMLHttpRequest") == "xml_http_request"

    def test_convert_with_spaces(self):
        """Test converting strings with spaces"""
        assert convert_to_snake_case("Device Type List") == "device_type_list"
        assert convert_to_snake_case("Basic Information") == "basic_information"
        assert convert_to_snake_case("On Off") == "on_off"

    def test_convert_with_numbers(self):
        """Test converting strings with numbers"""
        assert (
            convert_to_snake_case("PM2.5 Concentration Measurement")
            == "pm_2.5_concentration_measurement"
        )
        assert convert_to_snake_case("Test123Name") == "test_123_name"
        assert convert_to_snake_case("HTTP2Connection") == "http_2_connection"

    def test_convert_with_special_characters(self):
        """Test converting strings with special characters"""
        assert convert_to_snake_case("Test/Name") == "test_name"
        assert convert_to_snake_case("Test-Name") == "test_name"
        assert convert_to_snake_case("Test{Name}") == "test_name_"
        assert convert_to_snake_case("Test(Name)") == "test_name_"
        assert convert_to_snake_case("Test\\Name") == "test_name"
        assert convert_to_snake_case("Test|Name") == "test_name"

    def test_convert_command_suffix(self):
        """Test converting strings ending with 'Command'"""
        assert convert_to_snake_case("TestCommand") == "test"
        assert convert_to_snake_case("On Off Command") == "on_off_"
        assert convert_to_snake_case("StartCommand") == "start"

    def test_convert_already_snake_case(self):
        """Test converting already snake_case strings"""
        assert convert_to_snake_case("snake_case") == "snake_case"
        assert convert_to_snake_case("already_converted") == "already_converted"

    def test_convert_empty_string(self):
        """Test converting empty string"""
        assert convert_to_snake_case("") == ""

    def test_convert_single_word(self):
        """Test converting single word"""
        assert convert_to_snake_case("Test") == "test"
        assert convert_to_snake_case("test") == "test"
        assert convert_to_snake_case("TEST") == "test"

    def test_convert_with_multiple_spaces(self):
        """Test converting strings with multiple spaces"""
        assert (
            convert_to_snake_case("Test  Multiple   Spaces") == "test_multiple_spaces"
        )
        assert convert_to_snake_case("   Leading Spaces") == "_leading_spaces"
        assert convert_to_snake_case("Trailing Spaces   ") == "trailing_spaces_"

    def test_convert_with_consecutive_caps(self):
        """Test converting strings with consecutive capital letters"""
        assert convert_to_snake_case("HTTPSConnection") == "https_connection"
        assert convert_to_snake_case("XMLParser") == "xml_parser"
        assert convert_to_snake_case("JSONData") == "json_data"

    def test_convert_edge_cases(self):
        """Test converting edge cases"""
        assert convert_to_snake_case("A") == "a"
        assert convert_to_snake_case("AB") == "ab"
        assert convert_to_snake_case("ABC") == "abc"
        assert convert_to_snake_case("ABc") == "a_bc"
        assert convert_to_snake_case("AbC") == "ab_c"


class TestCleanLine:
    """Test the clean_line function"""

    def test_clean_basic_line(self):
        """Test cleaning basic line without escape sequences"""
        assert clean_line("Normal text") == "Normal text"
        assert clean_line("  Whitespace  ") == "Whitespace"

    def test_clean_escape_sequences(self):
        """Test cleaning lines with escape sequences"""
        assert clean_line("Text\x1b[0mwith escape") == "Textwith escape"
        assert clean_line("TextESC[0mwith escape") == "Textwith escape"
        assert clean_line("Text\u241b[0mwith escape") == "Textwith escape"

    def test_clean_multiple_escape_sequences(self):
        """Test cleaning lines with multiple escape sequences"""
        assert clean_line("Text\x1b[0mwith\x1b[0mmultiple") == "Textwithmultiple"
        assert clean_line("Mixed\x1b[0mESC[0m\u241b[0mescapes") == "Mixedescapes"

    def test_clean_empty_line(self):
        """Test cleaning empty line"""
        assert clean_line("") == ""
        assert clean_line("   ") == ""

    def test_clean_line_with_only_escape_sequences(self):
        """Test cleaning line with only escape sequences"""
        assert clean_line("\x1b[0m") == ""
        assert clean_line("ESC[0m") == ""
        assert clean_line("\u241b[0m") == ""

    def test_clean_line_with_tabs_and_newlines(self):
        """Test cleaning line with tabs and newlines"""
        assert clean_line("\tTabbed text\n") == "Tabbed text"
        assert clean_line("\n\rNewline text\r\n") == "Newline text"

    def test_clean_line_with_mixed_whitespace(self):
        """Test cleaning line with mixed whitespace"""
        assert (
            clean_line("  \t  Mixed   \n  whitespace  \r  ") == "Mixed   \n  whitespace"
        )


class TestConvertValue:
    """Test the convert_value function"""

    def test_convert_null_values(self):
        """Test converting null values"""
        assert convert_value("null") is None
        assert convert_value("NULL") is None
        assert convert_value("Null") is None
        assert convert_value("nUlL") is None

    def test_convert_boolean_values(self):
        """Test converting boolean values"""
        assert convert_value("true") is True
        assert convert_value("TRUE") is True
        assert convert_value("True") is True
        assert convert_value("tRuE") is True

        assert convert_value("false") is False
        assert convert_value("FALSE") is False
        assert convert_value("False") is False
        assert convert_value("fAlSe") is False

    def test_convert_numeric_values(self):
        """Test converting numeric values"""
        assert convert_value("123") == 123
        assert convert_value("0") == 0
        assert convert_value("999") == 999
        assert convert_value("000123") == 123  # Leading zeros

    def test_convert_string_values(self):
        """Test converting string values"""
        assert convert_value("regular string") == "regular string"
        assert convert_value("0x1234") == "0x1234"
        assert convert_value("non-numeric") == "non-numeric"

    def test_convert_empty_values(self):
        """Test converting empty values"""
        assert convert_value("") == ""
        assert convert_value("   ") == ""  # Should be cleaned and remain empty

    def test_convert_values_with_escape_sequences(self):
        """Test converting values with escape sequences"""
        assert convert_value("text\x1b[0mwith escape") == "textwith escape"
        assert convert_value("123\x1b[0m") == 123  # Should clean then convert to int

    def test_convert_values_with_whitespace(self):
        """Test converting values with whitespace"""
        assert convert_value("  123  ") == 123
        assert convert_value("  true  ") is True
        assert convert_value("  false  ") is False
        assert convert_value("  null  ") is None

    def test_convert_none_input(self):
        """Test converting None input"""
        assert convert_value(None) is None

    def test_convert_exception_handling(self):
        """Test exception handling in convert_value"""
        # Test with problematic input that might cause exceptions
        result = convert_value("problematic\x00\x01")
        assert isinstance(result, str)
        assert result is not None

    @patch("utils.helper.logger")
    def test_convert_with_logging(self, mock_logger):
        """Test that exceptions are logged"""
        # Force an exception by patching clean_line to raise
        with patch("utils.helper.clean_line", side_effect=Exception("Test error")):
            result = convert_value("test")

            # Should log warning
            mock_logger.warning.assert_called_once()
            assert "Error converting value" in str(mock_logger.warning.call_args)


class TestConvertClusterIdToHex:
    """Test the convert_cluster_id_to_hex function"""

    def test_convert_integer_cluster_id(self):
        """Test converting integer cluster ID"""
        assert convert_cluster_id_to_hex(29) == "0x001D"
        assert convert_cluster_id_to_hex(40) == "0x0028"
        assert convert_cluster_id_to_hex(1029) == "0x0405"
        assert convert_cluster_id_to_hex(0) == "0x0000"

    def test_convert_string_cluster_id(self):
        """Test converting string cluster ID"""
        assert convert_cluster_id_to_hex("29") == "0x001D"
        assert convert_cluster_id_to_hex("40") == "0x0028"
        assert convert_cluster_id_to_hex("1029") == "0x0405"
        assert convert_cluster_id_to_hex("0") == "0x0000"

    def test_convert_hex_string_cluster_id(self):
        """Test converting hex string cluster ID"""
        assert convert_cluster_id_to_hex("0x001D") == "0x001D"
        assert convert_cluster_id_to_hex("0x0028") == "0x0028"
        assert convert_cluster_id_to_hex("0x0405") == "0x0405"
        assert convert_cluster_id_to_hex("0x0000") == "0x0000"

    def test_convert_large_numbers(self):
        """Test converting large numbers"""
        assert convert_cluster_id_to_hex(65535) == "0xFFFF"
        assert convert_cluster_id_to_hex(4096) == "0x1000"

    def test_convert_invalid_string(self):
        """Test converting invalid string"""
        assert convert_cluster_id_to_hex("invalid") == "invalid"
        assert convert_cluster_id_to_hex("") == ""
        assert convert_cluster_id_to_hex("0xinvalid") == "0xinvalid"

    def test_convert_non_string_non_int(self):
        """Test converting non-string, non-int values"""
        assert convert_cluster_id_to_hex(None) is None
        assert convert_cluster_id_to_hex([]) == []
        assert convert_cluster_id_to_hex({}) == {}

    def test_convert_float_values(self):
        """Test converting float values"""
        assert convert_cluster_id_to_hex(29.0) == 29.0  # Should return as-is
        assert convert_cluster_id_to_hex(29.5) == 29.5  # Should return as-is


class TestConvertDeviceTypeToHex:
    """Test the convert_device_type_to_hex function"""

    def test_convert_simple_device_type(self):
        """Test converting simple device type in dict"""
        input_obj = {"DeviceType": 22, "Revision": 1}
        expected = {"DeviceType": "0x0016", "Revision": 1}

        result = convert_device_type_to_hex(input_obj)
        assert result == expected

    def test_convert_nested_device_type(self):
        """Test converting nested device type"""
        input_obj = {
            "endpoints": [
                {
                    "endpoint": 0,
                    "clusters": {
                        "0x001D": {
                            "attributes": {
                                "0x0000": {
                                    "DeviceTypeList": [
                                        {"DeviceType": 22, "Revision": 1},
                                        {"DeviceType": 256, "Revision": 1},
                                    ]
                                }
                            }
                        }
                    },
                }
            ]
        }

        result = convert_device_type_to_hex(input_obj)

        device_type_list = result["endpoints"][0]["clusters"]["0x001D"]["attributes"][
            "0x0000"
        ]["DeviceTypeList"]
        assert device_type_list[0]["DeviceType"] == "0x0016"
        assert device_type_list[1]["DeviceType"] == "0x0100"

    def test_convert_list_with_device_types(self):
        """Test converting list with device types"""
        input_obj = [
            {"DeviceType": 22, "Revision": 1},
            {"DeviceType": 256, "Revision": 1},
            {"SomeOtherKey": "value"},
        ]

        result = convert_device_type_to_hex(input_obj)

        assert result[0]["DeviceType"] == "0x0016"
        assert result[1]["DeviceType"] == "0x0100"
        assert result[2]["SomeOtherKey"] == "value"

    def test_convert_no_device_type(self):
        """Test converting objects without DeviceType"""
        input_obj = {
            "SomeKey": "value",
            "AnotherKey": 123,
            "NestedDict": {"InnerKey": "inner_value"},
        }

        result = convert_device_type_to_hex(input_obj)
        assert result == input_obj  # Should be unchanged

    def test_convert_already_hex_device_type(self):
        """Test converting already hex device type"""
        input_obj = {"DeviceType": "0x0016", "Revision": 1}

        result = convert_device_type_to_hex(input_obj)
        assert result["DeviceType"] == "0x0016"  # Should remain unchanged

    def test_convert_primitive_values(self):
        """Test converting primitive values"""
        assert convert_device_type_to_hex("string") == "string"
        assert convert_device_type_to_hex(123) == 123
        assert convert_device_type_to_hex(True) is True
        assert convert_device_type_to_hex(None) is None

    def test_convert_empty_containers(self):
        """Test converting empty containers"""
        assert convert_device_type_to_hex({}) == {}
        assert convert_device_type_to_hex([]) == []

    def test_convert_mixed_data_types(self):
        """Test converting mixed data types"""
        input_obj = {
            "string_value": "test",
            "int_value": 123,
            "bool_value": True,
            "none_value": None,
            "list_value": [1, 2, 3],
            "dict_value": {"nested": "value"},
            "device_type_value": {"DeviceType": 22},
        }

        result = convert_device_type_to_hex(input_obj)

        assert result["string_value"] == "test"
        assert result["int_value"] == 123
        assert result["bool_value"] is True
        assert result["none_value"] is None
        assert result["list_value"] == [1, 2, 3]
        assert result["dict_value"] == {"nested": "value"}
        assert result["device_type_value"]["DeviceType"] == "0x0016"

    def test_convert_multiple_device_types_same_dict(self):
        """Test converting multiple DeviceType keys in same dict"""
        input_obj = {
            "DeviceType": 22,
            "BackupDeviceType": 256,  # This should NOT be converted
            "Revision": 1,
        }

        result = convert_device_type_to_hex(input_obj)

        assert result["DeviceType"] == "0x0016"
        assert result["BackupDeviceType"] == 256  # Should remain unchanged
        assert result["Revision"] == 1

    def test_convert_deeply_nested_structure(self):
        """Test converting deeply nested structure"""
        input_obj = {
            "level1": {
                "level2": {"level3": {"level4": {"DeviceType": 22, "data": "test"}}}
            }
        }

        result = convert_device_type_to_hex(input_obj)

        assert result["level1"]["level2"]["level3"]["level4"]["DeviceType"] == "0x0016"
        assert result["level1"]["level2"]["level3"]["level4"]["data"] == "test"

    def test_convert_large_device_type_values(self):
        """Test converting large device type values"""
        input_obj = {"DeviceType": 65535, "Revision": 1}
        expected = {"DeviceType": "0xFFFF", "Revision": 1}

        result = convert_device_type_to_hex(input_obj)
        assert result == expected


class TestHelperErrorHandling:
    """Test error handling in helper functions"""

    def test_convert_to_snake_case_with_none(self):
        """Test convert_to_snake_case with None input"""
        # Should handle gracefully
        try:
            result = convert_to_snake_case(None)
            # If it succeeds, result should be reasonable
            assert result is not None
        except (TypeError, AttributeError):
            # If it fails, that's also acceptable behavior
            pass

    def test_clean_line_with_none(self):
        """Test clean_line with None input"""
        try:
            result = clean_line(None)
            assert result is not None
        except (TypeError, AttributeError):
            pass

    def test_convert_value_with_problematic_input(self):
        """Test convert_value with problematic input"""
        problematic_inputs = [
            "\x00\x01\x02",  # Binary data
            "{'invalid': json}",  # Invalid JSON-like
            "999999999999999999999999999",  # Very large number string
        ]

        for input_val in problematic_inputs:
            result = convert_value(input_val)
            # Should not raise exception
            assert result is not None

    def test_convert_cluster_id_with_extreme_values(self):
        """Test convert_cluster_id_to_hex with extreme values"""
        # Very large numbers
        assert convert_cluster_id_to_hex(999999) == "0xF423F"

        # Negative numbers (should handle gracefully)
        try:
            result = convert_cluster_id_to_hex(-1)
            assert result is not None
        except (ValueError, OverflowError):
            pass

    def test_convert_device_type_with_circular_reference(self):
        """Test convert_device_type_to_hex with circular reference"""
        # Create circular reference
        obj = {}
        obj["self"] = obj
        obj["DeviceType"] = 22

        # Should handle gracefully (may hit recursion limit)
        try:
            result = convert_device_type_to_hex(obj)
            assert result is not None
        except RecursionError:
            # This is acceptable behavior for circular references
            pass

    @patch("utils.helper.logger")
    def test_logging_in_error_conditions(self, mock_logger):
        """Test that errors are logged appropriately"""
        # Force an error in convert_value
        problematic_input = "test_input"
        with patch("utils.helper.clean_line", side_effect=Exception("Test error")):
            result = convert_value(problematic_input)

            # Should log warning
            mock_logger.warning.assert_called_once()
            assert "Error converting value" in str(mock_logger.warning.call_args)

            # Should return string representation
            assert result == "test_input"
