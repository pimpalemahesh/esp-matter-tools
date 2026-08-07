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
"""Consumer-neutral service facade -- the single driving port.

The CLI, the Web UI (via ``webapp.py``'s Pyodide ``*_json`` wrappers), and the MCP
server all go through these functions, so every consumer gets identical behaviour.
Everything is plain data in / plain data out (dicts and lists -- no JSON strings,
no browser assumptions). It is a thin layer over the engine operations in
``webapp.py``; it adds no logic of its own beyond shaping inputs/outputs.

Two small objects flow through every call:

* ``selection`` -- the canonical Selection dict::

      {"spec_version": "1.6", "transport": ["wifi_2g"], "role": "commissionee",
       "endpoints": [{"device_types": ["Extended Color Light"]}], ...}

* ``selected`` -- ``{tab: [pics_code, ...]}`` the *optional* items a human turned
  ON, keyed by tab (``"base"`` = node/MCORE, ``"1"``.. = application endpoints).
  This is the engine's native ``claims_by_tab`` / ``enabled_codes`` channel, so it
  threads straight through unchanged.
"""

from __future__ import annotations

from . import webapp


# ---- discovery -----------------------------------------------------------------

def list_versions() -> list[str]:
    """Matter spec versions this tool can generate for."""
    return webapp.list_versions()


def list_device_types(version: str = "1.6") -> list[str]:
    """Application device-type names available for ``version``."""
    return webapp.list_device_types(version)


def list_targets() -> list[str]:
    """Code-generation output targets (e.g. ``["esp_matter"]``)."""
    from .generate.codegen import list_targets as _list_targets
    return _list_targets()


# ---- helpers -------------------------------------------------------------------

def _with_claims(selection: dict, selected: dict | None) -> dict:
    """A copy of ``selection`` carrying the human's optional answers as the
    engine's ``claims_by_tab`` (drops ``None``/empty cleanly)."""
    prof = dict(selection or {})
    if selected:
        prof["claims_by_tab"] = selected
    return prof


def _enabled_by_tab(payload: dict) -> dict:
    """The FULL set of Yes codes per tab (mandatory pre-filled + optional turned
    on) from a generated payload -- what the PICS writer/validator consume."""
    out: dict[str, list[str]] = {}
    for item in payload["items"]:
        if item.get("answer") == "yes":
            out.setdefault(item["tab"], []).append(item["code"])
    return out


# ---- the human-in-the-loop questions surface -----------------------------------

def selection_questions(selection: dict, selected: dict | None = None) -> dict:
    """Optional items a *human* must decide for this selection.

    Returns ``{"summary": {...}, "questions": [...]}`` where each question is a
    yes/no the tool could not derive on its own (the engine's ``needs_you`` set).
    Mandatory items are auto-included and NOT returned here.

    Re-callable: pass the growing ``selected`` back to reveal the sub-questions a
    just-enabled feature unlocks (progressive disclosure). To accept a question,
    append its ``code`` to ``selected[<its tab>]``.
    """
    payload = webapp.generate_payload(_with_claims(selection, selected))
    labels = {t["id"]: t["label"] for t in payload["tabs"]}

    questions = [
        {
            "id": f"{item['tab']}|{item['code']}",
            "tab": item["tab"],
            "endpoint": labels.get(item["tab"], item["tab"]),
            "cluster": item.get("cluster", ""),
            "code": item["code"],
            "question": item.get("question") or item["code"],
            "suggested": item.get("answer", "no"),
            "why": item.get("why", ""),
            "conformance": item.get("conformance", ""),
        }
        for item in payload["items"] if item.get("needs_you")
    ]
    summary = {
        "spec_version": payload["spec_version"],
        "endpoints": [{"tab": t["id"], "label": t["label"], "caption": t["caption"]}
                      for t in payload["tabs"]],
        "counts": {"auto_included": payload["counts"]["yes"],
                   "to_decide": payload["counts"]["needs_you"]},
    }
    return {"summary": summary, "questions": questions}


# ---- generate ------------------------------------------------------------------

def generate(selection: dict, selected: dict | None = None,
             target: str = "esp_matter") -> dict:
    """Produce the PICS files AND the data-model code for a finished selection.

    ``selected`` is the human's optional Yes answers (``{tab:[codes]}``). Returns
    ``{"target", "pics_files": {path: xml}, "code": {snippet, file, exact,
    knowledge_source, endpoints}, "problems": [...]}``. ``problems`` is the
    spec-check (empty == clean); each has ``severity`` "error"/"warning".
    """
    if target not in list_targets():
        raise ValueError(f"unknown target {target!r}; available: {list_targets()}")
    selected = selected or {}
    selection = selection or {}

    # Full Yes set (mandatory + the human's optional choices) drives PICS + check;
    # the code generator takes only the optional claims (it derives the baseline).
    payload = webapp.generate_payload(_with_claims(selection, selected))
    enabled = _enabled_by_tab(payload)

    return {
        "target": target,
        "pics_files": webapp.export_pics_files(selection, enabled),
        "code": webapp.generate_scaffold_files(selection, selected),
        "problems": webapp.validate_selection(selection, enabled),
    }


# ---- Selection-object API (the CLI drives this) --------------------------------
# The CLI resolves richer inputs (profile/flags/selection files, a custom
# ``--model`` data model, and a ``--esp-matter-path`` live component) into a
# ``Selection`` object; these entry points keep that path here so the CLI, like
# the UI and MCP, goes through this one facade. Both APIs bottom out in the same
# engines (``generate_cluster_pics`` / ``compute_mcore_pics`` / ``generate_scaffold``).

def pics_for_selection(selection, model, output_dir: str):
    """Write per-endpoint PICS XML for a resolved ``Selection``; return the summary."""
    from .generate.selection import build_endpoints_enabled
    from .generate.writer import write_pics
    return write_pics(selection.profile.spec_version,
                      build_endpoints_enabled(model, selection), output_dir)


def scaffold_for_selection(selection, model, output_dir=None, knowledge=None):
    """The esp-matter data-model code for a resolved ``Selection`` (``ScaffoldResult``).

    ``knowledge`` (e.g. a live component from ``--esp-matter-path``) overrides the
    bundled signatures; ``None`` uses the bundled/nearest map for the version.
    """
    from .generate.scaffold import generate_scaffold
    return generate_scaffold(selection, model, output_dir, knowledge=knowledge)
