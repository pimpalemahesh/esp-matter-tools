#!/usr/bin/env python3

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
"""MCP server for the Matter PICS + esp-matter code generator.

Two tools (stdio), mirroring the web UI's flow:

1. ``generate_matter_pics(selection)`` -- the device description in, the complete
   MANDATORY result out: PICS XML files + esp-matter code + the list of open
   optional choices. Independent and complete: for a mandatory-only package,
   this one call is the whole job. Discovery is built in (call with no/partial
   input to learn the valid spec versions / device-type names).

2. ``add_optional_capabilities(selection, selected)`` -- OPTIONAL follow-up.
   Skip it for a mandatory-only package; call it only when the HUMAN has picked
   optional capabilities to add. Feed their YES codes back and it returns the
   PICS + code with every claim (and its spec consequences) applied.

Run (no pip install of this tool needed; only the ``mcp`` package):

    pip install -r requirements.txt -r requirements-mcp.txt
    python3 mcp_server.py            # or: python3 -m pics_tool.mcp_server
"""

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (_HERE, _HERE / "esp-matter-datamodel"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# The high-level decorator server: MCPServer in mcp >= 2.0, FastMCP in mcp 1.x.
# Both expose ``@server.tool()`` and ``server.run()`` (stdio).
try:
    from mcp.server.mcpserver import MCPServer as _Server  # mcp >= 2.0
except ModuleNotFoundError:
    try:
        from mcp.server.fastmcp import FastMCP as _Server  # mcp 1.x
    except (
        ModuleNotFoundError
    ) as exc:  # pragma: no cover - clearer than a raw ImportError
        raise SystemExit(
            "The 'mcp' package is required for the MCP server. Install it with:\n"
            "    pip install -r requirements-mcp.txt"
        ) from exc

from pics_tool import service

mcp = _Server("esp-matter-pics")


_USAGE = (
    "Provide 'selection' with at least spec_version, endpoints (device types) "
    'and transport, e.g. {"spec_version": "1.6", "transport": ["wifi_2g"], '
    '"role": "commissionee", "onboarding": ["qr", "manual_pairing_code"], '
    '"endpoints": [{"device_types": ["Extended Color Light"]}]}. '
    'Optional selection fields: node_device_types (["OTA Requestor"]), '
    "ble_commissioning, nfc_commissioning, wifi_paf, tcp, extended_discovery, "
    "commissioning_flow ('standard'|'user_intent'|'custom'), "
    "vendor_specific_ota, role ('commissionee'|'commissioner'|'controller')."
)


def _kind(code: str) -> str:
    """Coarse element kind from a PICS code, for ordering/labelling choices."""
    if code.startswith("MCORE."):
        return "node"
    if re.search(r"\.[SC]\.F[0-9a-fA-F]{2}$", code):
        return "feature"
    if re.search(r"^[A-Z0-9_]+\.[SC]$", code):
        return "cluster"
    if re.search(r"\.[SC]\.A[0-9a-fA-F]{4}$", code):
        return "attribute"
    if re.search(r"\.[SC]\.C[0-9a-fA-F]{2}", code):
        return "command"
    if re.search(r"\.[SC]\.E[0-9a-fA-F]{2}$", code):
        return "event"
    return "other"


_KIND_ORDER = {
    "cluster": 0,
    "feature": 1,
    "command": 2,
    "event": 3,
    "attribute": 4,
    "node": 5,
    "other": 6,
}
# The capability decisions a product owner actually recognises: whole optional
# clusters and optional features. The long tail (attributes/commands/events,
# node product-facts) safely defaults to "No".
_PRIMARY = ("cluster", "feature")


def _validate(selection: dict | None) -> dict | None:
    """Discovery-friendly input check: an error DICT (with the data the caller
    needs AND an explicit instruction to ASK THE USER rather than guess),
    or None when valid.

    The ``action`` field is a direct instruction to the calling agent: the
    Matter spec version and device type are the user's product facts, so on a
    missing/invalid one the agent must surface the supported options to the
    user and let them choose -- never silently default to a version or a
    device type.
    """
    versions = service.list_versions()
    selection = selection or {}
    version = selection.get("spec_version")
    if not version:
        return {
            "error": "no spec_version given",
            "versions": versions,
            "action": "ASK THE USER which Matter spec version to target and "
            "show them the supported versions listed here. Do NOT "
            "pick a version yourself (not even the latest) -- the "
            "version is the user's decision.",
            "usage": _USAGE,
        }
    if version not in versions:
        return {
            "error": f"unsupported spec_version {version!r}",
            "versions": versions,
            "action": f"Matter {version} is not supported. Show the user the "
            "supported versions listed here and ASK which one to use; "
            "do not substitute one yourself.",
            "usage": _USAGE,
        }
    known_types = sorted(service.list_device_types(version))
    named = [
        dt
        for ep in selection.get("endpoints") or []
        for dt in (ep.get("device_types") if isinstance(ep, dict) else [ep]) or []
    ]
    if selection.get("device_type"):
        named.append(selection["device_type"])
    if not named:
        return {
            "error": "no endpoints/device types given",
            "device_types": known_types,
            "spec_version": version,
            "action": f"ASK THE USER which application device type(s) their "
            f"product exposes, choosing from the device types "
            f"supported in Matter {version} (listed here).",
            "usage": _USAGE,
        }
    unknown = [n for n in named if n not in known_types]
    if unknown:
        return {
            "error": f"device type(s) not available in Matter {version}: {unknown}",
            "device_types": known_types,
            "spec_version": version,
            "action": f"The device type(s) {unknown} are not available in "
            f"Matter {version}. ASK THE USER to pick from the "
            f"supported device types for this version (listed here), "
            f"or to choose a different Matter version -- do not "
            f"substitute a similar-sounding device type yourself.",
            "usage": _USAGE,
        }
    return None


def _optional_choices(selection: dict, selected: dict | None) -> dict:
    """The still-open optional choices, grouped endpoint -> cluster (the same
    shape as the web UI's simple view). Every choice maps 1:1 to a PICS code."""
    res = service.selection_questions(selection, selected)
    groups: list[dict] = []
    by_tab: dict[str, dict] = {}
    primary = 0
    for q in res["questions"]:
        kind = _kind(q["code"])
        g = by_tab.get(q["tab"])
        if g is None:
            g = by_tab[q["tab"]] = {
                "tab": q["tab"],
                "label": q["endpoint"],
                "scope": "node" if q["tab"] == "base" else "endpoint",
                "clusters": [],
                "_by": {},
            }
            groups.append(g)
        cl = g["_by"].get(q["cluster"])
        if cl is None:
            cl = g["_by"][q["cluster"]] = {"cluster": q["cluster"], "choices": []}
            g["clusters"].append(cl)
        pri = kind in _PRIMARY
        primary += pri
        cl["choices"].append(
            {
                "code": q["code"],
                "label": q["label"],
                "kind": kind,
                "priority": "primary" if pri else "secondary",
            }
        )
    for g in groups:
        g.pop("_by", None)
        for cl in g["clusters"]:
            cl["choices"].sort(key=lambda c: _KIND_ORDER.get(c["kind"], 9))
    return {
        "counts": {"open": len(res["questions"]), "primary": primary},
        "groups": groups,
    }


def _run(selection: dict, selected: dict | None, goal: str, target: str) -> dict:
    """Shared engine run for both tools: outputs + the open optional choices."""
    try:
        out = service.generate(selection, selected, target, goal)
    except ValueError as exc:
        return {"error": str(exc), "usage": _USAGE}
    out["optional_choices"] = _optional_choices(selection, selected)
    q = service.selection_questions(selection, selected)
    out["summary"] = dict(q["summary"])
    return out


@mcp.tool()
def generate_matter_pics(
    selection: dict | None = None, goal: str = "both", target: str = "esp_matter"
) -> dict:
    """STEP 1 -- generate the complete MANDATORY Matter PICS and/or esp-matter
    data-model code from a device description, plus the list of optional
    choices a human may still want to add.

    ``selection`` describes the device::

        {"spec_version": "1.6", "transport": ["wifi_2g"], "role": "commissionee",
         "onboarding": ["qr", "manual_pairing_code"],
         "endpoints": [{"device_types": ["Extended Color Light"]}]}

    The result is COMPLETE for a mandatory-only package: every answer the spec
    derives from the inputs is filled in (nothing optional is assumed; optional
    items export as "No"). If that is all the user wants, you are done after
    this one call.

    DISCOVERY -- ASK, DON'T GUESS: the Matter spec version and the device
    type are the user's product facts, not yours to default. If the user has
    not given a spec version, call this with ``selection`` omitted (or without
    ``spec_version``); the response returns the supported ``versions`` and an
    ``action`` telling you to ask the user which one to use -- present the list
    and let them choose, do NOT pick a version (not even the latest) yourself.
    With a version but no/unknown device type, the response returns the exact
    ``device_types`` available in that version; ask the user to pick from them
    (a device type valid in one Matter version may not exist in another).

    OPTIONAL CAPABILITIES: ``optional_choices`` lists every open choice,
    grouped endpoint -> cluster (plus node-wide topics), each with a PICS
    ``code``, a human ``label``, a ``kind`` and a ``priority``. These are
    product facts only the HUMAN owns. Unless the user already said they want
    mandatory-only, present the ``priority=="primary"`` choices (optional
    clusters and features) to them and ask which their device supports --
    do NOT answer on their behalf. Then pass their YES codes to
    ``add_optional_capabilities``.

    ``goal``: "pics" (XML files + spec-check), "code" (data-model code only),
    or "both" (default). ``target``: code generator (default "esp_matter").

    Returns ``{"summary", "pics_files": {path: xml}, "code": {snippet, ...},
    "problems": [...], "optional_choices": {counts, groups}}`` -- or, for
    incomplete input, ``{"error", "action", "usage", "versions"|"device_types"}``
    where ``action`` is a direct instruction on what to ask the user.
    """
    err = _validate(selection)
    if err:
        return err
    out = _run(dict(selection), None, goal, target)
    if "error" not in out:
        out["summary"]["note"] = (
            "Mandatory baseline -- complete as-is. To add optional capabilities, "
            "ask the human about the primary optional_choices and pass their YES "
            "codes to add_optional_capabilities."
        )
    return out


@mcp.tool()
def add_optional_capabilities(
    selection: dict, selected: dict, goal: str = "both", target: str = "esp_matter"
) -> dict:
    """STEP 2 (OPTIONAL) -- re-generate with the extra capabilities the human
    chose, on top of the mandatory package from ``generate_matter_pics``.

    SKIP this call entirely for a mandatory-only package -- ``generate_matter_pics``
    is already complete on its own. Call this ONLY when the human has picked
    optional capabilities to add.

    ``selection`` is the same device description passed to
    ``generate_matter_pics``. ``selected`` is the human's YES answers as
    ``{tab: [pics_code, ...]}`` -- tab "base" = node-wide, "0" = Root Node,
    "1".. = application endpoints; the codes come from
    ``optional_choices`` (e.g. ``{"1": ["CC.S.F00", "CC.S.F02"]}``).

    Claims cascade exactly like the web UI: everything a claimed feature or
    cluster mandates is auto-included, and a claim can REVEAL new optional
    sub-choices -- check the returned ``optional_choices`` and, if new primary
    choices appeared, put them to the human and call this again with the
    grown ``selected``.

    ``problems`` is the spec-check: empty (or only severity "warning") means
    clean; fix an "error" by appending the named code to ``selected`` on the
    tab it names and re-calling. ``ignored_unknown_codes`` lists any selected
    codes that are not real PICS items for this version (typos) -- they were
    skipped; correct them from ``optional_choices``.

    Returns the same shape as ``generate_matter_pics``.
    """
    err = _validate(selection)
    if err:
        return err
    if not selected or not any(selected.values()):
        return {
            "error": "no selections given -- generate_matter_pics already "
            "returns the mandatory-only outputs; call this tool "
            "only with the human's YES codes in 'selected'",
            "usage": _USAGE,
        }
    bad_tabs = [t for t in selected if t != "base" and not str(t).isdigit()]
    if bad_tabs:
        return {
            "error": f"invalid tab keys {bad_tabs}: use 'base', '0' (Root "
            "Node) or the application endpoint number ('1'..)",
            "usage": _USAGE,
        }
    known = service.known_codes(selection["spec_version"])
    unknown = sorted({c for codes in selected.values() for c in codes} - set(known))
    out = _run(dict(selection), selected, goal, target)
    if "error" not in out:
        out["ignored_unknown_codes"] = unknown
        remaining = out["optional_choices"]["counts"]
        out["summary"]["note"] = (
            "Final outputs with the human's selections applied. "
            + (
                f"WARNING: {len(unknown)} selected code(s) are not real PICS items "
                f"and were ignored -- see ignored_unknown_codes. "
                if unknown
                else ""
            )
            + (
                f"{remaining['primary']} primary optional choice(s) are still open "
                "(some may have been revealed by these claims) -- offer them to "
                "the human if not already answered."
                if remaining["primary"]
                else ""
            )
        )
    return out


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
