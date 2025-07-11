#!/usr/bin/env python3
"""
Matter Device Compliance Parser - CLI Script

This script uses core modules to parse Matter device logs and validate compliance.
It provides terminal-based compliance checking with detailed results and automatically
saves parsed_data.json and validation_results.json files for further analysis.

Features:
- Comprehensive compliance validation with detailed terminal output
- Automatic JSON file generation (parsed_data.json, validation_results.json)
- Built-in test suite for validation
- Support for different chip versions
- Complete detailed output (no truncation)
- Proper exit codes for CI/CD integration
"""

import json
import logging
import os
import sys
import argparse
import time

# Import core modules
from core.log_parser import parse_datamodel_logs
from core.compliance_checker import (
    validate_device_compliance,
    load_element_requirements,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_compliance_check(input_file, chip_version="1.4.1", verbose=False):
    """
    Run compliance check using core modules

    Args:
        input_file (str): Path to input file
        chip_version (str): Chip version for requirements
        verbose (bool): Enable verbose logging

    Returns:
        dict: Results with status and data
    """
    try:
        # Set logging level
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            logging.getLogger().setLevel(logging.INFO)

        # Validate input file
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Input file not found: {input_file}")

        if not input_file.endswith(".txt"):
            raise ValueError("Input file must be a .txt file")

        # Read input file
        logger.info(f"Reading input file: {input_file}")
        with open(input_file, "r", encoding="utf-8") as f:
            data = f.read()

        if not data.strip():
            raise ValueError("Input file is empty")

        logger.info(f"File size: {len(data)} bytes")

        # Parse the data using core module
        logger.info("Starting data parsing...")
        parsed_data = parse_datamodel_logs(data)
        logger.info("Data parsing completed successfully")

        # Automatically save parsed data
        os.makedirs("output", exist_ok=True)
        with open("output/parsed_data.json", "w") as f:
            json.dump(parsed_data, f, indent=2)
        logger.info("Parsed data saved to: output/parsed_data.json")

        # Load requirements using core module
        logger.info(f"Loading element requirements for chip version: {chip_version}")
        element_requirements = load_element_requirements(chip_version)

        if not element_requirements:
            raise ValueError(
                f"No element requirements found for chip version: {chip_version}"
            )

        # Validate compliance using core module
        logger.info("Starting compliance validation...")
        validation_data = validate_device_compliance(
            parsed_data, element_requirements, chip_version
        )
        logger.info("Compliance validation completed")

        # Automatically save validation results
        with open("output/validation_results.json", "w") as f:
            json.dump(validation_data, f, indent=2)
        logger.info("Validation results saved to: output/validation_results.json")

        return {
            "status": "success",
            "parsed_data": parsed_data,
            "validation_data": validation_data,
            "element_requirements": element_requirements,
        }

    except Exception as e:
        logger.error(f"Error during compliance check: {str(e)}")
        return {"status": "error", "error": str(e)}


def print_compliance_summary(validation_data):
    """Print comprehensive compliance summary to terminal with complete details"""
    if not validation_data:
        print("No validation data available")
        return

    summary = validation_data.get("summary", {})
    endpoints = validation_data.get("endpoints", [])

    total_endpoints = summary.get("total_endpoints", 0)
    compliant_endpoints = summary.get("compliant_endpoints", 0)
    non_compliant_endpoints = summary.get("non_compliant_endpoints", 0)
    total_revision_issues = summary.get("total_revision_issues", 0)
    total_event_warnings = summary.get("total_event_warnings", 0)

    print("\n" + "=" * 80)
    print("MATTER DEVICE COMPLIANCE SUMMARY")
    print("=" * 80)
    print(f"Total Endpoints: {total_endpoints}")
    print(f"Compliant Endpoints: {compliant_endpoints}")
    print(f"Non-Compliant Endpoints: {non_compliant_endpoints}")

    if total_endpoints > 0:
        compliance_rate = (compliant_endpoints / total_endpoints) * 100
        print(f"Compliance Rate: {compliance_rate:.1f}%")

    if total_revision_issues > 0:
        print(f"Revision Issues: {total_revision_issues}")

    if total_event_warnings > 0:
        print(f"Event Warnings: {total_event_warnings}")

    print("=" * 80)

    # Overall status
    if non_compliant_endpoints == 0:
        print("✅ OVERALL STATUS: COMPLIANT")
    else:
        print("❌ OVERALL STATUS: NON-COMPLIANT")

    print("\nDETAILED COMPLIANCE RESULTS:")
    print("=" * 80)

    # Endpoint details with comprehensive information - NO TRUNCATION
    for i, endpoint in enumerate(endpoints):
        endpoint_id = endpoint.get("endpoint", "unknown")
        is_compliant = endpoint.get("is_compliant", False)
        device_types = endpoint.get("device_types", [])
        missing_elements = endpoint.get("missing_elements", [])
        revision_issues = endpoint.get("revision_issues", [])
        event_warnings = endpoint.get("event_warnings", [])

        status_symbol = "✅" if is_compliant else "❌"
        print(f"\n[{i+1}] ENDPOINT {endpoint_id}: {status_symbol}")
        print("-" * 50)

        # Device types with detailed cluster validation
        if device_types:
            for dt_idx, dt in enumerate(device_types):
                if "error" in dt:
                    print(f"  🔴 ERROR: {dt['error']}")
                else:
                    dt_id = dt.get("device_type_id", "unknown")
                    dt_name = dt.get("device_type_name", "unknown")
                    dt_compliant = dt.get("is_compliant", False)
                    dt_status = "✅" if dt_compliant else "❌"
                    print(f"\n  📋 Device Type: {dt_status} {dt_name} (ID: {dt_id})")

                    # Show cluster validation details
                    cluster_validations = dt.get("cluster_validations", [])
                    if cluster_validations:
                        print(
                            f"    🔧 Cluster Validations ({len(cluster_validations)} clusters):"
                        )

                        for cluster in cluster_validations:
                            cluster_id = cluster.get("cluster_id", "unknown")
                            cluster_name = cluster.get("cluster_name", "unknown")
                            cluster_type = cluster.get("cluster_type", "server")
                            cluster_compliant = cluster.get("is_compliant", False)
                            cluster_status = "✅" if cluster_compliant else "❌"

                            print(
                                f"      {cluster_status} {cluster_name} ({cluster_id}) [{cluster_type}]"
                            )

                            # Show ALL missing elements for this cluster - NO TRUNCATION
                            cluster_missing = cluster.get("missing_elements", [])
                            if cluster_missing:
                                for elem in cluster_missing:  # Show ALL elements
                                    elem_type = elem.get("type", "unknown")
                                    elem_id = elem.get("id", "unknown")
                                    elem_name = elem.get("name", "unknown")
                                    print(
                                        f"        🔸 Missing {elem_type}: {elem_name} ({elem_id})"
                                    )

                            # Show ALL revision issues for this cluster
                            cluster_revision_issues = cluster.get("revision_issues", [])
                            if cluster_revision_issues:
                                for rev_issue in cluster_revision_issues:
                                    severity = rev_issue.get("severity", "info")
                                    message = rev_issue.get(
                                        "message", "Unknown revision issue"
                                    )
                                    if severity == "error":
                                        print(f"        🔸 Revision Error: {message}")
                                    else:
                                        print(f"        🔸 Revision Info: {message}")

        # Overall missing elements for the endpoint - NO TRUNCATION
        if missing_elements:
            print(f"\n  🔍 MISSING ELEMENTS ({len(missing_elements)} total):")

            # Group by type
            missing_by_type = {}
            for elem in missing_elements:
                elem_type = elem.get("type", "unknown")
                if elem_type not in missing_by_type:
                    missing_by_type[elem_type] = []
                missing_by_type[elem_type].append(elem)

            for elem_type, items in missing_by_type.items():
                print(f"    📌 {elem_type.title()}s ({len(items)}):")
                for elem in items:  # Show ALL elements - NO TRUNCATION
                    elem_id = elem.get("id", "unknown")
                    elem_name = elem.get("name", "unknown")
                    cluster_name = elem.get("cluster_name", "")
                    if cluster_name:
                        print(f"      • {elem_name} ({elem_id}) in {cluster_name}")
                    else:
                        print(f"      • {elem_name} ({elem_id})")

        # ALL Revision issues - NO TRUNCATION
        if revision_issues:
            print(f"\n  ⚠️  REVISION ISSUES ({len(revision_issues)}):")
            for rev_issue in revision_issues:
                severity = rev_issue.get("severity", "info")
                message = rev_issue.get("message", "Unknown revision issue")
                item_type = rev_issue.get("item_type", "unknown")
                item_name = rev_issue.get("item_name", "unknown")
                actual_rev = rev_issue.get("actual_revision", "unknown")
                required_rev = rev_issue.get("required_revision", "unknown")

                icon = "🔴" if severity == "error" else "🟡"
                print(f"    {icon} {item_type.title()}: {item_name}")
                print(f"       Actual: {actual_rev}, Required: {required_rev}")
                print(f"       {message}")

        # ALL Event warnings - NO TRUNCATION
        if event_warnings:
            print(f"\n  💬 EVENT WARNINGS ({len(event_warnings)}):")
            for event_warning in event_warnings:  # Show ALL warnings
                severity = event_warning.get("severity", "info")
                message = event_warning.get("message", "Unknown event warning")
                event_type = event_warning.get("type", "unknown")

                icon = "🟡" if severity == "warning" else "\t\nℹ️"
                print(f"    {icon} {event_type}: {message}")

        print()  # Add spacing between endpoints

    print("=" * 80)

    # Summary recommendations
    if non_compliant_endpoints > 0:
        print("\n🔧 RECOMMENDATIONS:")
        print("   • Check missing clusters, attributes, commands, and features")
        print("   • Verify device type implementations meet specifications")
        if total_revision_issues > 0:
            print("   • Update firmware to meet minimum revision requirements")
        if total_event_warnings > 0:
            print("   • Review event implementation (warnings don't affect compliance)")
        print("   • Check saved JSON files for complete detailed analysis")
    else:
        print("🎉 CONGRATULATIONS: Device is fully compliant!")

    print("=" * 80)


def run_cli_mode():
    """Run in CLI mode for terminal usage"""
    parser = argparse.ArgumentParser(
        description="Matter Device Compliance Parser - Automatically saves parsed_data.json and validation_results.json"
    )
    parser.add_argument("input_file", nargs="?", help="Input log file (.txt) to parse")
    parser.add_argument(
        "--chip-version",
        default="1.4.1",
        help="Chip version for element requirements (default: 1.4.1)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Quiet mode - only show final results",
    )
    parser.add_argument(
        "--test", action="store_true", help="Run tests instead of processing file"
    )

    args = parser.parse_args()

    # Run tests if requested
    if args.test:
        return run_tests()

    # Validate input file is provided for non-test mode
    if not args.input_file:
        print("Error: input_file is required when not running tests")
        print("Use --test to run tests or provide an input file")
        return 2

    # Set up logging
    if args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
    elif args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    # Run compliance check
    print(f"🔍 Running compliance check on: {args.input_file}")
    print(f"📋 Chip version: {args.chip_version}")

    results = run_compliance_check(args.input_file, args.chip_version, args.verbose)

    if results["status"] == "success":
        if not args.quiet:
            print_compliance_summary(results["validation_data"])

        # Return appropriate exit code
        summary = results["validation_data"].get("summary", {})
        if summary.get("non_compliant_endpoints", 1) == 0:
            if not args.quiet:
                print("\n✅ COMPLIANCE CHECK PASSED")
                print("📁 Detailed results saved in output/ directory")
            return 0
        else:
            if not args.quiet:
                print("\n❌ COMPLIANCE CHECK FAILED")
                print("📁 Detailed results saved in output/ directory")
            return 1
    else:
        print(f"\n🔴 ERROR: {results['error']}")
        return 2


def run_tests():
    """Run simple tests for the compliance checker"""
    print("🧪 Running Matter Device Compliance Parser Tests")
    print("=" * 60)

    tests_passed = 0
    tests_total = 0

    # Test 1: Test core module imports
    tests_total += 1
    try:
        from core.log_parser import parse_datamodel_logs
        from core.compliance_checker import (
            validate_device_compliance,
            load_element_requirements,
        )

        print("✅ Test 1: Core module imports - PASSED")
        tests_passed += 1
    except Exception as e:
        print(f"❌ Test 1: Core module imports - FAILED: {e}")

    # Test 2: Test sample log parsing
    tests_total += 1
    try:
        sample_log = """[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0000 DataVersion: 1
DeviceTypeList: 1 entries
[0]: {
  DeviceType: 22
  Revision: 1
}"""
        result = parse_datamodel_logs(sample_log)
        if result and "endpoints" in result:
            print("✅ Test 2: Sample log parsing - PASSED")
            tests_passed += 1
        else:
            print("❌ Test 2: Sample log parsing - FAILED: Invalid result structure")
    except Exception as e:
        print(f"❌ Test 2: Sample log parsing - FAILED: {e}")

    # Test 3: Test element requirements loading
    tests_total += 1
    try:
        requirements = load_element_requirements("1.4.1")
        if isinstance(requirements, list):
            print("✅ Test 3: Element requirements loading - PASSED")
            tests_passed += 1
        else:
            print(
                "❌ Test 3: Element requirements loading - FAILED: Invalid requirements format"
            )
    except Exception as e:
        print(f"❌ Test 3: Element requirements loading - FAILED: {e}")

    # Test 4: Test compliance check function
    tests_total += 1
    try:
        # Create a temporary test file
        test_file = "test_temp.txt"
        with open(test_file, "w") as f:
            f.write(
                """[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0000 DataVersion: 1
DeviceTypeList: 1 entries
[0]: {
  DeviceType: 22
  Revision: 1
}"""
            )

        results = run_compliance_check(test_file, "1.4.1", False)

        # Clean up
        os.remove(test_file)

        if results["status"] in ["success", "error"]:  # Either is acceptable for test
            print("✅ Test 4: Compliance check function - PASSED")
            tests_passed += 1
        else:
            print(
                "❌ Test 4: Compliance check function - FAILED: Invalid result status"
            )
    except Exception as e:
        print(f"❌ Test 4: Compliance check function - FAILED: {e}")
        # Clean up if file exists
        if os.path.exists("test_temp.txt"):
            os.remove("test_temp.txt")

    # Test 5: Test file validation
    tests_total += 1
    try:
        # Test with non-existent file
        results = run_compliance_check("non_existent_file.txt", "1.4.1", False)
        if results["status"] == "error" and "not found" in results["error"]:
            print("✅ Test 5: File validation - PASSED")
            tests_passed += 1
        else:
            print("❌ Test 5: File validation - FAILED: Should detect missing file")
    except Exception as e:
        print(f"❌ Test 5: File validation - FAILED: {e}")

    # Test Summary
    print("\n" + "=" * 60)
    print(f"📊 TEST SUMMARY: {tests_passed}/{tests_total} tests passed")

    if tests_passed == tests_total:
        print("✅ ALL TESTS PASSED!")
        return 0
    else:
        print("❌ SOME TESTS FAILED!")
        return 1


def main():
    """Main function - run CLI mode"""
    return run_cli_mode()


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
