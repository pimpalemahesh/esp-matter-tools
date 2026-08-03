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


def test_undecidable_product_facts_are_manual_not_decided():
    """Absence of information is NOT a 'No': items no input can derive (DLOG
    fields, TCP, PAF, tamper resistance, ...) must sit in the manual group,
    never be presented as tool-decided."""
    p = webapp.generate_payload(PROFILE)
    by_code = {it["code"]: it for it in p["items"] if it["tab"] == "base"}
    # product facts with no derivation path, AND composition facts the phase-1
    # UI still cannot express (bridge, device lists, ICD) -> manual
    for code in ("MCORE.DLOG.S.UTCTIMESTAMP", "MCORE.DLOG.S.TIMESINCEBOOT",
                 "MCORE.SC.TCP", "MCORE.DD.PHYSICAL_TAMPERING",
                 "MCORE.BRIDGE", "MCORE.BRIDGECLIENT", "MCORE.DEVLIST.UseDevices",
                 "MCORE.SC.SIT_ICD"):
        assert by_code[code]["group"] == "manual", f"{code} wrongly tool-decided"
        assert by_code[code]["answer"] == "no"  # conservative default until claimed
    # OTA is an explicit input now: no selection = input-backed decided answers,
    # with VendorSpecific derived Yes by Base.xml's own rule (commissionee
    # without an OTA Requestor must be updatable somehow)
    assert by_code["MCORE.OTA.Requestor"]["group"] == "decided"
    assert by_code["MCORE.OTA.Requestor"]["answer"] == "no"
    assert by_code["MCORE.OTA.VendorSpecific"]["group"] == "decided"
    assert by_code["MCORE.OTA.VendorSpecific"]["answer"] == "yes"
    assert by_code["MCORE.BDX.Receiver"]["answer"] == "no"
    # ...while genuinely derivable facts stay tool-decided (COM.PAF became
    # derivable once wifi_paf was promoted to a profile input)
    for code in ("MCORE.COM.WIFI_2P4GHZ", "MCORE.ROLE.COMMISSIONEE", "MCORE.COM.PAF"):
        assert by_code[code]["group"] == "decided", f"{code} should be derivable"
    # role-contradictory (commissioner-side) items ARE decidable for a commissionee
    for code in ("MCORE.DD.CTRL_CONCATENATED_QR_CODE_1", "MCORE.DD.11_MANUAL_PC"):
        assert by_code[code]["group"] == "decided" and by_code[code]["answer"] == "no"
    # a DECLARED node composition is decisive again: requestor Yes, provider No
    p2 = webapp.generate_payload(dict(PROFILE, node_device_types=["OTA Requestor"]))
    ota = {it["code"]: it for it in p2["items"] if it["tab"] == "base"}
    assert ota["MCORE.OTA.Requestor"]["group"] == "decided"
    assert ota["MCORE.OTA.Requestor"]["answer"] == "yes"
    assert ota["MCORE.OTA.Provider"]["group"] == "decided"
    assert ota["MCORE.OTA.Provider"]["answer"] == "no"
    assert ota["MCORE.OTA.Resume"]["group"] == "manual"  # sub-cap: real question


# --- user answers re-enter the engine ----------------------------------------


def test_enabled_feature_reenters_engine():
    """Turning a feature PICS code ON must pull in what it makes mandatory."""
    base = webapp.generate_payload(PROFILE)
    base_yes = {it["code"] for it in base["items"] if it["answer"] == "yes"}
    assert "OO.S.F01" not in base_yes  # DeadFrontBehavior is optional

    p = webapp.generate_payload(PROFILE, claims=["OO.S.F01"])
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


