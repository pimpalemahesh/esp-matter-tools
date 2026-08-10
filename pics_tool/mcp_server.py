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

Exposes the tool to an LLM as four MCP tools (stdio). The intended, minimal-state
flow -- the LLM keeps only a small ``selection`` and a ``selected`` answer map:

  1. list_matter_versions()            -> pick a spec version
  2. list_device_types(version)        -> pick device type(s) per endpoint
  3. build a ``selection`` dict
  4. get_selection_questions(selection[, selected])
        -> ask the HUMAN each yes/no question; for every YES, append the
           question's ``code`` to ``selected[<its tab>]``.
        -> optionally call again with the updated ``selected`` to reveal
           sub-questions a just-enabled feature unlocks.
  5. generate(selection, selected)     -> PICS XML files + esp-matter code

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
    from mcp.server.mcpserver import MCPServer as _Server   # mcp >= 2.0
except ModuleNotFoundError:
    try:
        from mcp.server.fastmcp import FastMCP as _Server   # mcp 1.x
    except ModuleNotFoundError as exc:  # pragma: no cover - clearer than a raw ImportError
        raise SystemExit(
            "The 'mcp' package is required for the MCP server. Install it with:\n"
            "    pip install -r requirements-mcp.txt") from exc

from pics_tool import service

mcp = _Server("esp-matter-pics")


# ---- MCP-side presentation: group the flat questions so an LLM can walk the
# whole selection tab-by-tab instead of drowning in one list. This is purely a
# view over service.selection_questions -- the common facade stays flat.

_KIND_ORDER = {"feature": 0, "side": 1, "command": 2, "event": 3,
               "attribute": 4, "node": 5, "other": 6}


def _kind(code: str) -> str:
    """Coarse element kind from a PICS code, for ordering/labelling questions."""
    if code.startswith("MCORE."):
        return "node"
    if re.search(r"\.[SC]\.F[0-9a-fA-F]{2}$", code):
        return "feature"
    if re.search(r"\.[SC]\.A[0-9a-fA-F]{4}$", code):
        return "attribute"
    if re.search(r"\.[SC]\.C[0-9a-fA-F]{2}", code):
        return "command"
    if re.search(r"\.[SC]\.E[0-9a-fA-F]{2}$", code):
        return "event"
    if re.search(r"^[A-Z0-9_]+\.[SC]$", code):
        return "side"
    return "other"


# A question's priority tells the LLM what it MUST put to the human vs. what it
# may leave at the default. "primary" = the capability decisions a product owner
# actually knows (does this device do X?): optional features and cluster sides.
# "secondary" = the long tail (attributes/commands/events, node product-facts)
# that follows from the capabilities or is safely left off unless asked for.
def _priority(kind: str) -> str:
    return "primary" if kind in ("feature", "side") else "secondary"


def _grouped(result: dict, goal: str = "both") -> dict:
    """Reshape ``{summary, questions}`` into ``{summary, groups, questions}``.

    ``groups`` = one entry per tab (in the summary's endpoint order), each with
    its ``clusters`` (first-seen order); each cluster's ``questions`` are ordered
    features/sides first, and it carries per-kind ``counts``. Every question gains
    a ``kind`` and a ``priority`` ("primary"/"secondary"); the summary gains
    primary/secondary counts and a ``how_to_ask`` directive. ``goal`` only shapes
    the guidance/echo -- the caller has already filtered ``questions`` for it.
    """
    tab_order = [e["tab"] for e in result["summary"].get("endpoints", [])]
    tab_label = {e["tab"]: e["label"] for e in result["summary"].get("endpoints", [])}
    questions = []
    for q in result["questions"]:
        k = _kind(q["code"])
        questions.append(dict(q, kind=k, priority=_priority(k)))

    groups: list[dict] = []
    by_tab: dict[str, dict] = {}
    for q in questions:
        g = by_tab.get(q["tab"])
        if g is None:
            g = by_tab[q["tab"]] = {
                "tab": q["tab"],
                "label": tab_label.get(q["tab"], q["endpoint"]),
                "scope": "node" if q["tab"] == "base" else "endpoint",
                "clusters": [], "_by_cluster": {},
            }
            groups.append(g)
        cl = g["_by_cluster"].get(q["cluster"])
        if cl is None:
            cl = g["_by_cluster"][q["cluster"]] = {"cluster": q["cluster"], "questions": []}
            g["clusters"].append(cl)
        cl["questions"].append(q)

    for g in groups:
        g.pop("_by_cluster", None)
        g["primary_count"] = 0
        for cl in g["clusters"]:
            cl["questions"].sort(key=lambda q: (_KIND_ORDER.get(q["kind"], 9), q["code"]))
            cl["counts"] = {}
            for q in cl["questions"]:
                cl["counts"][q["kind"]] = cl["counts"].get(q["kind"], 0) + 1
            g["primary_count"] += sum(1 for q in cl["questions"] if q["priority"] == "primary")
    groups.sort(key=lambda g: tab_order.index(g["tab"]) if g["tab"] in tab_order else 99)

    primary = sum(1 for q in questions if q["priority"] == "primary")
    summary = dict(result["summary"])
    summary["goal"] = goal
    summary["counts"] = dict(summary.get("counts", {}), to_decide=len(questions),
                             primary=primary, secondary=len(questions) - primary)
    goal_note = ("" if goal != "code" else
                 " (goal='code': node/Base.xml questions are omitted -- they shape "
                 "the PICS, not the data-model code.)")
    summary["how_to_ask"] = (
        "STEP 0 -- if you have not already, ask the human whether they want PICS "
        "files, the esp-matter data-model code, or both, and pass it as 'goal' "
        "('pics'|'code'|'both'); for 'code' the Base.xml questions are skipped." +
        goal_note +
        " HUMAN-IN-THE-LOOP: do NOT decide the optional capabilities yourself. "
        f"Present the {primary} PRIMARY questions (priority=='primary' -- the "
        "optional features and cluster sides, the capabilities a product owner "
        "recognises) to the human, grouped by endpoint and cluster, and ask which "
        "their device supports. WAIT for their answers, record each YES in "
        "'selected', then call generate. SECONDARY items default to off -- raise "
        "them only if the human asks or a validator 'error' problem requires one. "
        "Never generate with capabilities silently defaulted.")
    return {"summary": summary, "groups": groups, "questions": questions}


