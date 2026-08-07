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
"""Build the esp_matter capability map (a SIGNATURE INDEX) from a released
component's ``data_model/`` headers.

Maintainer-side only (never runs in Pyodide): parse the clean C++ prototypes in
``esp_matter_{feature,attribute,command,event}.h`` into
``{symbol -> {returns, params:[{type,name}]}}`` where ``symbol`` is the C++
namespace-qualified callable, e.g. ``cluster::on_off::feature::lighting::add``,
``cluster::level_control::attribute::create_on_transition_time``.

The schema is a flat signature index on purpose (see the architecture plan): new
API surface is absorbed as more params/symbols, never a schema change. The parser
is a dependency-free brace-depth namespace scanner -- no libclang.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_HEADERS = ("esp_matter_feature.h", "esp_matter_attribute.h",
            "esp_matter_command.h", "esp_matter_event.h")

_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_COMMENT_LINE = re.compile(r"//[^\n]*")

# Single left-to-right scan: namespace-open (consumes its own '{'), a lone brace,
# a closing brace, or a target free-function declaration (add / create_*).
_TOK = re.compile(
    r"namespace\s+(?P<ns>\w+)\s*\{"
    r"|(?P<open>\{)"
    r"|(?P<close>\})"
    r"|(?P<ret>esp_err_t|attribute_t\s*\*|command_t\s*\*|event_t\s*\*)\s*"
    r"(?P<fn>add|create_\w+)\s*\((?P<args>[^)]*)\)\s*;",
    re.S)

_NAME_RE = re.compile(r"([A-Za-z_]\w*)\s*$")
_INT_TYPE = re.compile(r"^u?int(?:8|16|32|64)_t$")


def _strip_comments(text: str) -> str:
    return _COMMENT_LINE.sub("", _COMMENT_BLOCK.sub("", text))


def _norm_type(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*\*", "*", t)     # "cluster_t *" -> "cluster_t*"
    t = re.sub(r"\s*&", "&", t)
    return t


def _split_params(args: str) -> list[str]:
    """Split a parameter list on top-level commas (respecting <> and ())."""
    parts, depth, cur = [], 0, ""
    for ch in args:
        if ch in "<(":
            depth += 1
        elif ch in ">)":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def _parse_param(p: str) -> dict:
    p = p.split("=", 1)[0].strip()          # drop any default value
    m = _NAME_RE.search(p)
    if not m or not p[:m.start()].strip():   # unnamed param -> whole thing is the type
        return {"type": _norm_type(p), "name": ""}
    return {"type": _norm_type(p[:m.start()]), "name": m.group(1)}


def _parse_header(text: str, symbols: dict) -> None:
    text = _strip_comments(text)
    stack: list[str | None] = []             # namespace names; None for struct/other braces
    for m in _TOK.finditer(text):
        if m.group("ns") is not None:
            stack.append(m.group("ns"))
        elif m.group("open"):
            stack.append(None)
        elif m.group("close"):
            if stack:
                stack.pop()
        elif m.group("fn"):
            path = [x for x in stack if x]
            if len(path) < 2 or path[0] != "esp_matter":
                continue
            symbol = "::".join(path[1:] + [m.group("fn")])   # drop the esp_matter root
            symbols[symbol] = {
                "returns": _norm_type(m.group("ret")),
                "params": [_parse_param(p) for p in _split_params(m.group("args"))],
            }


def find_data_model(root: str | Path) -> Path | None:
    """Locate the esp_matter ``data_model/`` headers under a component/SDK path.

    Accepts the data_model dir itself, a component root
    (``components/esp_matter/data_model``), or an esp-matter SDK checkout.
    """
    root = Path(root).expanduser()
    for cand in (root, root / "data_model",
                 root / "components" / "esp_matter" / "data_model"):
        if (cand / "esp_matter_feature.h").is_file():
            return cand
    for hit in root.rglob("esp_matter_feature.h"):
        return hit.parent
    return None


def build_index(data_model_dir: str | Path, component_version: str) -> dict:
    """Parse the component's data_model headers into the capability map dict.

    Handles both esp-matter layouts: the monolithic
    ``esp_matter_{feature,attribute,command,event}.h`` (released components through
    1.5.x) AND the per-cluster ``generated/clusters/<ns>/<ns>.h`` files (esp-matter
    ``main`` / newer). Both use the same ``esp_matter::cluster::<ns>::...`` nesting,
    so the same scanner feeds one symbol index.
    """
    dm = Path(data_model_dir).expanduser()
    symbols: dict[str, dict] = {}
    for header in _HEADERS:
        path = dm / header
        if path.is_file():
            _parse_header(path.read_text(encoding="utf-8", errors="ignore"), symbols)
    generated = dm / "generated" / "clusters"
    if generated.is_dir():
        for path in sorted(generated.rglob("*.h")):
            _parse_header(path.read_text(encoding="utf-8", errors="ignore"), symbols)
    return {"component_version": component_version, "symbols": symbols}


def write_caps(data_model_dir: str | Path, out_path: str | Path,
               component_version: str) -> int:
    """Build and write ``caps_<ver>.json``; returns the symbol count."""
    index = build_index(data_model_dir, component_version)
    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return len(index["symbols"])