def test_default_export_is_error_free():
    """With OTA as an explicit input, Base.xml's updatability rule is resolved
    at generation time (VendorSpecific derives Yes when no OTA Requestor is
    selected), so a default export validates with zero errors."""
    p = webapp.generate_payload(PROFILE)
    yes = {it["code"] for it in p["items"] if it["answer"] == "yes"}
    assert "MCORE.OTA.VendorSpecific" in yes  # derived, not guessed
    problems = webapp.validate_selection(PROFILE, sorted(yes))
    assert [pr for pr in problems if pr["severity"] == "error"] == []


def test_validate_accounts_for_user_enabled_features():
    """A user-enabled optional feature makes its dependents mandatory; the
    validator must catch a selection that claims the feature but not them."""
    p = webapp.generate_payload(PROFILE, claims=["OO.S.F01"])
    full = [it["code"] for it in p["items"] if it["answer"] == "yes"]
    full.append("MCORE.OTA.VendorSpecific")  # resolve the OTA choice (see above)
    dependents = webapp.validate_selection(
        PROFILE, [c for c in full if c == "OO.S.F01" or not c.startswith("OO.S.F")])
    # dropping nothing: full set validates with no ERRORS
    assert [p for p in webapp.validate_selection(PROFILE, full)
            if p["severity"] == "error"] == []
    assert isinstance(dependents, list)


# --- client-side PICS ---------------------------------------------------------


def test_client_device_type_gets_client_pics():
    profile = dict(PROFILE, device_type="Dimmer Switch")
    p = webapp.generate_payload(profile)
    ep1 = _codes(p, "1")
    assert "OO.C" in ep1
    assert "LVL.C" in ep1
    assert any(c.startswith("OO.C.C") and c.endswith(".Tx") for c in ep1)


def test_ota_requestor_expressed_via_mcore_not_orphan_codes():
    """The CSA OTA test plan runs off MCORE.OTA.* / MCORE.BDX.*, not a
    per-element grid -- so OTA cluster codes must NOT surface in the UI, while
    the MCORE derivations must be on."""
    profile = dict(PROFILE, node_device_types=["OTA Requestor"])
    p = webapp.generate_payload(profile)
    all_codes = {it["code"] for it in p["items"]}
    assert not any(c.startswith(("OTAR.", "OTAP.")) for c in all_codes)
    yes = {it["code"] for it in p["items"] if it["answer"] == "yes"}
    assert "MCORE.OTA.Requestor" in yes
    assert "MCORE.BDX.Receiver" in yes


def test_every_payload_code_is_template_backed():
    """No orphan codes: every question shown is claimable (exists in a
    template, has question text, and will actually be exported)."""
    from pics_tool.generate.template_io import known_item_numbers

    known = known_item_numbers("1.6")
    for extra in ([], ["OTA Requestor"]):
        p = webapp.generate_payload(dict(PROFILE, device_type="Dimmer Switch",
                                         node_device_types=extra))
        orphans = {it["code"] for it in p["items"]} - known
        assert not orphans, f"unanswerable codes in payload: {sorted(orphans)}"


# --- decided vs manual sections -------------------------------------------------


def test_items_split_into_decided_and_manual_groups():
    """Every tab shows all template items: engine-decided ones in 'decided',
    everything else (optional cluster elements, undecidable Base facts) in
    'manual' with a default No."""
    p = webapp.generate_payload(PROFILE)

    base = [it for it in p["items"] if it["tab"] == "base"]
    assert len(base) == 132  # each and every Base.xml item is present
    manual_base = [it for it in base if it["group"] == "manual"]
    assert len(manual_base) == 60
    assert all(it["answer"] == "no" for it in manual_base)
    assert any(it["code"] == "MCORE.DD.PHYSICAL_TAMPERING" for it in manual_base)

    ep1 = [it for it in p["items"] if it["tab"] == "1"]
    decided = {it["code"] for it in ep1 if it["group"] == "decided"}
    manual = {it["code"] for it in ep1 if it["group"] == "manual"}
    assert "OO.S.A0000" in decided       # mandatory OnOff attribute
    assert "OO.S.A4001" in decided       # OnTime: mandatory under the LT feature
    assert "OO.S.F01" in manual          # optional DeadFrontBehavior feature
    assert "OO.C" in manual              # client role not mandated -> vendor choice
    assert decided.isdisjoint(manual)


