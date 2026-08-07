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
def get_selection_questions(selection: dict, selected: dict | None = None) -> dict:
    """Return the OPTIONAL yes/no questions a human must decide for a selection.

    ``selection`` is the canonical dict, e.g.::

        {"spec_version": "1.6", "transport": ["wifi_2g"], "role": "commissionee",
         "endpoints": [{"device_types": ["Extended Color Light"]}]}

    ``selected`` is the answers-so-far map ``{tab: [pics_code, ...]}`` (tab
    "base" = node/MCORE, "1".. = application endpoints); omit or ``{}`` on the
    first call.

    Returns ``{"summary": {...}, "questions": [...]}``. Present each question's
    ``question`` (and ``why``) to the human. For every YES, append that question's
    ``code`` to ``selected[question["tab"]]``. Only items the tool can't decide on
    its own are returned; mandatory items are auto-included by ``generate``.

    Re-callable: pass the updated ``selected`` back to reveal sub-questions that a
    just-enabled feature unlocks. When there are no more questions the human cares
    about, call ``generate``.
    """
    return service.selection_questions(selection, selected)


@mcp.tool()
def generate(selection: dict, selected: dict | None = None,
             target: str = "esp_matter") -> dict:
    """Generate the PICS XML files AND the data-model code for a finished selection.

    ``selected`` is the human's optional YES answers (``{tab: [codes]}``) gathered
    via ``get_selection_questions``. ``target`` selects the code output
    (default ``"esp_matter"``).

    Returns::

        {"target": ...,
         "pics_files": {"endpoint0/....xml": "<xml>", ...},
         "code": {"snippet": "<C++ to paste into app_main()>",
                  "file": "app_data_model.cpp", "exact": bool,
                  "knowledge_source": "...", "endpoints": [...]},
         "problems": [{"code","name","why","severity","tab"}, ...]}

    ``problems`` is the spec check: an empty list (or only ``severity`` "warning")
    means the selection is clean. Fix any "error" problems by enabling the named
    code (append it to ``selected``) and regenerating.
    """
    return service.generate(selection, selected, target)


def main() -> None:
    mcp.run()   # stdio transport


if __name__ == "__main__":
    main()
