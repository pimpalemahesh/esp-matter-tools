# Copyright 2026 Espressif Systems (Shanghai) PTE LTD
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
import pytest

from esp_matter_datamodel import validation
from esp_matter_datamodel.model.elements import DataModel

EXAMPLE = {
    "schema_version": "1.0.0",
    "spec_version": "1.6",
    "provenance": {"spec_sha": "deadbeef", "generated_from": "data_model/1.6"},
    "clusters": {
        "0x0006": {
            "id": "0x0006",
            "name": "On/Off",
            "pics": "OO",
            "revision": 6,
            "features": {
                "0": {
                    "bit": 0,
                    "mask": 1,
                    "code": "LT",
                    "name": "Lighting",
                    "conformance": {"type": "optional"},
                },
                "2": {
                    "bit": 2,
                    "mask": 4,
                    "code": "OFFONLY",
                    "name": "OffOnly",
                    "conformance": {"type": "optional"},
                },
            },
            "attributes": {
                "0x0000": {
                    "id": "0x0000",
                    "name": "OnOff",
                    "conformance": {"type": "mandatory"},
                },
                "0x4000": {
                    "id": "0x4000",
                    "name": "GlobalSceneControl",
                    "conformance": {
                        "type": "mandatory",
                        "condition": {"op": "feature", "code": "LT", "bit": 0},
                    },
                },
            },
            "accepted_commands": {
                "0x00": {
                    "id": "0x00",
                    "name": "Off",
                    "conformance": {"type": "mandatory"},
                },
                "0x01": {
                    "id": "0x01",
                    "name": "On",
                    "conformance": {
                        "type": "mandatory",
                        "condition": {
                            "op": "not",
                            "arg": {"op": "feature", "code": "OFFONLY", "bit": 2},
                        },
                    },
                },
            },
            "generated_commands": {},
            "events": {},
        }
    },
    "device_types": {
        "0x0100": {
            "id": "0x0100",
            "name": "On/Off Light",
            "revision": 3,
            "server_clusters": {
                "0x0006": {
                    "id": "0x0006",
                    "name": "On/Off",
                    "conformance": {"type": "mandatory"},
                    "feature_overrides": {"0": {"conformance": {"type": "mandatory"}}},
                    "attribute_overrides": {},
                    "command_overrides": {},
                },
                "0x0008": {
                    "id": "0x0008",
                    "name": "Level Control",
                    "conformance": {"type": "optional"},
                    "feature_overrides": {},
                    "attribute_overrides": {},
                    "command_overrides": {},
                },
            },
            "client_clusters": {},
        }
    },
}


def test_example_validates_against_schema():
    validation.validate(EXAMPLE)


def test_datamodel_round_trip():
    model = DataModel.from_json(EXAMPLE)
    assert model.to_json() == EXAMPLE


def test_device_type_lookup_case_insensitive():
    model = DataModel.from_json(EXAMPLE)
    dt = model.device_type_by_name("on/off light")
    assert dt is not None and dt.id == "0x0100"


def test_invalid_instance_rejected():
    bad = {"schema_version": "1.0.0", "spec_version": "1.6", "clusters": {}}
    with pytest.raises(validation.SchemaValidationError):
        validation.validate(bad)  # missing device_types