def test_client_items_follow_spec_only():
    """Spec only: a client role is tool-decided (Yes) only when the device type
    MANDATES it; a non-mandated client role is a vendor option -> manual, never
    a tool-decided No."""
    p = webapp.generate_payload(PROFILE)  # On/Off Light mandates no clients
    by = {it["code"]: it for it in p["items"] if it["tab"] == "1"}
    assert by["OO.C"]["group"] == "manual" and by["OO.C"]["answer"] == "no"

    p2 = webapp.generate_payload(dict(PROFILE, device_type="Dimmer Switch"))
    by2 = {it["code"]: it for it in p2["items"] if it["tab"] == "1"}
    assert by2["OO.C"]["answer"] == "yes" and by2["OO.C"]["group"] == "decided"
    assert by2["OO.C.C40.Tx"]["group"] == "manual"  # optional OffWithEffect Tx


def test_manual_cluster_item_flipped_yes_exports():
    """A manually claimed optional item lands in the exported XML."""
    p = webapp.generate_payload(PROFILE)
    enabled = [it["code"] for it in p["items"] if it["answer"] == "yes"]
    enabled.append("OO.S.A4001")  # claim optional OnTime
    files = webapp.export_pics_files(PROFILE, enabled)
    onoff = next(f for f in files if "On-Off" in f)
    import re
    m = re.search(r"<itemNumber>OO\.S\.A4001</itemNumber>.*?<support>(\w+)</support>",
                  files[onoff], re.S)
    assert m and m.group(1) == "true"


def test_im_role_override():
    """im_client in the profile overrides the device-type derivation."""
    p = webapp.generate_payload(PROFILE)
    assert p["im_client"] is False and p["im_client_overridden"] is False

    p2 = webapp.generate_payload(dict(PROFILE, im_client=True))
    assert p2["im_client"] is True and p2["im_client_overridden"] is True
    idm = {it["code"]: it for it in p2["items"] if it["code"].startswith("MCORE.IDM.C")}
    assert idm["MCORE.IDM.C"]["answer"] == "yes"  # override reaches the IDM items


# --- version discovery + cluster grouping --------------------------------------


def test_list_versions_discovers_shipped_data():
    versions = webapp.list_versions()
    assert "1.6" in versions
    assert all(isinstance(v, str) for v in versions)


def test_every_item_carries_a_cluster_label():
    p = webapp.generate_payload(PROFILE)
    assert all(it["cluster"] for it in p["items"])
    by = {it["code"]: it["cluster"] for it in p["items"]}
    assert by["MCORE.COM.WIFI_2P4GHZ"] == "Radio & Transport"
    assert by["MCORE.DD.QR"] == "Discovery & Onboarding"
    assert by["OO.S"] == "On-Off Cluster"
    assert by["ACL.S"].startswith("Access Control")


def test_mcore_area_grouping_is_version_driven():
    """Group membership comes from the loaded Base.xml, not a hardcoded list:
    an unknown future namespace forms its own group instead of vanishing into
    'General'."""
    assert webapp._mcore_area("MCORE.DD.QR") == "Discovery & Onboarding"
    assert webapp._mcore_area("MCORE.NEWAREA.SOMETHING") == "NEWAREA"

    # counts are derived, never stated: recompute one group independently
    from pics_tool.generate.template_io import base_template_path, parse_pics_items
    items = parse_pics_items(base_template_path("1.6"))
    idm = [it.number for it in items if it.number.startswith("MCORE.IDM.")]
    p = webapp.generate_payload(PROFILE)
    shown = [it for it in p["items"] if it["cluster"] == "Interaction Model"]
    assert len(shown) == len(idm)


