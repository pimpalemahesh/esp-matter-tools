import json
import os
import shutil
import tempfile
from unittest.mock import Mock
from unittest.mock import patch

import pytest


@pytest.fixture
def sample_log_data():
    """Sample valid log data for testing"""
    return """[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0000 DataVersion: 1
DeviceTypeList: 2 entries
[0]: {
  DeviceType: 22
  Revision: 1
}
[1]: {
  DeviceType: 256
  Revision: 1
}
[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0001 DataVersion: 1
ServerList: 3 entries
[0]: 29
[1]: 40
[2]: 1029
[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0002 DataVersion: 1
ClientList: 1 entries
[0]: 6
[TOO] Endpoint: 0 Cluster: 0x0028 Attribute 0xFFFC DataVersion: 1
FeatureMap: 0x00000000
[TOO] Endpoint: 0 Cluster: 0x0028 Attribute 0xFFFD DataVersion: 1
ClusterRevision: 1
[TOO] Endpoint: 1 Cluster: 0x001D Attribute 0x0000 DataVersion: 1
DeviceTypeList: 1 entries
[0]: {
  DeviceType: 256
  Revision: 1
}"""


@pytest.fixture
def sample_parsed_data():
    """Sample parsed data structure for testing"""
    return {
        "endpoints": [
            {
                "endpoint": 0,
                "clusters": {
                    "0x001D": {
                        "attributes": {
                            "0x0000": {
                                "DeviceTypeList": [
                                    {
                                        "DeviceType": "0x0016",
                                        "Revision": 1
                                    },
                                    {
                                        "DeviceType": "0x0100",
                                        "Revision": 1
                                    },
                                ]
                            },
                            "0x0001": {
                                "ServerList": [
                                    {
                                        "id": "0x001D"
                                    },
                                    {
                                        "id": "0x0028"
                                    },
                                    {
                                        "id": "0x0405"
                                    },
                                ]
                            },
                            "0x0002": {
                                "ClientList": [{
                                    "id": "0x0006"
                                }]
                            },
                        },
                        "events": {},
                        "commands": {},
                        "features": {},
                    },
                    "0x0028": {
                        "attributes": {},
                        "events": {},
                        "commands": {},
                        "features": {
                            "FeatureMap": {
                                "FeatureMap": "0x00000000"
                            },
                            "ClusterRevision": {
                                "ClusterRevision": 1
                            },
                        },
                    },
                },
            },
            {
                "endpoint": 1,
                "clusters": {
                    "0x001D": {
                        "attributes": {
                            "0x0000": {
                                "DeviceTypeList": [{
                                    "DeviceType": "0x0100",
                                    "Revision": 1
                                }]
                            }
                        },
                        "events": {},
                        "commands": {},
                        "features": {},
                    }
                },
            },
        ]
    }


@pytest.fixture
def sample_element_requirements():
    """Sample element requirements for testing"""
    return [
        {
            "id":
            22,
            "name":
            "Root Node",
            "revision":
            1,
            "clusters": [
                {
                    "id":
                    "0x001D",
                    "name":
                    "Descriptor",
                    "type":
                    "server",
                    "revision":
                    1,
                    "attributes": [
                        {
                            "id": "0x0000",
                            "name": "DeviceTypeList"
                        },
                        {
                            "id": "0x0001",
                            "name": "ServerList"
                        },
                        {
                            "id": "0x0002",
                            "name": "ClientList"
                        },
                    ],
                },
                {
                    "id":
                    "0x0028",
                    "name":
                    "Basic Information",
                    "type":
                    "server",
                    "revision":
                    1,
                    "attributes": [
                        {
                            "id": "0x0000",
                            "name": "DataModelRevision"
                        },
                        {
                            "id": "0x0001",
                            "name": "VendorName"
                        },
                    ],
                    "features": [{
                        "id": "0x0001",
                        "name": "TestFeature"
                    }],
                },
            ],
        },
        {
            "id":
            256,
            "name":
            "On/Off Light",
            "revision":
            1,
            "clusters": [
                {
                    "id": "0x001D",
                    "name": "Descriptor",
                    "type": "server",
                    "revision": 1,
                    "attributes": [{
                        "id": "0x0000",
                        "name": "DeviceTypeList"
                    }],
                },
                {
                    "id":
                    "0x0006",
                    "name":
                    "On/Off",
                    "type":
                    "server",
                    "revision":
                    1,
                    "attributes": [{
                        "id": "0x0000",
                        "name": "OnOff"
                    }],
                    "commands": [
                        {
                            "id": "0x0000",
                            "name": "Off"
                        },
                        {
                            "id": "0x0001",
                            "name": "On"
                        },
                    ],
                },
            ],
        },
    ]


@pytest.fixture
def temp_requirements_file(sample_element_requirements):
    """Create a temporary requirements file for testing

    :param sample_element_requirements:

    """
    temp_dir = tempfile.mkdtemp()
    data_dir = os.path.join(temp_dir, "data")
    os.makedirs(data_dir)

    requirements_file = os.path.join(data_dir,
                                     "element_requirements_1.4.1.json")
    with open(requirements_file, "w") as f:
        json.dump(sample_element_requirements, f)

    # Change to temp directory and yield the path
    original_cwd = os.getcwd()
    os.chdir(temp_dir)

    yield requirements_file

    # Cleanup
    os.chdir(original_cwd)
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_logger():
    """Mock logger for testing"""
    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        yield mock_logger


@pytest.fixture
def invalid_log_data():
    """Invalid log data for negative testing"""
    return {
        "empty":
        "",
        "no_too_entries":
        "Some random log data without [TOO] entries",
        "malformed_metadata":
        "[TOO] Invalid metadata format",
        "incomplete_block":
        "[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0000\nDeviceTypeList: 1 entries\n[0]: {",
        "invalid_json_like":
        "[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0000\nInvalid: {broken json",
        "mixed_valid_invalid":
        "[TOO] Endpoint: 0 Cluster: 0x001D Attribute 0x0000\nDeviceTypeList: 1 entries\n[0]: {\n  DeviceType: 22\n[TOO] Invalid line",
    }


@pytest.fixture
def invalid_parsed_data():
    """Invalid parsed data for negative testing"""
    return {
        "empty_dict": {},
        "no_endpoints": {
            "some_key": "some_value"
        },
        "endpoints_not_list": {
            "endpoints": "not a list"
        },
        "malformed_endpoint": {
            "endpoints": [{
                "invalid": "structure"
            }]
        },
        "missing_clusters": {
            "endpoints": [{
                "endpoint": 0
            }]
        },
        "invalid_cluster_structure": {
            "endpoints": [{
                "endpoint": 0,
                "clusters": "not a dict"
            }]
        },
    }


@pytest.fixture
def invalid_requirements():
    """Invalid requirements for negative testing"""
    return {
        "empty_list": [],
        "not_list": {
            "invalid": "structure"
        },
        "invalid_device_type": [{
            "invalid": "device_type"
        }],
        "missing_id": [{
            "name": "Test Device",
            "clusters": []
        }],
        "invalid_cluster": [{
            "id": 22,
            "name": "Test",
            "clusters": [{
                "invalid": "cluster"
            }]
        }],
    }
