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
"""The two-step MCP surface: a complete mandatory baseline from one call, then
the human's optional answers applied by the second. Tools are exercised as
plain functions (no stdio transport)."""

import re

import pytest

pytest.importorskip("mcp")
pytest.importorskip("esp_matter_datamodel.loader")

import mcp_server


def _fn(tool):
    """The plain function behind a FastMCP/MCPServer tool object."""
    return getattr(tool, "fn", None) or getattr(tool, "__wrapped__", None) or tool


baseline = _fn(mcp_server.generate_baseline)
apply_sel = _fn(mcp_server.apply_selections)

SEL = {
    "spec_version": "1.6",
    "transport": ["wifi_2g"],
    "role": "commissionee",
    "onboarding": ["qr", "manual_pairing_code"],
    "endpoints": [{"device_types": ["Extended Color Light"]}],
}


def _support(code: str, xml: str):
    m = re.search(
        rf"<itemNumber>{re.escape(code)}</itemNumber>.*?"
        rf"<support>(true|false)</support>",
        xml,
        re.S,
    )
    return m and m.group(1)


def test_discovery_paths_return_data_not_exceptions():
    r = baseline()
    assert r["error"] and r["versions"] and r["usage"]
    r = baseline({"spec_version": "1.6"})
    assert "device_types" in r and "Extended Color Light" in r["device_types"]
    r = baseline({"spec_version": "9.9"})
    assert "versions" in r
    r = baseline(
        {"spec_version": "1.6", "endpoints": [{"device_types": ["Colour Light"]}]}
    )
    assert "Colour Light" in r["error"] and "device_types" in r


def test_missing_version_instructs_agent_to_ask_not_default():
    """A missing/invalid spec version returns the supported list AND an explicit
    instruction to ask the user -- so the agent never silently defaults."""
    r = baseline()
    assert set(r["versions"]) >= {"1.4", "1.6"}
    assert "ASK THE USER" in r["action"] and "version" in r["action"].lower()
    # never nudge the agent toward a default
    assert "latest" in r["action"].lower()  # "...not even the latest..."

    r = baseline({"spec_version": "1.7"})  # plausible-but-unsupported
    assert "1.7" in r["error"] and "ASK" in r["action"] and r["versions"]


def test_device_type_not_in_version_is_rejected_with_valid_list():
    """A device type valid in a newer Matter version but absent in the chosen
    one is rejected, with the version's real device types + an ask-the-user
    instruction (no silent substitution)."""
    from pics_tool import service

    newer = set(service.list_device_types("1.6")) - set(
        service.list_device_types("1.4")
    )
    dt = sorted(newer)[0]  # e.g. "Audio Doorbell"
    r = baseline({"spec_version": "1.4", "endpoints": [{"device_types": [dt]}]})
    assert dt in r["error"] and "1.4" in r["error"]
    assert dt not in r["device_types"]  # the real 1.4 list, without it
    assert "ASK THE USER" in r["action"]


def test_baseline_is_complete_and_lists_optional_choices():
    r = baseline(SEL)
    assert r["pics_files"] and r["code"] and r["code"]["snippet"]
    assert not [p for p in r["problems"] if p["severity"] != "warning"]
    oc = r["optional_choices"]
    assert oc["counts"]["open"] > 0 and oc["counts"]["primary"] > 0
    # grouped like the UI: node topics + Root Node + the app endpoint
    tabs = {g["tab"] for g in oc["groups"]}
    assert {"base", "0", "1"} <= tabs
    # every choice is a real, claimable unit with a human label
    for g in oc["groups"]:
        for cl in g["clusters"]:
            for c in cl["choices"]:
                assert (
                    c["code"]
                    and c["label"]
                    and c["priority"] in ("primary", "secondary")
                )


def test_apply_selections_threads_claims_and_consequences():
    r = apply_sel(
        SEL, {"1": ["CC.S.F00"], "base": ["MCORE.DD.TXT_KEY_VP"]}, goal="pics"
    )
    assert r["ignored_unknown_codes"] == []
    ep1 = next(
        x for p, x in r["pics_files"].items() if "endpoint1" in p and "Color" in p
    )
    assert _support("CC.S.F00", ep1) == "true"
    assert _support("CC.S.A0000", ep1) == "true"  # CurrentHue: F00 consequence
    base_xml = next(x for p, x in r["pics_files"].items() if "Base" in p)
    assert _support("MCORE.SC.VP_KEY", base_xml) == "true"  # mirrored twin


def test_apply_selections_guards():
    assert "generate_baseline" in apply_sel(SEL, {})["error"]
    assert "invalid tab keys" in apply_sel(SEL, {"EP1": ["CC.S.F00"]})["error"]
    r = apply_sel(SEL, {"1": ["CC.S.F00", "CC.S.FAKE99"]})
    assert r["ignored_unknown_codes"] == ["CC.S.FAKE99"]
    assert "ignored" in r["summary"]["note"]