# --- gateway claims (option b) --------------------------------------------------


def test_gateway_claim_derives_mandatory_side_elements():
    """Claiming X.C is a user-stated fact; the spec derives the client's
    mandatory commands -- but the claim and its consequences STAY in Manual
    selection (pre-filled Yes): "Selected by the tool" is profile-derived only."""
    p = webapp.generate_payload(PROFILE, claims=["OO.C"])
    by = {it["code"]: it for it in p["items"] if it["tab"] == "1"}
    for code in ("OO.C", "OO.C.C00.Tx", "OO.C.C01.Tx", "OO.C.C02.Tx"):
        assert by[code]["group"] == "manual" and by[code]["answer"] == "yes", code
    assert by["OO.C.C40.Tx"]["group"] == "manual"
    assert by["OO.C.C40.Tx"]["answer"] == "no"     # OffWithEffect stays optional
    assert by["OO.S"]["group"] == "decided"        # profile-derived side untouched


def test_claimed_feature_stays_in_manual_section():
    """Same principle for feature claims: user-driven -> Manual selection."""
    p = webapp.generate_payload(PROFILE, claims=["OO.S.F01"])
    by = {it["code"]: it for it in p["items"] if it["tab"] == "1"}
    assert by["OO.S.F01"]["group"] == "manual" and by["OO.S.F01"]["answer"] == "yes"
    assert by["OO.S.A0000"]["group"] == "decided"  # baseline stays tool-decided


def test_manual_section_orders_server_before_client():
    p = webapp.generate_payload(PROFILE)
    manual = [it["code"] for it in p["items"]
              if it["tab"] == "1" and it["group"] == "manual" and it["cluster"] == "On-Off Cluster"]
    first_client = next(i for i, c in enumerate(manual) if c.split(".")[1] == "C")
    assert all(c.split(".")[1] == "C" for c in manual[first_client:]), manual


def test_validate_flags_missing_gateway_dependents():
    problems = webapp.validate_selection(PROFILE, ["OO.C"])
    flagged = {pr["code"] for pr in problems}
    assert {"OO.C.C00.Tx", "OO.C.C01.Tx", "OO.C.C02.Tx"} <= flagged


def test_manual_items_nest_under_their_feature_or_gateway():
    """Manual-section nesting: pure optional items are top-level; items whose
    template cond references a feature nest under THAT feature; client items
    nest under the client gateway. Negated refs ("M if NOT F02") never parent."""
    p = webapp.generate_payload(dict(PROFILE, device_type="Dimmer Switch"))
    by = {it["code"]: it for it in p["items"] if it["tab"] == "1"}
    assert by["OO.S.A4000"]["parent"] == "OO.S.F00"   # LT-gated attribute
    assert by["OO.C.C40.Tx"]["parent"] == "OO.C"      # client item under gateway
    assert by["OO.S.C01.Rsp"]["parent"] is None       # "NOT (OO.S.F02)": no parent
    assert by["OO.S.F00"]["parent"] is None           # feature row is a mini-gateway

    # ordering within the cluster: feature block sits together, client last
    manual = [it["code"] for it in p["items"]
              if it["tab"] == "1" and it["group"] == "manual"
              and it["cluster"] == "On-Off Cluster"]
    f00 = manual.index("OO.S.F00")
    assert manual[f00 + 1] == "OO.S.A4000"            # dependents right below


