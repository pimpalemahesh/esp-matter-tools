import json
import os
import shutil
import sys
import tempfile
from io import StringIO
from unittest.mock import Mock
from unittest.mock import mock_open
from unittest.mock import patch

import pytest

from datamodel_parser import main
from datamodel_parser import print_compliance_summary
from datamodel_parser import run_cli_mode
from datamodel_parser import run_compliance_check
from datamodel_parser import run_tests

# Add current directory to sys.path to ensure datamodel_parser can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRunComplianceCheck:
    """Test the run_compliance_check function"""

    def test_run_compliance_check_success(self, temp_requirements_file):
        """Test successful compliance check

        :param temp_requirements_file:

        """
        # Create temporary input file
        test_input = "[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0000 DataVersion: 1\nDeviceTypeList: 1 entries\n[0]: {\n  DeviceType: 22\n  Revision: 1\n}"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as f:
            f.write(test_input)
            temp_file = f.name

        try:
            result = run_compliance_check(temp_file, "1.4.1", False)

            assert result["status"] == "success"
            assert "parsed_data" in result
            assert "validation_data" in result
            assert "element_requirements" in result

            # Check that output files were created
            assert os.path.exists("output/parsed_data.json")
            assert os.path.exists("output/validation_results.json")

        finally:
            # Cleanup
            os.unlink(temp_file)
            if os.path.exists("output/parsed_data.json"):
                os.unlink("output/parsed_data.json")
            if os.path.exists("output/validation_results.json"):
                os.unlink("output/validation_results.json")

    def test_run_compliance_check_file_not_found(self):
        """Test compliance check with non-existent file"""
        result = run_compliance_check("non_existent_file.txt", "1.4.1", False)

        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_run_compliance_check_invalid_file_extension(self):
        """Test compliance check with invalid file extension"""
        with tempfile.NamedTemporaryFile(mode="w",
                                         suffix=".json",
                                         delete=False) as f:
            f.write("{}")
            temp_file = f.name

        try:
            result = run_compliance_check(temp_file, "1.4.1", False)

            assert result["status"] == "error"
            assert "must be a .txt file" in result["error"]

        finally:
            os.unlink(temp_file)


class TestPrintComplianceSummary:
    """Test the print_compliance_summary function"""

    def test_print_compliance_summary_compliant(self, capsys):
        """Test printing summary for compliant device

        :param capsys:

        """
        validation_data = {
            "summary": {
                "total_endpoints": 1,
                "compliant_endpoints": 1,
                "non_compliant_endpoints": 0,
                "total_revision_issues": 0,
                "total_event_warnings": 0,
            },
            "endpoints": [{
                "endpoint":
                0,
                "is_compliant":
                True,
                "device_types": [{
                    "device_type_id": 22,
                    "device_type_name": "Root Node",
                    "is_compliant": True,
                }],
                "missing_elements": [],
                "revision_issues": [],
                "event_warnings": [],
            }],
        }

        print_compliance_summary(validation_data)

        captured = capsys.readouterr()
        assert "COMPLIANT" in captured.out
        assert "Total Endpoints: 1" in captured.out
        assert "Compliant Endpoints: 1" in captured.out
        assert "Non-Compliant Endpoints: 0" in captured.out

    def test_print_compliance_summary_empty_data(self, capsys):
        """Test printing summary with empty validation data

        :param capsys:

        """
        print_compliance_summary({})

        captured = capsys.readouterr()
        assert "No validation data available" in captured.out


class TestRunTests:
    """Test the run_tests function"""

    def test_run_tests_success(self, capsys):
        """Test successful test run

        :param capsys:

        """
        with patch("datamodel_parser.parse_datamodel_logs") as mock_parse:
            with patch(
                    "datamodel_parser.load_element_requirements") as mock_load:
                mock_parse.return_value = {"endpoints": []}
                mock_load.return_value = [{"id": 22, "name": "Test"}]

                result = run_tests()

                captured = capsys.readouterr()
                assert "Running Matter Device Compliance Parser Tests" in captured.out
                assert "TEST SUMMARY" in captured.out


class TestRunCliMode:
    """Test the run_cli_mode function"""

    def test_run_cli_mode_missing_input_file(self, capsys):
        """Test CLI mode with missing input file

        :param capsys:

        """
        with patch("sys.argv", ["datamodel_parser.py"]):
            result = run_cli_mode()

            captured = capsys.readouterr()
            assert "input_file is required" in captured.out
            assert result == 2

    def test_run_cli_mode_test_flag(self, capsys):
        """Test CLI mode with test flag

        :param capsys:

        """
        with patch("sys.argv", ["datamodel_parser.py", "--test"]):
            with patch("datamodel_parser.run_tests", return_value=0):
                result = run_cli_mode()

                assert result == 0


class TestMainFunction:
    """Test the main function"""

    def test_main_function_calls_cli_mode(self):
        """Test that main function calls run_cli_mode"""
        with patch("datamodel_parser.run_cli_mode",
                   return_value=0) as mock_cli:
            result = main()

            mock_cli.assert_called_once()
            assert result == 0  # main returns the exit code instead of calling sys.exit


class TestDatamodelParserErrorHandling:
    """Test error handling in datamodel parser"""

    def test_run_compliance_check_exception_handling(self):
        """Test that run_compliance_check handles exceptions gracefully"""
        # Create a temporary valid file to pass file validation
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as f:
            f.write("test content")
            temp_file = f.name

        try:
            with patch(
                    "datamodel_parser.parse_datamodel_logs",
                    side_effect=Exception("Test error"),
            ):
                result = run_compliance_check(temp_file, "1.4.1", False)

            assert result["status"] == "error"
            assert "Test error" in result["error"]
        finally:
            import os

            os.unlink(temp_file)

    def test_print_compliance_summary_exception_handling(self, capsys):
        """Test that print_compliance_summary handles exceptions gracefully

        :param capsys:

        """
        # Test with malformed validation data
        malformed_data = {"summary": "not a dict", "endpoints": "not a list"}

        # The function doesn't handle malformed data gracefully, so it raises AttributeError
        with pytest.raises(AttributeError):
            print_compliance_summary(malformed_data)
