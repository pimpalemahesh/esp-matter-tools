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
"""Target-neutral intermediate representation (IR): *what* to build.

This is the only contract between selection sources (PICS today) and code
targets (esp_matter today). Everything is by SPEC identity + spec name -- no
C++ namespaces or types, no PICS codes -- so a new input source or a new output
target can be added without touching the other side.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ElementRef:
    """An optional element enabled beyond the device-type baseline.

    Spec identity + spec name only; the target maps this to its own naming.
    ``id`` is the element's spec id (feature bit as hex, or ``0xNNNN`` for
    attributes/commands/events) -- kept for future knowledge lookups.
    """

    cluster_id: str
    cluster_name: str
    id: str
    name: str


@dataclass
class ClusterSide:
    """A whole cluster added by SIDE (server/client) beyond the device baseline."""

    cluster_id: str
    cluster_name: str
    server: bool = False
    client: bool = False


@dataclass
class EndpointPlan:
    """One endpoint: its device type(s) plus every optional addition on it.

    ``device_types`` is spec names, primary first then any composed types.
    Optional additions are kept in claim order and split by kind so the target
    can render them deterministically.
    """

    index: int
    device_types: list[str]
    features: list[ElementRef] = field(default_factory=list)
    attributes: list[ElementRef] = field(default_factory=list)
    commands: list[ElementRef] = field(default_factory=list)
    events: list[ElementRef] = field(default_factory=list)
    sides: list[ClusterSide] = field(default_factory=list)
    unknown_sides: list[str] = field(
        default_factory=list
    )  # unresolvable side claims (notes)


@dataclass
class DataModelPlan:
    """The full construction plan for a node: spec version + its endpoints."""

    spec_version: str
    endpoints: list[EndpointPlan] = field(default_factory=list)