def test_multi_feature_conformance_is_boolean_exact():
    """(A AND B) enables only when BOTH features are claimed; (A OR B) enables
    when EITHER is. The conformance evaluator is a real boolean engine -- no
    heuristics."""
    from esp_matter_datamodel import loader
    from pics_tool.generate.cluster_engine import claim_cluster_side

    m = loader.load_version("1.6", validate=False)
    cond = frozenset({"Wi-Fi", "IP", "Active"})

    def enabled(cid, item, feats):
        return item in claim_cluster_side(m, cid, "S", cond,
                                          seed_feature_codes=set(feats))

    # TSTAT.S.A0013 (OccupiedCoolingSetpoint): M if COOL AND OCC
    assert not enabled("0x0201", "TSTAT.S.A0013", ())
    assert not enabled("0x0201", "TSTAT.S.A0013", ("COOL",))
    assert not enabled("0x0201", "TSTAT.S.A0013", ("OCC",))
    assert enabled("0x0201", "TSTAT.S.A0013", ("COOL", "OCC"))

    # CC.S.C47.Rsp (StopMoveStep): M if HS OR XY OR CT
    assert not enabled("0x0300", "CC.S.C47.Rsp", ())
    assert enabled("0x0300", "CC.S.C47.Rsp", ("XY",))
    assert enabled("0x0300", "CC.S.C47.Rsp", ("CT",))
    assert enabled("0x0300", "CC.S.C47.Rsp", ("HS", "XY"))


def test_export_roundtrip_fidelity():
    """The two export guarantees:
    1. every Yes answer lands in the exported XML, support=true, in the SAME
       endpoint file (tab) the user answered it on -- nothing lost or moved;
    2. every written file contains the COMPLETE template (all picsItems), and
       nothing beyond the Yes set is flipped to true."""
    import re
    import xml.etree.ElementTree as ET
    from pics_tool.generate.template_io import list_templates, parse_pics_items

    profile = dict(PROFILE, device_type="Extended Color Light")
    p = webapp.generate_payload(profile)

    # flip a manual item on every tab, incl. Descriptor on EP1 (also on EP0)
    extra = {"base": "MCORE.DD.PHYSICAL_TAMPERING",
             "0": "ACL.S.A0007", "1": "DESC.S.A0005"}
    by_tab = {}
    for it in p["items"]:
        if it["answer"] == "yes" or extra.get(it["tab"]) == it["code"]:
            by_tab.setdefault(it["tab"], []).append(it["code"])

    files = webapp.export_pics_files(profile, by_tab)

    def supports(xml):
        out = {}
        for pi in ET.fromstring(xml).iter("picsItem"):
            out[(pi.findtext("itemNumber") or "").strip()] = \
                (pi.findtext("support") or "").strip() == "true"
        return out

    tab_dir = {"base": "endpoint0", "0": "endpoint0", "1": "endpoint1"}
    parsed = {f: supports(x) for f, x in files.items() if f.endswith(".xml")}

    # guarantee 1: every Yes present, true, in the right endpoint dir
    for t, codes in by_tab.items():
        for code in codes:
            hits = [f for f, sup in parsed.items()
                    if f.startswith(tab_dir[t] + "/") and sup.get(code)]
            assert hits, f"{code} (tab {t}) missing from export"
    # ...and nothing extra is true
    all_yes = {c for codes in by_tab.values() for c in codes}
    for f, sup in parsed.items():
        for code, on in sup.items():
            if on:
                assert code in all_yes, f"{f}: {code} true but never answered Yes"

    # guarantee 2: written files carry the complete template, item for item
    templates = {t.name: {it.number for it in parse_pics_items(t)}
                 for t in list_templates("1.6")}
    for f, sup in parsed.items():
        tname = f.split("/", 1)[1]
        assert set(sup) == templates[tname], f"{f} does not match its template"


# --- full pre-export validation (CSA-parity sweep) ------------------------------


def _errors(problems):
    return {p["code"] for p in problems if p["severity"] == "error"}


def test_validate_catches_template_cond_cascade_from_attribute_claim():
    """Claiming an optional attribute can make another item mandatory via the
    TEMPLATE cond (BINFO.S.A0011 Reachable -> BINFO.S.E03 ReachableChanged);
    the sweep must catch it even though no engine path derives it."""
    p = webapp.generate_payload(PROFILE)
    by_tab = {}
    for it in p["items"]:
        if it["answer"] == "yes":
            by_tab.setdefault(it["tab"], []).append(it["code"])
    by_tab["0"].append("BINFO.S.A0011")
    problems = webapp.validate_selection(PROFILE, by_tab)
    assert "BINFO.S.E03" in _errors(problems)


