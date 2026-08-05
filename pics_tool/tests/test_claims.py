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
"""The shared claims layer, and its parity with the web UI's internal split."""

import pytest

loader = pytest.importorskip("esp_matter_datamodel.loader")

from pics_tool.generate import claims
from pics_tool.generate.cluster_engine import active_conditions, load_transport_map
from pics_tool.generate.profile import DeviceProfile
from pics_tool.generate.template_io import known_item_numbers


def _model():
    return loader.load_version("1.6")


def test_feature_seeds_from_codes():
    model = _model()
    # On/Off (0x0006) bit 0 is the Lighting feature.
    seeds = claims.feature_seeds_from_codes(model, ["OO.S.F00"])
    assert "0x0006" in seeds and seeds["0x0006"]  # a non-empty feature code set
    # Unknown prefix / non-feature codes are ignored.
    assert claims.feature_seeds_from_codes(model, ["ZZ.S.F00", "OO.S.A0000"]) == {}


def test_mcore_atoms():
    assert claims.mcore_atoms(["MCORE.DD.NFC", "OO.S.F00", "MCORE.OTA.HTTPS"]) == {
        "MCORE.DD.NFC", "MCORE.OTA.HTTPS"}
    assert claims.mcore_atoms([]) == set()


def test_side_claims_client():
    model = _model()
    profile = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": "On/Off Light", "transport": ["wifi_2g"]})
    conditions = active_conditions(profile, load_transport_map())
    out = claims.side_claims(model, profile, ["OO.C"], conditions, known_item_numbers("1.6"))
    assert "OO.C" in out
    assert "OO.C" in out["OO.C"]  # claiming the client side yields the role code


def test_parity_with_webapp_internal_split():
    """The CLI's shared layer must equal what the web UI computes internally."""
    webapp = pytest.importorskip("pics_tool.webapp")
    model = _model()
    profile = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": "Dimmer Switch", "transport": ["wifi_2g"]})
    codes = ["OO.S.F00", "OO.C", "MCORE.DD.NFC"]
    conditions = active_conditions(profile, load_transport_map())

    assert (claims.feature_seeds_from_codes(model, codes)
            == webapp._feature_seeds_from_codes("1.6", codes))
    assert (claims.side_claims(model, profile, codes, conditions, known_item_numbers("1.6"))
            == webapp._gateway_claims("1.6", profile, codes))
