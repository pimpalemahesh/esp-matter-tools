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


def known_codes(version: str = "1.6") -> frozenset[str]:
    """Every claimable PICS item number for ``version`` (template-backed)."""
    from .generate.template_io import known_item_numbers

    return known_item_numbers(version)


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
    live decision the human must make -- a genuine optional item that applies
    right now (the engine's ``needs_you`` set). Everything the tool can derive on
    its own is auto-included and NOT returned here: mandatory items, and the
    elements a feature/cluster-side mandates once it is enabled.

    Re-callable: pass the growing ``selected`` back to reveal the optional
    sub-questions a just-enabled feature unlocks (progressive disclosure, driven
    by the engine). To accept a question, append its ``code`` to
    ``selected[<its tab>]``.
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
            # short human label (element/boilerplate-stripped name); the full
            # question rides along for context
            "label": item.get("name") or item.get("question") or item["code"],
            "question": item.get("question") or item["code"],
            "suggested": item.get("answer", "no"),
            "why": item.get("why", ""),
            "conformance": item.get("conformance", ""),
        }
        for item in payload["items"]
        # mirrored DNS-SD twins are ONE decision: only the lead item is asked
        # (answering it claims both codes -- see claims.MCORE_MIRRORS)
        if item.get("needs_you") and not item.get("mirror_of")
    ]
    summary = {
        "spec_version": payload["spec_version"],
        "endpoints": [
            {"tab": t["id"], "label": t["label"], "caption": t["caption"]}
            for t in payload["tabs"]
        ],
        # to_decide counts DECISIONS (mirrored twins fold into their lead), so
        # it always equals len(questions)
        "counts": {
            "auto_included": payload["counts"]["yes"],
            "to_decide": len(questions),
        },
    }
    return {"summary": summary, "questions": questions}


# ---- generate ------------------------------------------------------------------


def generate(
    selection: dict,
    selected: dict | None = None,
    target: str = "esp_matter",
    goal: str = "both",
) -> dict:
    """Produce the PICS files and/or the data-model code for a finished selection.

    ``selected`` is the human's optional Yes answers (``{tab:[codes]}``). ``goal``
    selects the outputs: ``"pics"`` (PICS XML + spec-check), ``"code"`` (esp-matter
    data-model code only), or ``"both"`` (default). Returns
    ``{"target", "goal", "pics_files": {path: xml}, "code": {snippet, file, exact,
    knowledge_source, endpoints} | None, "problems": [...]}``. Keys not produced for
    the chosen ``goal`` are empty (``pics_files == {}`` / ``problems == []`` /
    ``code is None``). ``problems`` is the PICS spec-check (empty == clean); each
    has ``severity`` "error"/"warning".
    """
    if target not in list_targets():
        raise ValueError(f"unknown target {target!r}; available: {list_targets()}")
    if goal not in ("pics", "code", "both"):
        raise ValueError(f"unknown goal {goal!r}; use 'pics', 'code' or 'both'")
    selected = selected or {}
    selection = selection or {}

    out: dict = {
        "target": target,
        "goal": goal,
        "pics_files": {},
        "code": None,
        "problems": [],
    }
    if goal in ("pics", "both"):
        # Full Yes set (mandatory + the human's optional choices) drives PICS + the
        # spec-check. Base.xml/MCORE answers matter here (they ARE the node PICS).
        payload = webapp.generate_payload(_with_claims(selection, selected))
        enabled = _enabled_by_tab(payload)
        out["pics_files"] = webapp.export_pics_files(selection, enabled)
        out["problems"] = webapp.validate_selection(selection, enabled)
    if goal in ("code", "both"):
        # The code generator takes only the optional endpoint claims (it derives
        # the baseline); node/Base.xml answers do not affect it.
        out["code"] = webapp.generate_scaffold_files(selection, selected)
    return out


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

    return write_pics(
        selection.profile.spec_version,
        build_endpoints_enabled(model, selection),
        output_dir,
    )


def scaffold_for_selection(selection, model, output_dir=None, knowledge=None):
    """The esp-matter data-model code for a resolved ``Selection`` (``ScaffoldResult``).

    ``knowledge`` (e.g. a live component from ``--esp-matter-path``) overrides the
    bundled signatures; ``None`` uses the bundled/nearest map for the version.
    """
    from .generate.scaffold import generate_scaffold

    return generate_scaffold(selection, model, output_dir, knowledge=knowledge)
