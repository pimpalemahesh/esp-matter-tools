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
"""The esp_matter Knowledge port: what the target asks about the component API.

``BundledKnowledge`` reads the committed ``data/caps_<ver>.json`` signature index
(works in Pyodide -- no filesystem/component needed). A future
``ComponentKnowledge`` (P3) will parse a live component the same way. The target
consults ``symbol(name)`` to bind call arguments; ``None`` means "unknown" and the
target degrades to a placeholder, so missing data never yields wrong code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib.resources import files


@dataclass
class Param:
    type: str
    name: str = ""


@dataclass
class Signature:
    returns: str
    params: list[Param] = field(default_factory=list)


class Knowledge:
    """Port interface. A source of esp_matter API signatures."""

    version: str = ""
    source_label: str = ""

    def symbol(self, name: str) -> Signature | None:
        return None


class BundledKnowledge(Knowledge):
    """Signatures from a committed caps_<ver>.json shipped with the tool."""

    def __init__(self, version: str, symbols: dict, component_version: str):
        self.version = version
        self._symbols = symbols
        self.component_version = component_version
        self.source_label = f"bundled esp_matter {component_version}"

    def symbol(self, name: str) -> Signature | None:
        s = self._symbols.get(name)
        if s is None:
            return None
        return Signature(returns=s.get("returns", ""),
                         params=[Param(p.get("type", ""), p.get("name", ""))
                                 for p in s.get("params", [])])


class ComponentKnowledge(BundledKnowledge):
    """Signatures parsed from a LIVE esp_matter component on disk (CLI opt-in).

    Lets the CLI generate exact code against the developer's actual checkout --
    including ``main`` / unreleased / forked components -- for which no bundled
    caps exist.
    """

    def __init__(self, data_model_dir, version: str = "component"):
        from .caps_build import build_index
        index = build_index(data_model_dir, "component")
        super().__init__(version, index["symbols"], "component")
        self.source_label = f"live component ({data_model_dir})"


def from_component(path, version: str = "component") -> ComponentKnowledge:
    """Build ``ComponentKnowledge`` from a component/SDK path (resolves data_model/)."""
    from .caps_build import find_data_model
    dm = find_data_model(path)
    if dm is None:
        raise ValueError(f"no esp_matter data_model headers found under {path!r}")
    return ComponentKnowledge(dm, version)


_CAPS_RE = re.compile(r"caps_(.+)\.json$")

# Parsed caps payloads cached (immutable at runtime); a miss is NOT cached, so a
# lazily-fetched per-version caps file is picked up once it lands in the FS.
_CACHE: dict[str, tuple | None] = {}


def _version_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def _data_dir():
    return files("pics_tool.generate.codegen.targets.esp_matter").joinpath("data")


def _read(version: str):
    """(symbols, component_version, nearest_for) for a version, or None if absent."""
    if version in _CACHE:
        return _CACHE[version]
    try:
        res = _data_dir().joinpath(f"caps_{version}.json")
    except (ModuleNotFoundError, FileNotFoundError):
        return None
    if not res.is_file():
        return None
    data = json.loads(res.read_text(encoding="utf-8"))
    tup = (data.get("symbols", {}), data.get("component_version", version),
           data.get("nearest_for"))
    _CACHE[version] = tup
    return tup


def available_versions() -> list[str]:
    """Versions with a committed caps file present in the package (sorted)."""
    try:
        names = [f.name for f in _data_dir().iterdir()]
    except (ModuleNotFoundError, FileNotFoundError, NotADirectoryError):
        return []
    vs = [m.group(1) for n in names if (m := _CAPS_RE.match(n))]
    return sorted(vs, key=_version_key)


def _make(version: str, tup, *, nearest_for: str | None = None) -> BundledKnowledge:
    symbols, compver, own_nf = tup
    kb = BundledKnowledge(version, symbols, compver)
    nf = nearest_for or own_nf
    if nf:
        kb.source_label = f"bundled esp_matter {compver} (nearest; no {nf} component)"
    return kb


def load_bundled(version: str) -> BundledKnowledge | None:
    """The committed capability map for exactly ``version``, or None if not shipped."""
    tup = _read(version)
    return _make(version, tup) if tup is not None else None


def load_nearest(version: str) -> BundledKnowledge | None:
    """Caps for ``version`` if present, else the nearest lower shipped version's
    caps (labeled as a nearest fallback). None only if no caps ship at all."""
    own = load_bundled(version)
    if own is not None:
        return own
    avail = available_versions()
    if not avail:
        return None
    key = _version_key(version)
    lower = [v for v in avail if _version_key(v) <= key]
    pick = max(lower or avail, key=_version_key)
    tup = _read(pick)
    return _make(version, tup, nearest_for=version) if tup is not None else None