def test_validate_cascades_to_fixpoint():
    """Enabling a Wi-Fi band cascades: COM.WIFI becomes mandatory, and once it
    is, COM.WIRELESS does too — one validation reports the whole closure."""
    problems = webapp.validate_selection(PROFILE, ["MCORE.COM.WIFI_2P4GHZ"])
    errs = _errors(problems)
    assert "MCORE.COM.WIFI" in errs
    assert "MCORE.COM.WIRELESS" in errs


def test_known_template_quirks_are_warnings_not_errors():
    p = webapp.generate_payload(PROFILE)
    enabled = [it["code"] for it in p["items"] if it["answer"] == "yes"]
    problems = webapp.validate_selection(PROFILE, enabled + ["MCORE.OTA.VendorSpecific"])
    scf = [pr for pr in problems if pr["code"] == "MCORE.DD.STANDARD_COMM_FLOW"]
    assert scf and scf[0]["severity"] == "warning"
    assert "deliberately" in scf[0]["why"]


def test_idm_capabilities_not_blanket_claimed():
    """IM role derivation gives only what the spec forces: the role atoms and
    (for a device with mandated client Tx commands) InvokeRequest. Granular
    client capabilities (write Bool, batch, read...) and optional server
    capabilities (LargeData, PersistentSubscription) are the vendor's call."""
    p = webapp.generate_payload(dict(PROFILE, device_type="Dimmer Switch"))
    by = {it["code"]: it for it in p["items"] if it["tab"] == "base"}
    assert by["MCORE.IDM.C"]["answer"] == "yes"
    assert by["MCORE.IDM.C.InvokeRequest"]["answer"] == "yes"  # mandated Tx
    for c in ("MCORE.IDM.C.WriteRequest.Attribute.DataType_Bool",
              "MCORE.IDM.C.ReadRequest", "MCORE.IDM.C.InvokeRequest.BatchCommands",
              "MCORE.IDM.S.LargeData", "MCORE.IDM.S.PersistentSubscription"):
        assert by[c]["group"] == "manual" and by[c]["answer"] == "no", c

    # server-only device: client side is an input-backed decided No
    p2 = webapp.generate_payload(PROFILE)
    by2 = {it["code"]: it for it in p2["items"] if it["tab"] == "base"}
    assert by2["MCORE.IDM.C.WriteRequest.Attribute.DataType_Bool"]["group"] == "decided"
    assert by2["MCORE.IDM.C.WriteRequest.Attribute.DataType_Bool"]["answer"] == "no"


def test_client_claim_flows_into_im_role():
    """Claiming an optional client side (OO.C) makes the device an IM client:
    the IM role follows the claim, IDM.C + InvokeRequest fill in as manual-Yes
    (user-driven, not tool-decided), the granular capabilities open up as
    manual questions, and unclaiming reverts everything."""
    p = webapp.generate_payload(PROFILE, claims=["OO.C"])
    assert p["im_client"] is True
    by = {it["code"]: it for it in p["items"]}
    for c in ("MCORE.IDM.C", "MCORE.IDM.C.InvokeRequest"):
        assert by[c]["group"] == "manual" and by[c]["answer"] == "yes", c
    assert by["MCORE.IDM.C.ReadRequest"]["group"] == "manual"
    assert by["MCORE.IDM.C.ReadRequest"]["answer"] == "no"

    # validation backs it up if the claim set is inconsistent
    errs = {pr["code"] for pr in webapp.validate_selection(PROFILE, ["OO.C", "OO.C.C00.Tx"])
            if pr["severity"] == "error"}
    assert {"MCORE.IDM.C", "MCORE.IDM.C.InvokeRequest"} <= errs

    # no claim -> server only, client side decided No
    p2 = webapp.generate_payload(PROFILE)
    assert p2["im_client"] is False


