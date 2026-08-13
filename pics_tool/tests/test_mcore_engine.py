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
from pics_tool.generate import mcore_engine as me
from pics_tool.generate.profile import DeviceProfile
from pics_tool.generate.template_io import PicsItem


def _profile(**kw):
    base = {
        "spec_version": "1.6",
        "device_type": "X",
        "transport": ["wifi_2g"],
        "role": "commissionee",
    }
    base.update(kw)
    return DeviceProfile.from_dict(base)


def test_synthetic_fixpoint_and_leaves():
    items = [
        PicsItem("MCORE.COM.WIFI_2P4GHZ", [("O", "")]),  # profile-controlled leaf
        PicsItem("MCORE.COM.THR", [("O", "")]),  # profile-controlled leaf
        PicsItem("MCORE.COM.WIFI", [("M", "MCORE.COM.WIFI_2P4GHZ")]),  # derived-M
        PicsItem("MCORE.COM.WIRELESS", [("M", "MCORE.COM.WIFI")]),  # chained derived-M
        PicsItem("MCORE.DD.TXT_KEY_VP", [("O", "")]),  # generic leaf -> on
        PicsItem("MCORE.IDM.C", [("O", "")]),  # denied for commissionee
    ]
    role_profile = {
        "seeds": ["MCORE.ROLE.COMMISSIONEE"],
        "deny": ["MCORE.IDM.C", "MCORE.IDM.C.*"],
    }
    enabled = me._compute(
        items, _profile(transport=["wifi_2g"]), me.NodeFacts(), role_profile
    )

    assert "MCORE.COM.WIFI_2P4GHZ" in enabled  # seeded by transport
    assert "MCORE.COM.WIFI" in enabled  # derived by cond fixpoint
    assert "MCORE.COM.WIRELESS" in enabled  # chained fixpoint
    assert (
        "MCORE.DD.TXT_KEY_VP" not in enabled
    )  # generic leaf: default OFF (no max-options)
    assert "MCORE.COM.THR" not in enabled  # not seeded
    assert "MCORE.IDM.C" not in enabled  # leaf, default OFF


def test_gating_bridge_and_provider():
    items = [
        PicsItem("MCORE.BRIDGE.AllowDeviceRename", [("O", "MCORE.BRIDGE")]),
        PicsItem("MCORE.OTA.Provider", [("O", "")]),
    ]
    role_profile = me.load_role_profile("commissionee")
    # No bridge / provider cluster present -> both off.
    off = me._compute(items, _profile(), me.NodeFacts(), role_profile)
    assert "MCORE.BRIDGE" not in off
    assert "MCORE.OTA.Provider" not in off
    # Bridge/provider present: MCORE.BRIDGE and OTA.Provider are seeded on, but the
    # OPTIONAL bridge sub-flag stays OFF (product choice, not auto-enabled).
    facts = me.NodeFacts(has_bridge=True, has_ota_provider=True)
    on = me._compute(items, _profile(), facts, role_profile)
    assert "MCORE.BRIDGE" in on
    assert "MCORE.OTA.Provider" in on
    assert "MCORE.BRIDGE.AllowDeviceRename" not in on  # optional -> not assumed


def test_node_facts_from_clusters():
    f = me.node_facts_from_clusters({"0x002a", "0x0006"})
    assert f.has_ota_requestor and not f.has_ota_provider and not f.has_bridge
    f2 = me.node_facts_from_clusters({"0x0029", "0x0039"})
    assert f2.has_ota_provider and f2.has_bridge and not f2.has_ota_requestor


def test_integration_base_xml_commissionee_wifi():
    # No OTA/bridge clusters -> OTA and BDX off; transport/role/onboarding on.
    enabled = me.compute_mcore_pics(
        _profile(transport=["wifi_2g"]), "1.6", cluster_ids=set()
    )
    # Input-seeded and cond-derived stay on.
    for code in [
        "MCORE.COM.WIFI_2P4GHZ",
        "MCORE.COM.WIFI",
        "MCORE.COM.WIRELESS",
        "MCORE.COM.BLE",
        "MCORE.ROLE.COMMISSIONEE",
        "MCORE.DD.QR",
        "MCORE.DD.STANDARD_COMM_FLOW",
    ]:
        assert code in enabled, code
    # Optional leaves are default OFF now (no max-options): IDM.S and discovery
    # keys are not assumed; OTA/bridge/PAF/etc. are off without the right input.
    for code in [
        "MCORE.IDM.S",
        "MCORE.DD.TXT_KEY_VP",
        "MCORE.SC.SII_OP_DISCOVERY_KEY",
        "MCORE.DD.PHYSICAL_TAMPERING",
        "MCORE.COM.THR",
        "MCORE.COM.ETH",
        "MCORE.ROLE.COMMISSIONER",
        "MCORE.IDM.C",
        "MCORE.OTA.Requestor",
        "MCORE.OTA.Provider",
        "MCORE.BRIDGE",
        "MCORE.DD.DISCOVERY_PAF",
        "MCORE.COM.PAF",
        "MCORE.DD.CONCATENATED_QR_CODE",
    ]:
        assert code not in enabled, code


def test_ota_and_bdx_derived_from_cluster_ids():
    def mcore(cluster_ids):
        return me.compute_mcore_pics(
            _profile(transport=["wifi_2g"]), "1.6", cluster_ids
        )

    req = mcore({"0x002a"})  # OTA Requestor cluster present
    assert "MCORE.OTA.Requestor" in req and "MCORE.BDX.Receiver" in req
    assert "MCORE.OTA.Provider" not in req and "MCORE.BDX.Sender" not in req
    prov = mcore({"0x0029"})  # OTA Provider cluster present
    assert "MCORE.OTA.Provider" in prov and "MCORE.BDX.Sender" in prov
    assert "MCORE.OTA.Requestor" not in prov
    none = mcore(set())
    assert not any(x.startswith("MCORE.BDX.") for x in none)
    assert "MCORE.OTA.Requestor" not in none


def test_onboarding_multiselect_enables_all():
    prof = DeviceProfile.from_dict(
        {
            "spec_version": "1.6",
            "device_type": "X",
            "transport": ["wifi_2g"],
            "onboarding": ["qr", "manual_pairing_code", "nfc"],
        }
    )
    enabled = me.compute_mcore_pics(prof, "1.6")
    assert {"MCORE.DD.QR", "MCORE.DD.MANUAL_PC", "MCORE.DD.NFC"} <= enabled


def test_integration_ethernet_only_no_ble():
    prof = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": "X", "transport": ["ethernet"]}
    )
    enabled = me.compute_mcore_pics(prof, "1.6")
    assert "MCORE.COM.ETH" in enabled
    assert (
        "MCORE.COM.BLE" not in enabled
    )  # ble_commissioning defaults false for ethernet-only
    assert "MCORE.COM.WIFI" not in enabled
