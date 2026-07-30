# Copyright 2025 Espressif Systems (Shanghai) PTE LTD
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

from pics_tool.generate.profile import (
    DeviceProfile,
    ProfileError,
    load_profile,
    merge_overrides,
)


def test_defaults_applied():
    p = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": "On/Off Light", "transport": ["wifi_2g"]}
    )
    assert p.role == "commissionee"
    assert p.onboarding == ["qr", "manual_pairing_code"]
    assert p.node_device_types == []
    assert p.ble_commissioning is True
    assert p.power_source == "mains"


def test_ble_default_ethernet_only_is_false():
    p = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": "X", "transport": ["ethernet"]}
    )
    assert p.ble_commissioning is False


def test_ble_explicit_override_respected():
    p = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": "X", "transport": ["ethernet"],
         "ble_commissioning": True}
    )
    assert p.ble_commissioning is True


@pytest.mark.parametrize("bad", [
    {"spec_version": "1.6", "device_type": "X", "transport": ["zigbee"]},
    {"spec_version": "1.6", "device_type": "X", "transport": []},
    {"spec_version": "1.6", "device_type": "X", "transport": ["wifi_2g"], "role": "boss"},
    {"spec_version": "", "device_type": "X", "transport": ["wifi_2g"]},
])
def test_invalid_profiles(bad):
    with pytest.raises(ProfileError):
        DeviceProfile.from_dict(bad)


def test_unknown_keys_go_to_extra():
    p = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": "X", "transport": ["thread"],
         "future_flag": 42}
    )
    assert p.extra == {"future_flag": 42}


def test_merge_overrides_cli_wins_and_none_ignored():
    base = {"spec_version": "1.6", "device_type": "A", "transport": ["wifi_2g"]}
    merged = merge_overrides(base, device_type="B", role=None)
    assert merged["device_type"] == "B"
    assert "role" not in merged


def test_load_profile_from_yaml(tmp_path):
    f = tmp_path / "device-profile.yaml"
    f.write_text(
        "spec_version: '1.6'\ndevice_type: On/Off Light\ntransport: [wifi_2g, thread]\n"
        "role: commissionee\n",
        encoding="utf-8",
    )
    p = load_profile(f, device_type="Dimmable Light")  # CLI override wins
    assert p.device_type == "Dimmable Light"
    assert p.transport == ["wifi_2g", "thread"]


def test_icd_mode_validated_and_defaulted():
    from pics_tool.generate.profile import DeviceProfile, ProfileError
    import pytest as _pytest

    p = DeviceProfile.from_dict({"spec_version": "1.6", "device_type": "X",
                                 "transport": ["thread"], "is_icd": True})
    assert p.icd_mode == "sit"
    with _pytest.raises(ProfileError):
        DeviceProfile.from_dict({"spec_version": "1.6", "device_type": "X",
                                 "transport": ["thread"], "is_icd": True,
                                 "icd_mode": "bogus"})
