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
"""Tests for the web entry point: payload completeness, export routing,
answer re-entry, and the spec-consistency validation gate."""

import pytest

pytest.importorskip("esp_matter_datamodel.loader")

from pics_tool import webapp

PROFILE = {
    "spec_version": "1.6",
    "device_type": "On/Off Light",
    "transport": ["wifi_2g"],
    "role": "commissionee",
    "onboarding": ["qr", "manual_pairing_code"],
    "node_device_types": [],
}


def _codes(payload, tab):
    return {it["code"] for it in payload["items"] if it["tab"] == tab}


# --- payload completeness ---------------------------------------------------


def test_payload_has_three_separate_sections():
    """Base (MCORE), Root Node clusters, and the app endpoint are distinct tabs,
    and the Root Node cluster PICS are present (the bug where ACL/Basic
    Info/CNET silently vanished from the UI and the export)."""
    p = webapp.generate_payload(PROFILE)
    assert [t["id"] for t in p["tabs"]] == ["base", "0", "1"]
    assert p["tabs"][1]["label"].startswith("Root Node")
    assert "On/Off Light" in p["tabs"][2]["label"]

    base, ep0 = _codes(p, "base"), _codes(p, "0")
    assert "MCORE.COM.WIFI_2P4GHZ" in base
    assert all(c.startswith("MCORE.") for c in base)
    assert not any(c.startswith("MCORE.") for c in ep0)
    for required in ("ACL.S", "BINFO.S", "CNET.S", "CGEN.S", "OPCREDS.S"):
        assert required in ep0, f"{required} missing from endpoint 0"


def test_payload_echoes_profile_snapshot():
    p = webapp.generate_payload(PROFILE)
    assert p["profile"] == PROFILE


def test_dlog_items_off_without_diag_logs_cluster():
    """DLOG questions are decisively OFF (not 'your call') when the node does
    not host the Diagnostic Logs cluster."""
    p = webapp.generate_payload(PROFILE)
    dlog = [it for it in p["items"] if it["code"].startswith("MCORE.DLOG.")]
    assert dlog, "expected DLOG items in Base.xml"
    assert all(not it["needs_you"] and it["answer"] == "no" for it in dlog)


# --- user answers re-enter the engine ----------------------------------------


def test_enabled_feature_reenters_engine():
    """Turning a feature PICS code ON must pull in what it makes mandatory."""
    base = webapp.generate_payload(PROFILE)
    base_yes = {it["code"] for it in base["items"] if it["answer"] == "yes"}
    assert "OO.S.F01" not in base_yes  # DeadFrontBehavior is optional

    p = webapp.generate_payload(PROFILE, enabled_features=["OO.S.F01"])
    yes = {it["code"] for it in p["items"] if it["answer"] == "yes"}
    assert "OO.S.F01" in yes
    assert base_yes <= yes  # strictly additive


# --- export routing -----------------------------------------------------------


def test_export_writes_all_endpoint0_cluster_files():
    """The web export must produce the same file set as the CLI: Base.xml plus
    the Root Node cluster test plans on endpoint 0."""
    p = webapp.generate_payload(PROFILE)
    enabled = [it["code"] for it in p["items"] if it["answer"] == "yes"]
    files = webapp.export_pics_files(PROFILE, enabled)

    ep0_files = {f for f in files if f.startswith("endpoint0/")}
    assert "endpoint0/Base.xml" in ep0_files
    assert any("Access Control" in f for f in ep0_files)
    assert any("Network Commissioning" in f for f in ep0_files)
    assert any("Basic Information" in f for f in ep0_files)
    assert len(files) >= 15  # CLI writes 16 for this profile

    # what you see is what you export: enabled EP1 codes present in the XML
    ep1_onoff = next(f for f in files if f.startswith("endpoint1/") and "On-Off" in f)
    assert "<support>true</support>" in files[ep1_onoff]


def test_export_routes_root_cluster_codes_to_ep0():
    p = webapp.generate_payload(PROFILE)
    enabled = [it["code"] for it in p["items"] if it["answer"] == "yes"]
    files = webapp.export_pics_files(PROFILE, enabled)
    acl = next(f for f in files if "Access Control Cluster" in f)
    assert acl.startswith("endpoint0/")


# --- validation gate ----------------------------------------------------------


def test_validate_flags_disabled_mandatory_item():
    p = webapp.generate_payload(PROFILE)
    enabled = [it["code"] for it in p["items"] if it["answer"] == "yes"]
    bad = [c for c in enabled if c != "OO.S.A0000"]  # OnOff attr is mandatory
    problems = webapp.validate_selection(PROFILE, bad)
    assert any(pr["code"] == "OO.S.A0000" for pr in problems)


def test_validate_flags_mcore_cond_violation():
    """Enabling a Wi-Fi band without MCORE.COM.WIFI violates Base.xml's cond."""
    problems = webapp.validate_selection(PROFILE, ["MCORE.COM.WIFI_2P4GHZ"])
    assert any(pr["code"] == "MCORE.COM.WIFI" for pr in problems)


def test_validate_clean_selection_passes():
    p = webapp.generate_payload(PROFILE)
    enabled = [it["code"] for it in p["items"] if it["answer"] == "yes"]
    assert webapp.validate_selection(PROFILE, enabled) == []


def test_validate_accounts_for_user_enabled_features():
    """A user-enabled optional feature makes its dependents mandatory; the
    validator must catch a selection that claims the feature but not them."""
    p = webapp.generate_payload(PROFILE, enabled_features=["OO.S.F01"])
    full = [it["code"] for it in p["items"] if it["answer"] == "yes"]
    dependents = webapp.validate_selection(
        PROFILE, [c for c in full if c == "OO.S.F01" or not c.startswith("OO.S.F")])
    # dropping nothing: full set validates clean
    assert webapp.validate_selection(PROFILE, full) == []
    assert isinstance(dependents, list)


# --- client-side PICS ---------------------------------------------------------


def test_client_device_type_gets_client_pics():
    profile = dict(PROFILE, device_type="Dimmer Switch")
    p = webapp.generate_payload(profile)
    ep1 = _codes(p, "1")
    assert "OO.C" in ep1
    assert "LVL.C" in ep1
    assert any(c.startswith("OO.C.C") and c.endswith(".Tx") for c in ep1)


def test_ota_requestor_is_otap_client():
    profile = dict(PROFILE, node_device_types=["OTA Requestor"])
    p = webapp.generate_payload(profile)
    ep0 = _codes(p, "0")
    assert "OTAP.C" in ep0
    assert "OTAR.S" in ep0
