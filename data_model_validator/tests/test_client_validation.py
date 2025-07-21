#!/usr/bin/env python3
import json
import logging
import os
import sys

from core.compliance_checker import find_client_cluster
from core.compliance_checker import validate_cluster

# Add current directory to sys.path to ensure core modules can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def test_client_cluster_validation():
    """ """
    # Test data structure based on user's parsed_data.json
    test_endpoint_clusters = {
        "0x0002": {
            "attributes": {
                "ClientList": [{
                    "id": "0x0029",
                    "name": "ota_software_update_provider"
                }]
            }
        }
    }

    # Test requirement for OTA client cluster
    required_cluster = {
        "name": "ota_software_update_provider",
        "id": "0x0029",
        "type": "client",
    }

    print("=" * 60)
    print("Testing Client Cluster Validation")
    print("=" * 60)

    print(f"Test data: {json.dumps(test_endpoint_clusters, indent=2)}")
    print(f"Required cluster: {json.dumps(required_cluster, indent=2)}")

    print("\n" + "-" * 40)
    print("Step 1: Testing find_client_cluster function")
    print("-" * 40)

    found = find_client_cluster(test_endpoint_clusters, "0x0029")
    print(f"Result: Client cluster 0x0029 found = {found}")

    print("\n" + "-" * 40)
    print("Step 2: Testing full validate_cluster function")
    print("-" * 40)

    result = validate_cluster(test_endpoint_clusters, required_cluster)
    print(f"Validation result: {json.dumps(result, indent=2)}")

    print("\n" + "=" * 60)
    if result["is_compliant"]:
        print("✅ SUCCESS: Client cluster validation PASSED!")
    else:
        print("❌ FAILED: Client cluster validation failed")
        print(f"Missing elements: {result['missing_elements']}")
    print("=" * 60)


if __name__ == "__main__":
    test_client_cluster_validation()