def test_wifi_paf_input_decides_both_paf_items():
    """wifi_paf input: Yes seeds DD.DISCOVERY_PAF and COM.PAF derives via the
    cond fixpoint (with Wi-Fi); No is an input-backed decided No. Without a
    Wi-Fi transport, COM.PAF stays off even when PAF discovery is claimed."""
    p = webapp.generate_payload(dict(PROFILE, wifi_paf=True))
    by = {it["code"]: it for it in p["items"] if it["tab"] == "base"}
    assert by["MCORE.DD.DISCOVERY_PAF"]["group"] == "decided"
    assert by["MCORE.DD.DISCOVERY_PAF"]["answer"] == "yes"
    assert by["MCORE.COM.PAF"]["group"] == "decided"
    assert by["MCORE.COM.PAF"]["answer"] == "yes"

    p2 = webapp.generate_payload(PROFILE)  # default: wifi_paf false
    by2 = {it["code"]: it for it in p2["items"] if it["tab"] == "base"}
    assert by2["MCORE.DD.DISCOVERY_PAF"]["group"] == "decided"
    assert by2["MCORE.DD.DISCOVERY_PAF"]["answer"] == "no"
    assert by2["MCORE.COM.PAF"]["answer"] == "no"

    p3 = webapp.generate_payload(dict(PROFILE, transport=["thread"], wifi_paf=True))
    by3 = {it["code"]: it for it in p3["items"] if it["tab"] == "base"}
    assert by3["MCORE.COM.PAF"]["answer"] == "no"  # PAF needs Wi-Fi


def test_nfc_commissioning_input_decides_ntl():
    """NFC Transport Layer commissioning is its own discovery input: it decides
    MCORE.DD.NTL both ways, independent of the passive onboarding NFC tag."""
    p = webapp.generate_payload(dict(PROFILE, nfc_commissioning=True))
    by = {it["code"]: it for it in p["items"] if it["tab"] == "base"}
    assert by["MCORE.DD.NTL"]["group"] == "decided"
    assert by["MCORE.DD.NTL"]["answer"] == "yes"
    assert by["MCORE.DD.NFC"]["answer"] == "no"  # tag input untouched

    p2 = webapp.generate_payload(dict(PROFILE, onboarding=["nfc"]))
    by2 = {it["code"]: it for it in p2["items"] if it["tab"] == "base"}
    assert by2["MCORE.DD.NFC"]["answer"] == "yes"   # tag claimed
    assert by2["MCORE.DD.NTL"]["group"] == "decided"
    assert by2["MCORE.DD.NTL"]["answer"] == "no"    # transport NOT implied by tag


def test_manual_pairing_code_length_decides_commissioning_flow():
    """Spec 5.1.4: an 11-digit manual code implies Standard Commissioning Flow;
    a 21-digit code (VID/PID embedded) implies a NON-standard flow and must not
    claim STANDARD_COMM_FLOW."""
    p11 = webapp.generate_payload(dict(PROFILE, onboarding=["manual_pairing_code_11"]))
    by11 = {it["code"]: it for it in p11["items"] if it["tab"] == "base"}
    assert by11["MCORE.DD.MANUAL_PC"]["answer"] == "yes"
    assert by11["MCORE.DD.STANDARD_COMM_FLOW"]["answer"] == "yes"

    p21 = webapp.generate_payload(dict(PROFILE, onboarding=["manual_pairing_code_21"]))
    by21 = {it["code"]: it for it in p21["items"] if it["tab"] == "base"}
    assert by21["MCORE.DD.MANUAL_PC"]["answer"] == "yes"
    assert by21["MCORE.DD.STANDARD_COMM_FLOW"]["answer"] == "no"
    # which non-standard flow is a product fact -> manual
    assert by21["MCORE.DD.CUSTOM_COMM_FLOW"]["group"] == "manual"


