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
"""Render the esp-matter data-model construction snippet from a Selection.

Emits ``node::create`` (Root Node on EP0) plus, for each application endpoint,
``endpoint::<device_type>::create`` -- with default config -- and, for composed
endpoints, ``endpoint::<type>::add`` for the extra device types. Optional PICS
claims (features / sides) are surfaced as precise ``// TODO`` guidance: whether a
given ``feature::add`` takes a config is esp-matter-specific and not derivable
from the data model, so we name the exact call rather than emit maybe-wrong code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import jinja2
from esp_matter_datamodel.model.elements import DataModel

from ..claims import FEATURE_CODE_RE, GATEWAY_RE, pics_to_cluster
from .naming import esp_name

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
ROOT_NODE = "Root Node"


@dataclass
class DeviceTypeInfo:
    name: str          # canonical spec name, e.g. "Extended Color Light"
    namespace: str     # esp-matter C++ namespace, e.g. "extended_color_light"
    id: str            # canonical 0xXXXX id
    baseline_cluster_ids: set[str] = field(default_factory=set)


@dataclass
class OptionalFeature:
    cluster_name: str
    cluster_namespace: str
    cluster_id: str
    feature_name: str
    feature_namespace: str


@dataclass
class EndpointScaffold:
    endpoint: int
    primary: DeviceTypeInfo
    composed: list[DeviceTypeInfo] = field(default_factory=list)
    optional_features: list[OptionalFeature] = field(default_factory=list)
    optional_sides: list[str] = field(default_factory=list)   # human notes for X.S/X.C claims

    @property
    def device_types(self) -> list[str]:
        return [self.primary.name] + [c.name for c in self.composed]


@dataclass
class ScaffoldResult:
    """The construction snippet plus a structured description of what it builds."""

    snippet: str
    file: str | None = None
    endpoints: list[EndpointScaffold] = field(default_factory=list)

    @property
    def device_type_name(self) -> str:
        return self.endpoints[0].primary.name if self.endpoints else ""

    @property
    def device_namespace(self) -> str:
        return self.endpoints[0].primary.namespace if self.endpoints else ""


def _resolve_device_type(model: DataModel, name: str) -> DeviceTypeInfo:
    dt = model.device_type_by_name(name)
    if dt is None:
        raise ValueError(
            f"device type {name!r} not found in the {model.spec_version} data model")
    # esp-matter's endpoint::<type>::create() builds the device type's own server
    # clusters PLUS the Base Device Type's (Descriptor, Binding, ...).
    baseline = set(dt.server_clusters.keys())
    if model.base_device_type is not None:
        baseline |= set(model.base_device_type.server_clusters.keys())
    return DeviceTypeInfo(dt.name, esp_name(dt.name), dt.id, baseline)


def _optionals(model: DataModel, claims, baseline_cluster_ids: set[str]):
    """Split an endpoint's claims into optional features and side notes."""
    clusters_by_pics = pics_to_cluster(model)
    features: list[OptionalFeature] = []
    sides: list[str] = []
    for code in claims or []:
        fm = FEATURE_CODE_RE.match(code)
        if fm:
            cid = clusters_by_pics.get(fm.group("pics"))
            if cid is None:
                continue
            cluster = model.clusters[cid]
            bit = int(fm.group("bit"), 16)
            feat = cluster.features.get(bit)
            if feat is None:
                continue
            features.append(OptionalFeature(
                cluster_name=cluster.name, cluster_namespace=esp_name(cluster.name),
                cluster_id=cid, feature_name=feat.name,
                feature_namespace=esp_name(feat.name)))
            continue
        gm = GATEWAY_RE.match(code)
        if gm:
            cid = clusters_by_pics.get(gm.group("pics"))
            name = model.clusters[cid].name if cid else gm.group("pics")
            role = "client" if gm.group("side") == "C" else "server"
            if cid is None or cid not in baseline_cluster_ids or role == "client":
                sides.append(f"{name} ({role} side, {code})")
    return features, sides


def _environment() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
    )


def generate_scaffold(selection, model: DataModel,
                      output_dir: str | Path | None = None) -> ScaffoldResult:
    """Build the data-model construction snippet for ``selection``.

    ``selection`` is a :class:`pics_tool.generate.selection.Selection`. If
    ``output_dir`` is given, the snippet is also written to
    ``<output_dir>/app_data_model.cpp``.
    """
    endpoints: list[EndpointScaffold] = []
    for epid, ep in enumerate(selection.endpoints, start=1):
        dts = [_resolve_device_type(model, name) for name in ep.device_types]
        baseline: set[str] = set()
        for dt in dts:
            baseline |= dt.baseline_cluster_ids
        features, sides = _optionals(model, ep.claims, baseline)
        endpoints.append(EndpointScaffold(
            endpoint=epid, primary=dts[0], composed=dts[1:],
            optional_features=features, optional_sides=sides))

    snippet = _environment().get_template("data_model_snippet.jinja").render(
        endpoints=endpoints)

    written: str | None = None
    if output_dir is not None:
        out = Path(output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        dst = out / "app_data_model.cpp"
        dst.write_text(snippet, encoding="utf-8")
        written = str(dst)

    return ScaffoldResult(snippet=snippet, file=written, endpoints=endpoints)