@mcp.tool()
def list_matter_versions() -> dict:
    """List the Matter spec versions this generator supports.

    Returns ``{"versions": ["1.4", "1.4.1", ...]}``. Pick one for the
    ``spec_version`` field of a selection.
    """
    return {"versions": service.list_versions()}


@mcp.tool()
def list_device_types(version: str) -> dict:
    """List the application device-type names available for a Matter ``version``.

    Returns ``{"version": ..., "device_types": ["Extended Color Light", ...]}``.
    Use these exact names in a selection's ``endpoints[].device_types``.
    """
    return {"version": version, "device_types": service.list_device_types(version)}


@mcp.tool()
def get_selection_questions(selection: dict, selected: dict | None = None,
                            goal: str = "both") -> dict:
    """Return the OPTIONAL yes/no questions a human must decide for a selection.

    ``selection`` is the canonical dict, e.g.::

        {"spec_version": "1.6", "transport": ["wifi_2g"], "role": "commissionee",
         "endpoints": [{"device_types": ["Extended Color Light"]}]}

    ``selected`` is the answers-so-far map ``{tab: [pics_code, ...]}`` (tab
    "base" = node/MCORE, "1".. = application endpoints); omit or ``{}`` on the
    first call.

    FIRST ask the human what they want and pass it as ``goal``: ``"pics"`` (PICS
    XML files), ``"code"`` (esp-matter data-model code only), or ``"both"``. When
    ``goal=="code"`` the node/Base.xml questions are omitted -- they shape the
    PICS, not the code -- so you only ask about endpoint capabilities.

    Returns ``{"summary": {...}, "groups": [...], "questions": [...]}``.

    THIS TOOL EXISTS TO PUT DECISIONS TO A HUMAN. You must not answer the optional
    capability questions yourself, pick "mandatory-only", or generate with the
    defaults and offer to amend later. The human owns these product facts -- only
    they know whether the device supports Night Vision, a Speaker, MotionLatching,
    etc.

    Required flow:
      1. Read ``summary.how_to_ask`` and ``summary.counts`` (``primary`` = the
         capability questions you MUST ask).
      2. Walk ``groups`` -- one entry per tab (node "base" tab + each endpoint),
         each with ``clusters``; each question has a ``kind`` and a ``priority``.
         Present EVERY ``priority=="primary"`` question (optional features and
         cluster sides), grouped by endpoint/cluster, and ask the human which
         their device supports. Cover every tab -- do not stop after one cluster.
      3. WAIT for the human's answers. For each YES, append that question's
         ``code`` to ``selected[question["tab"]]``.
      4. ``priority=="secondary"`` items (attributes/commands/events, node
         product-facts) default to OFF -- raise them only if the human brings them
         up. Do not silently enable or disable them on the human's behalf.

    Mandatory items -- and the elements a feature makes mandatory once enabled --
    are resolved automatically and never appear here, so the set is only genuine
    choices. Re-callable: pass the growing ``selected`` back to reveal any optional
    sub-questions a just-enabled feature unlocks. Call ``generate`` ONLY once the
    human has answered the primary questions.
    """
    res = service.selection_questions(selection, selected)
    questions = res["questions"]
    if goal == "code":
        # Base.xml/MCORE items are node-level PICS facts; they do not affect the
        # generated data-model code, so don't ask about them for a code-only goal.
        questions = [q for q in questions if q["tab"] != "base"]
    return _grouped({"summary": res["summary"], "questions": questions}, goal)


@mcp.tool()
def generate(selection: dict, selected: dict | None = None,
             target: str = "esp_matter", goal: str = "both") -> dict:
    """Generate the PICS XML files and/or the data-model code for a selection.

    Call this ONLY after ``get_selection_questions`` and after the human has
    answered the primary (feature/cluster-side) questions -- ``selected`` must
    reflect their actual answers, not your own defaults. Do not call generate to
    "get something" and offer to regenerate later; that skips the human decision
    this workflow exists for.

    ``selected`` is the human's optional YES answers (``{tab: [codes]}``) gathered
    via ``get_selection_questions``. ``target`` selects the code output
    (default ``"esp_matter"``). ``goal`` selects the outputs and MUST match the
    ``goal`` you asked the human and used for ``get_selection_questions``:
    ``"pics"``, ``"code"``, or ``"both"`` (default).

    Returns::

        {"target": ..., "goal": ...,
         "pics_files": {"endpoint0/....xml": "<xml>", ...},   # {} when goal=="code"
         "code": {"snippet": "<C++ to paste into app_main()>",
                  "file": "app_data_model.cpp", "exact": bool,
                  "knowledge_source": "...", "endpoints": [...]} | None,  # None when goal=="pics"
         "problems": [{"code","name","why","severity","tab"}, ...]}       # [] when goal=="code"

    ``problems`` is the PICS spec check: an empty list (or only ``severity``
    "warning") means the selection is clean. Fix any "error" problems by enabling
    the named code (append it to ``selected``) and regenerating.
    """
    return service.generate(selection, selected, target, goal)


def main() -> None:
    mcp.run()   # stdio transport


if __name__ == "__main__":
    main()
