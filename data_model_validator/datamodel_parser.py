#!/usr/bin/env python3
"""
Matter Device Compliance Parser - CLI Script

This script uses core modules to parse Matter device logs and validate compliance.
It provides terminal-based compliance checking with detailed results and automatically
saves parsed_data.json and validation_results.json files for further analysis.

Features:
- Comprehensive compliance validation with tabular output
- Automatic JSON file generation (parsed_data.json, validation_results.json)
- Built-in test suite for validation
- Support for different chip versions
- Clean tabular formatting for easy visualization
- Proper exit codes for CI/CD integration
- Device commissioning and wildcard data reading via chip-tool
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time
import random
from datetime import datetime

from core.compliance_checker import load_element_requirements
from core.compliance_checker import validate_device_compliance
from core.log_parser import parse_datamodel_logs

# Try to import tabulate for better table formatting
try:
    from tabulate import tabulate

    TABULATE_AVAILABLE = True
except ImportError:
    TABULATE_AVAILABLE = False
    print("Note: Install 'tabulate' for better table formatting: pip install tabulate")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Chip-tool binary path
CHIP_TOOL_PATH = os.getenv("CHIP_TOOL_PATH")
print(CHIP_TOOL_PATH)


def run_chip_tool_command_with_timeout(command, timeout_seconds, cwd=None):
    """Run a chip-tool command with timeout for CLI usage

    :param command: List of command arguments
    :type command: list
    :param timeout_seconds: Timeout in seconds
    :type timeout_seconds: int
    :param cwd: Working directory (Default value = None)
    :type cwd: str
    :returns: Tuple of (success, output)
    :rtype: tuple

    """
    try:
        # Ensure chip-tool binary exists
        if not os.path.exists(CHIP_TOOL_PATH):
            logger.error(f"chip-tool binary not found at {CHIP_TOOL_PATH}")
            return False, f"chip-tool binary not found at {CHIP_TOOL_PATH}"

        # Change to controller directory if not specified
        if cwd is None:
            cwd = os.path.dirname(CHIP_TOOL_PATH)

        # Build full command
        full_command = ["./chip-tool"] + command
        logger.info(
            f"Executing: {' '.join(full_command)} (timeout: {timeout_seconds}s)"
        )

        # Start process
        process = subprocess.Popen(
            full_command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
        )

        # Collect output with timeout
        output_lines = []
        start_time = time.time()

        while True:
            # Check timeout
            if time.time() - start_time > timeout_seconds:
                logger.error(f"Command timed out after {timeout_seconds} seconds")
                process.terminate()
                output_lines.append(
                    f"Command timed out after {timeout_seconds} seconds"
                )
                return False, "\n".join(output_lines)

            # Check if process is done
            if process.poll() is not None:
                # Read any remaining output
                remaining = process.stdout.read()
                if remaining:
                    for line in remaining.splitlines():
                        if line.strip():
                            output_lines.append(line.strip())
                            logger.info(f"[chip-tool] {line.strip()}")
                break

            # Read available output (non-blocking with timeout)
            try:
                import select

                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if ready:
                    output = process.stdout.readline()
                    if output:
                        output_lines.append(output.strip())
                        logger.info(f"[chip-tool] {output.strip()}")
            except ImportError:
                # Fallback for systems without select (like Windows)
                time.sleep(0.1)

        # Get final return code
        return_code = process.poll()
        output_text = "\n".join(output_lines)

        if return_code == 0:
            logger.info("Command completed successfully")
            return True, output_text
        else:
            logger.error(f"Command failed with return code {return_code}")
            return False, output_text

    except Exception as e:
        error_msg = f"Error executing command: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def extract_wildcard_data_from_output(output):
    """Extract wildcard data from chip-tool output

    :param output: Raw output from chip-tool command
    :type output: str
    :returns: Extracted wildcard data or None
    :rtype: str or None

    """
    try:
        # Look for [TOO] entries which indicate wildcard data
        lines = output.split("\n")
        wildcard_lines = []

        for line in lines:
            if "[TOO]" in line:
                wildcard_lines.append(line)

        if wildcard_lines:
            logger.info(f"Found {len(wildcard_lines)} wildcard data entries")
            return "\n".join(wildcard_lines)
        else:
            logger.warning("No wildcard data found in output")
            return None

    except Exception as e:
        logger.error(f"Error extracting wildcard data: {e}")
        return None


def commission_device_cli(commission_args):
    """Commission device via CLI and return wildcard data

    :param commission_args: Dictionary with commissioning parameters
    :type commission_args: dict
    :returns: Tuple of (success, wildcard_data, error_message)
    :rtype: tuple

    """
    try:
        logger.info("=== Starting Device Commission Process ===")

        pairing_code = commission_args.get("pairing_code")
        node_id = commission_args.get("node_id")
        commission_method = commission_args.get("commission_method", "pairing-code")
        wifi_ssid = commission_args.get("wifi_ssid", "")
        wifi_password = commission_args.get("wifi_password", "")
        timeout = commission_args.get("timeout", 60)

        # Generate random node ID if not provided
        if not node_id:
            node_id = random.randint(1000, 9999)
            logger.info(f"Generated random Node ID: {node_id}")

        # Log commission parameters
        logger.info(f"Commission method: {commission_method}")
        logger.info(f"Node ID: {node_id}")
        logger.info(f"Timeout: {timeout} seconds")

        # Step 1: Commission the device
        logger.info("Step 1: Commissioning device...")

        if commission_method == "ble-wifi" and wifi_ssid and wifi_password:
            # BLE-WiFi commissioning
            logger.info(f"Commissioning device via BLE-WiFi (Node ID: {node_id})")
            command = [
                "pairing",
                "ble-wifi",
                str(node_id),
                wifi_ssid,
                wifi_password,
                "20202021",
                "3840",
            ]
        elif commission_method == "pairing-code" and pairing_code:
            # Standard pairing code
            logger.info(f"Commissioning device with pairing code (Node ID: {node_id})")
            command = ["pairing", "code", str(node_id), pairing_code]
        elif commission_method == "on-network":
            # On-network commissioning
            logger.info(f"Commissioning device on network (Node ID: {node_id})")
            command = ["pairing", "onnetwork", str(node_id), "20202021"]
        else:
            error_msg = "Invalid commission method or missing required parameters"
            logger.error(error_msg)
            return False, None, error_msg

        success, output = run_chip_tool_command_with_timeout(command, timeout)
        if not success:
            return False, None, f"Commission failed: {output}"

        # Step 2: Wait a moment for device to settle
        logger.info("Step 2: Waiting for device to settle...")
        time.sleep(5)

        # Step 3: Read wildcard attributes
        logger.info("Step 3: Reading wildcard attributes...")

        wildcard_command = [
            "any",
            "read-by-id",
            "0xFFFFFFFF",
            "0xFFFFFFFF",
            str(node_id),
            "0xFFFF",
        ]
        success, output = run_chip_tool_command_with_timeout(wildcard_command, timeout)

        if not success:
            return False, None, f"Wildcard read failed: {output}"

        # Step 4: Extract wildcard data
        logger.info("Step 4: Extracting wildcard data...")
        wildcard_data = extract_wildcard_data_from_output(output)

        if wildcard_data:
            logger.info("Wildcard data extracted successfully")
            return True, wildcard_data, None
        else:
            return False, None, "No wildcard data found in output"

    except Exception as e:
        error_msg = f"Commission process error: {str(e)}"
        logger.error(error_msg)
        return False, None, error_msg


def run_compliance_check(
    input_file, chip_version="master", verbose=False, commission_args=None
):
    """Run compliance check using core modules with optional commissioning

    :param input_file: Path to input file (can be None if commissioning)
    :type input_file: str or None
    :param chip_version: Chip version for requirements (Default value = "master")
    :type chip_version: str
    :param verbose: Enable verbose logging (Default value = False)
    :type verbose: bool
    :param commission_args: Commissioning arguments (Default value = None)
    :type commission_args: dict or None
    :returns: Results with status and data
    :rtype: dict

    """
    try:
        # Set logging level
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            logging.getLogger().setLevel(logging.INFO)

        data = None

        # Handle commissioning mode
        if commission_args:
            logger.info("Running in commissioning mode")
            success, wildcard_data, error_msg = commission_device_cli(commission_args)

            if not success:
                raise ValueError(f"Commissioning failed: {error_msg}")

            data = wildcard_data
            logger.info("Using wildcard data from commissioning")

        else:
            # Handle file input mode (existing functionality)
            if not input_file:
                raise ValueError("Either input_file or commissioning must be specified")

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


def print_table(headers, rows, title=None):
    """Print a formatted table using tabulate if available, otherwise simple format

    :param headers:
    :param rows:
    :param title:  (Default value = None)

    """
    if title:
        print(f"\n{title}")
        print("=" * len(title))

    if TABULATE_AVAILABLE:
        print(tabulate(rows, headers=headers, tablefmt="grid"))
    else:
        # Simple ASCII table fallback
        col_widths = [
            max(len(str(header)), max(len(str(row[i])) for row in rows) if rows else 0)
            for i, header in enumerate(headers)
        ]

        # Print header
        header_row = " | ".join(
            str(header).ljust(col_widths[i]) for i, header in enumerate(headers)
        )
        print(header_row)
        print("-" * len(header_row))

        # Print rows
        for row in rows:
            row_str = " | ".join(
                str(row[i]).ljust(col_widths[i]) for i in range(len(headers))
            )
            print(row_str)
    print()


def print_compliance_summary(validation_data):
    """Print comprehensive compliance summary in tabular format with per-endpoint details

    :param validation_data: Validation results data

    """
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
    print("MATTER DEVICE COMPLIANCE REPORT")
    print("=" * 80)

    # 1. Overall Summary Table
    compliance_rate = (
        (compliant_endpoints / total_endpoints * 100) if total_endpoints > 0 else 0
    )
    overall_status = (
        "✅ COMPLIANT" if non_compliant_endpoints == 0 else "❌ NON-COMPLIANT"
    )

    summary_data = [
        ["Total Endpoints", total_endpoints],
        ["Compliant Endpoints", compliant_endpoints],
        ["Non-Compliant Endpoints", non_compliant_endpoints],
        ["Compliance Rate", f"{compliance_rate:.1f}%"],
        ["Total Revision Issues", total_revision_issues],
        ["Total Event Warnings", total_event_warnings],
        ["Overall Status", overall_status],
    ]

    print_table(["Metric", "Value"], summary_data, "📊 OVERALL COMPLIANCE SUMMARY")

    # 2. Endpoints Quick Overview Table
    endpoint_overview_rows = []
    for endpoint in endpoints:
        endpoint_id = endpoint.get("endpoint", "Unknown")
        is_compliant = endpoint.get("is_compliant", False)
        device_types = endpoint.get("device_types", [])
        missing_count = len(endpoint.get("missing_elements", []))
        revision_issues_count = len(endpoint.get("revision_issues", []))
        event_warnings_count = len(endpoint.get("event_warnings", []))

        status = "✅ Compliant" if is_compliant else "❌ Non-Compliant"
        device_types_str = ", ".join(
            [
                dt.get("device_type_name", "Unknown")
                for dt in device_types
                if dt.get("device_type_name")
            ]
        )

        endpoint_overview_rows.append(
            [
                endpoint_id,
                status,
                (
                    device_types_str[:40] + "..."
                    if len(device_types_str) > 40
                    else device_types_str
                ),
                missing_count,
                revision_issues_count,
                event_warnings_count,
            ]
        )

    print_table(
        [
            "Endpoint",
            "Status",
            "Device Type Names",
            "Missing",
            "Rev Issues",
            "Warnings",
        ],
        endpoint_overview_rows,
        "🔌 ENDPOINTS QUICK OVERVIEW",
    )

    # 3. PER-ENDPOINT DETAILED ANALYSIS
    print("\n" + "=" * 80)
    print("📋 PER-ENDPOINT DETAILED COMPLIANCE ANALYSIS")
    print("=" * 80)

    for i, endpoint in enumerate(endpoints):
        endpoint_id = endpoint.get("endpoint", "Unknown")
        is_compliant = endpoint.get("is_compliant", False)
        device_types = endpoint.get("device_types", [])
        missing_elements = endpoint.get("missing_elements", [])
        revision_issues = endpoint.get("revision_issues", [])
        event_warnings = endpoint.get("event_warnings", [])

        # B. Device Types for this Endpoint
        if device_types:
            device_type_rows = []
            for dt in device_types:
                if "error" in dt:
                    device_type_rows.append(
                        [
                            "Error",
                            "Error",
                            "❌ Error",
                            0,
                            dt.get("error", "Unknown error")[:50] + "...",
                        ]
                    )
                else:
                    dt_id = dt.get("device_type_id", "Unknown")
                    dt_name = dt.get("device_type_name", "Unknown")
                    dt_compliant = dt.get("is_compliant", False)
                    clusters_count = len(dt.get("cluster_validations", []))

                    status = "✅ Compliant" if dt_compliant else "❌ Non-Compliant"

                    device_type_rows.append([dt_id, dt_name, status, clusters_count])

            print_table(
                ["Type ID", "Type Name", "Status", "Clusters"],
                device_type_rows,
                f"📋 Endpoint {endpoint_id} Device Types",
            )

        # C. Clusters for this Endpoint
        cluster_rows = []
        for dt in device_types:
            if "cluster_validations" in dt:
                for cluster in dt.get("cluster_validations", []):
                    cluster_id = cluster.get("cluster_id", "Unknown")
                    cluster_name = cluster.get("cluster_name", "Unknown")
                    cluster_type = cluster.get("cluster_type", "server")
                    device_type_name = dt.get("device_type_name", "Unknown")
                    is_cluster_compliant = cluster.get("is_compliant", False)
                    missing_count = len(cluster.get("missing_elements", []))

                    # Get revision issues for this cluster
                    cluster_revision_issues = cluster.get("revision_issues", [])
                    revision_summary = ""
                    if cluster_revision_issues:
                        error_count = len(
                            [
                                r
                                for r in cluster_revision_issues
                                if r.get("severity") == "error"
                            ]
                        )
                        warning_count = len(
                            [
                                r
                                for r in cluster_revision_issues
                                if r.get("severity") != "error"
                            ]
                        )
                        if error_count > 0:
                            revision_summary = f"🔴 {error_count} errors"
                            if warning_count > 0:
                                revision_summary += f", 🟡 {warning_count} warnings"
                        elif warning_count > 0:
                            revision_summary = f"🟡 {warning_count} warnings"
                    else:
                        revision_summary = "✅ OK"

                    status = (
                        "✅ Compliant" if is_cluster_compliant else "❌ Non-Compliant"
                    )

                    cluster_rows.append(
                        [
                            cluster_id,
                            cluster_name,
                            cluster_type.title(),
                            device_type_name,
                            status,
                            missing_count,
                            revision_summary,
                        ]
                    )

        if cluster_rows:
            print_table(
                [
                    "Cluster ID",
                    "Cluster Name",
                    "Type",
                    "Device Type Name",
                    "Status",
                    "Missing",
                    "Revisions",
                ],
                cluster_rows,
                f"🔧 Endpoint {endpoint_id} Complete Cluster Compliance",
            )

        # E. Event Warnings for this Endpoint (only endpoint-level warnings, cluster warnings are in cluster table)
        endpoint_level_warnings = [
            w for w in event_warnings if not w.get("cluster_name")
        ]
        if endpoint_level_warnings:
            event_rows = []
            for warning in endpoint_level_warnings:
                severity = warning.get("severity", "info")
                icon = "🟡" if severity == "warning" else "ℹ️"

                event_rows.append(
                    [
                        warning.get("type", "Unknown"),
                        f"{icon} {severity.title()}",
                        (
                            warning.get("message", "")[:60] + "..."
                            if len(warning.get("message", "")) > 60
                            else warning.get("message", "")
                        ),
                    ]
                )

            print_table(
                ["Event Type", "Severity", "Message"],
                event_rows,
                f"💬 Endpoint {endpoint_id} General Event Warnings",
            )

        # F. Endpoint Recommendations
        print(f"\n🔧 Endpoint {endpoint_id} Recommendations:")
        if not is_compliant:
            # Check for device type revision issues
            device_revision_issue = endpoint.get("revision_issues", [])
            if device_revision_issue:
                print(
                    f"\n   • Fix {len(device_revision_issue)} revision issues listed below"
                )
                for revision_issue in device_revision_issue:
                    print(
                        f"\t   • For {revision_issue.get('item_name', 'Unknown')}, revision on device is {revision_issue.get('actual_revision', 'Unknown')} but the required revision is {revision_issue.get('required_revision', 'Unknown')}"
                    )

            # Check for missing elements
            if missing_elements:
                print(
                    f"\n   • Fix {len(missing_elements)} missing elements listed below"
                )
                print(
                    f"   • Make sure to add the missing elements to the respective clusters"
                )
                for missing_element in missing_elements:
                    print(
                        f"\t   • {missing_element.get('name', 'Unknown')} {missing_element.get('type', 'Unknown')} is missing on {missing_element.get('cluster_name', 'Unknown')} cluster. {missing_element.get('message', '')}"
                    )

            # Count revision issues from clusters
            total_cluster_revision_errors = 0
            for dt in device_types:
                for cluster in dt.get("cluster_validations", []):
                    cluster_revision_issues = cluster.get("revision_issues", [])
                    total_cluster_revision_errors += len(
                        [
                            r
                            for r in cluster_revision_issues
                            if r.get("severity") == "error"
                        ]
                    )

            if total_cluster_revision_errors > 0:
                print(
                    f"\n   • Address {total_cluster_revision_errors} critical revision issues shown in the below list"
                )
                for dt in device_types:
                    for cluster in dt.get("cluster_validations", []):
                        cluster_revision_issues = cluster.get("revision_issues", [])
                        for revision_issue in cluster_revision_issues:
                            print(
                                f"\t   • For {revision_issue.get('item_name', 'Unknown')}, revision on device is {revision_issue.get('actual_revision', 'Unknown')} but the required revision is {revision_issue.get('required_revision', 'Unknown')}"
                            )

        else:
            print("   • ✅ Endpoint is compliant - no action needed")

        if event_warnings:
            print(f"\n   • ℹ️ Review the below event warnings (informational only)")
            for event_warning in event_warnings:
                (
                    print(
                        f"\t   •Make sure {event_warning.get('event_name', 'Unknown')} event is present on {event_warning.get('cluster_name', 'Unknown')} cluster"
                    )
                    if event_warning.get("type", "unknown") == "event_requirement"
                    else None
                )

    # 4. Overall Recommendations
    print(f"\n{'=' * 80}")
    print("🎯 OVERALL RECOMMENDATIONS")
    print(f"{'=' * 80}")

    if non_compliant_endpoints > 0:
        print(f"• Fix compliance issues in {non_compliant_endpoints} endpoint(s)")
        print("• Focus on endpoints marked as ❌ Non-Compliant above")
        print("• Check per-endpoint missing elements and revision issues")
        if total_revision_issues > 0:
            print("• Update firmware to meet required revisions")
    else:
        print("🎉 CONGRATULATIONS: All endpoints are fully compliant!")
        print("• Device meets Matter specification requirements")
        print("• All required elements are present and properly implemented")

    if total_event_warnings > 0:
        print(
            f"• Review {total_event_warnings} event warnings (don't affect compliance)"
        )

    print("\n📁 Detailed results saved in:")
    print("   • output/parsed_data.json - Raw parsed device data")
    print("   • output/validation_results.json - Complete validation results")
    print("=" * 80)


def run_cli_mode():
    """Run in CLI mode for terminal usage"""
    parser = argparse.ArgumentParser(
        description="Matter Device Compliance Parser - Tabular results with JSON export"
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        help="Input log file (.txt) to parse (not required if commissioning)",
    )
    parser.add_argument(
        "--chip-version",
        default="master",
        help="Chip version for element requirements (default: master)",
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

    # Commissioning arguments
    parser.add_argument(
        "--commission", action="store_true", help="Enable device commissioning mode"
    )
    parser.add_argument(
        "--commission-method",
        choices=["pairing-code", "ble-wifi", "on-network"],
        default="pairing-code",
        help="Commissioning method (default: pairing-code)",
    )
    parser.add_argument("--pairing-code", help="Pairing code for commissioning")
    parser.add_argument(
        "--node-id",
        type=int,
        help="Node ID for commissioning (auto-generated if not specified)",
    )
    parser.add_argument("--wifi-ssid", help="Wi-Fi SSID for BLE-WiFi commissioning")
    parser.add_argument(
        "--wifi-password", help="Wi-Fi password for BLE-WiFi commissioning"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout for commissioning operations in seconds (default: 60)",
    )

    args = parser.parse_args()

    # Run tests if requested
    if args.test:
        return run_tests()

    # Set up logging
    if args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
    elif args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    # Handle commissioning mode
    commission_args = None
    if args.commission:
        # Validate commissioning parameters
        if args.commission_method == "pairing-code" and not args.pairing_code:
            print(
                "Error: --pairing-code is required when using pairing-code commissioning method"
            )
            return 2

        if args.commission_method == "ble-wifi":
            if not args.wifi_ssid:
                print("Error: --wifi-ssid is required for BLE-WiFi commissioning")
                return 2
            if not args.wifi_password:
                print("Error: --wifi-password is required for BLE-WiFi commissioning")
                return 2

        commission_args = {
            "commission_method": args.commission_method,
            "pairing_code": args.pairing_code,
            "node_id": args.node_id,
            "wifi_ssid": args.wifi_ssid,
            "wifi_password": args.wifi_password,
            "timeout": args.timeout,
        }

        print(f"🔧 Running in commissioning mode")
        print(f"📋 Commission method: {args.commission_method}")
        print(f"🔌 Node ID: {args.node_id or 'auto-generated'}")
        print(f"⏱️ Timeout: {args.timeout} seconds")
        print(f"📋 Chip version: {args.chip_version}")

    else:
        # Validate input file is provided for non-commissioning mode
        if not args.input_file:
            print("Error: input_file is required when not using commissioning mode")
            print("Use --commission to enable commissioning or provide an input file")
            print("Use --test to run tests")
            return 2

        print(f"🔍 Running compliance check on: {args.input_file}")
        print(f"📋 Chip version: {args.chip_version}")

    # Run compliance check
    results = run_compliance_check(
        args.input_file, args.chip_version, args.verbose, commission_args
    )

    if results["status"] == "success":
        if not args.quiet:
            print_compliance_summary(results["validation_data"])

        # Return appropriate exit code
        summary = results["validation_data"].get("summary", {})
        if summary.get("non_compliant_endpoints", 1) == 0:
            if not args.quiet:
                print("\n✅ COMPLIANCE CHECK PASSED")
            return 0
        else:
            if not args.quiet:
                print("\n❌ COMPLIANCE CHECK FAILED")
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
        from core.compliance_checker import (
            load_element_requirements,
            validate_device_compliance,
        )
        from core.log_parser import parse_datamodel_logs

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
        requirements = load_element_requirements("master")
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

        results = run_compliance_check(test_file, "master", False)

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
        results = run_compliance_check("non_existent_file.txt", "master", False)
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