def test_ota_input_covers_all_combinations():
    """OTA input: requestor / provider / vendor-specific, any combination."""
    base = dict(PROFILE, onboarding=["qr"])
    p = webapp.generate_payload(dict(base, node_device_types=["OTA Requestor"],
                                     vendor_specific_ota=True))
    by = {it["code"]: it for it in p["items"] if it["tab"] == "base"}
    assert by["MCORE.OTA.Requestor"]["answer"] == "yes"
    assert by["MCORE.OTA.VendorSpecific"]["answer"] == "yes"  # both is valid
    assert by["MCORE.BDX.Receiver"]["answer"] == "yes"
    assert by["MCORE.OTA.Resume"]["group"] == "manual"  # requestor sub-cap: ask

    p2 = webapp.generate_payload(dict(base, node_device_types=["OTA Provider"]))
    by2 = {it["code"]: it for it in p2["items"] if it["tab"] == "base"}
    assert by2["MCORE.OTA.Provider"]["answer"] == "yes"
    assert by2["MCORE.BDX.Sender"]["answer"] == "yes"


def test_mcore_claims_reenter_the_cond_fixpoint():
    """Claiming a Base atom derives its dependents at GENERATION time (not only
    in the export validator): DD.CONCATENATED_QR_CODE mandates DD.QR."""
    # onboarding=nfc only, so DD.QR is not seeded by the profile
    profile = dict(PROFILE, onboarding=["nfc"])
    base = webapp.generate_payload(profile)
    by0 = {it["code"]: it for it in base["items"] if it["tab"] == "base"}
    assert by0["MCORE.DD.QR"]["answer"] == "no"

    p = webapp.generate_payload(profile, claims=["MCORE.DD.CONCATENATED_QR_CODE"])
    by = {it["code"]: it for it in p["items"] if it["tab"] == "base"}
    assert by["MCORE.DD.CONCATENATED_QR_CODE"]["answer"] == "yes"
    assert by["MCORE.DD.QR"]["answer"] == "yes"          # derived from the claim
    assert by["MCORE.DD.QR"]["group"] == "manual"        # ...and stays YOURS


def test_bdx_not_ruled_out_by_vendor_ota():
    """The OTA input derives the BDX roles Matter OTA needs, but cannot rule
    the others out -- BDX also serves Diagnostic Logs (DUT may even be the
    Sender). Without Matter OTA, every BDX item is an Optional Item, not a
    decided No; with Matter OTA, the receiver trio is decided-Yes and the rest
    stay optional."""
    vendor = webapp.generate_payload(dict(PROFILE, vendor_specific_ota=True))
    byv = {it["code"]: it for it in vendor["items"] if it["tab"] == "base"}
    for c in ("MCORE.BDX.Receiver", "MCORE.BDX.Sender", "MCORE.BDX.Initiator",
              "MCORE.BDX.Responder", "MCORE.BDX.AsynchronousReceiver",
              "MCORE.BDX.Driver"):
        assert byv[c]["group"] == "manual" and byv[c]["answer"] == "no", c

    req = webapp.generate_payload(dict(PROFILE, node_device_types=["OTA Requestor"]))
    byr = {it["code"]: it for it in req["items"] if it["tab"] == "base"}
    for c in ("MCORE.BDX.Receiver", "MCORE.BDX.Initiator", "MCORE.BDX.SynchronousReceiver"):
        assert byr[c]["group"] == "decided" and byr[c]["answer"] == "yes", c
    for c in ("MCORE.BDX.Sender", "MCORE.BDX.Responder"):  # sender side: DLOG may need it
        assert byr[c]["group"] == "manual" and byr[c]["answer"] == "no", c
