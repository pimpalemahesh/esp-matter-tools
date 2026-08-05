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
"""Typed, in-memory representation of the Matter data model.

These dataclasses mirror the JSON contract (``schema/datamodel.schema.json``)
one-to-one and carry ``from_json`` / ``to_json`` so the model round-trips
losslessly. They are tool-neutral: no PICS (or any other tool) concept appears
here — this is *the Matter data model*, nothing more.

Collections are keyed for O(1) lookup, matching how consumers access them:
clusters/device-types by canonical ``0xXXXX`` id, attributes/commands/events by
id, features by integer bit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .conformance import Conformance, conformance_from_json, conformance_to_json

SCHEMA_VERSION = "1.0.0"


@dataclass
class Feature:
    bit: int
    mask: int
    code: str
    name: str
    conformance: Conformance

    @classmethod
    def from_json(cls, d: dict) -> "Feature":
        return cls(
            bit=d["bit"],
            mask=d["mask"],
            code=d["code"],
            name=d["name"],
            conformance=conformance_from_json(d["conformance"]),
        )

    def to_json(self) -> dict:
        return {
            "bit": self.bit,
            "mask": self.mask,
            "code": self.code,
            "name": self.name,
            "conformance": conformance_to_json(self.conformance),
        }


@dataclass
class Attribute:
    id: str
    name: str
    conformance: Conformance

    @classmethod
    def from_json(cls, d: dict) -> "Attribute":
        return cls(id=d["id"], name=d["name"],
                   conformance=conformance_from_json(d["conformance"]))

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name,
                "conformance": conformance_to_json(self.conformance)}


@dataclass
class Command:
    id: str
    name: str
    conformance: Conformance

    @classmethod
    def from_json(cls, d: dict) -> "Command":
        return cls(id=d["id"], name=d["name"],
                   conformance=conformance_from_json(d["conformance"]))

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name,
                "conformance": conformance_to_json(self.conformance)}


@dataclass
class Event:
    id: str
    name: str
    priority: str | None
    conformance: Conformance

    @classmethod
    def from_json(cls, d: dict) -> "Event":
        return cls(id=d["id"], name=d["name"], priority=d.get("priority"),
                   conformance=conformance_from_json(d["conformance"]))

    def to_json(self) -> dict:
        out: dict = {"id": self.id, "name": self.name,
                     "conformance": conformance_to_json(self.conformance)}
        if self.priority is not None:
            out["priority"] = self.priority
        return out


def _map_from_json(container: dict, ctor, key: str) -> dict:
    return {k: ctor(v) for k, v in container.items()} if container else {}


def _map_to_json(mapping: dict) -> dict:
    return {k: v.to_json() for k, v in mapping.items()}


@dataclass
class Cluster:
    id: str
    name: str
    pics: str
    revision: int
    features: dict[int, Feature] = field(default_factory=dict)
    attributes: dict[str, Attribute] = field(default_factory=dict)
    accepted_commands: dict[str, Command] = field(default_factory=dict)
    generated_commands: dict[str, Command] = field(default_factory=dict)
    events: dict[str, Event] = field(default_factory=dict)

    @classmethod
    def from_json(cls, d: dict) -> "Cluster":
        return cls(
            id=d["id"],
            name=d["name"],
            pics=d.get("pics", ""),
            revision=d["revision"],
            features={int(k): Feature.from_json(v) for k, v in d.get("features", {}).items()},
            attributes={k: Attribute.from_json(v) for k, v in d.get("attributes", {}).items()},
            accepted_commands={k: Command.from_json(v)
                               for k, v in d.get("accepted_commands", {}).items()},
            generated_commands={k: Command.from_json(v)
                                for k, v in d.get("generated_commands", {}).items()},
            events={k: Event.from_json(v) for k, v in d.get("events", {}).items()},
        )

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "pics": self.pics,
            "revision": self.revision,
            "features": {str(k): v.to_json() for k, v in self.features.items()},
            "attributes": _map_to_json(self.attributes),
            "accepted_commands": _map_to_json(self.accepted_commands),
            "generated_commands": _map_to_json(self.generated_commands),
            "events": _map_to_json(self.events),
        }


@dataclass
class ClusterRequirement:
    """A cluster required by a device type, with any element overrides."""

    id: str
    name: str
    conformance: Conformance
    feature_overrides: dict[int, Conformance] = field(default_factory=dict)
    attribute_overrides: dict[str, Conformance] = field(default_factory=dict)
    command_overrides: dict[str, Conformance] = field(default_factory=dict)

    @classmethod
    def from_json(cls, d: dict) -> "ClusterRequirement":
        return cls(
            id=d["id"],
            name=d["name"],
            conformance=conformance_from_json(d["conformance"]),
            feature_overrides={int(k): conformance_from_json(v["conformance"])
                               for k, v in d.get("feature_overrides", {}).items()},
            attribute_overrides={k: conformance_from_json(v["conformance"])
                                 for k, v in d.get("attribute_overrides", {}).items()},
            command_overrides={k: conformance_from_json(v["conformance"])
                               for k, v in d.get("command_overrides", {}).items()},
        )

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "conformance": conformance_to_json(self.conformance),
            "feature_overrides": {str(k): {"conformance": conformance_to_json(v)}
                                  for k, v in self.feature_overrides.items()},
            "attribute_overrides": {k: {"conformance": conformance_to_json(v)}
                                    for k, v in self.attribute_overrides.items()},
            "command_overrides": {k: {"conformance": conformance_to_json(v)}
                                  for k, v in self.command_overrides.items()},
        }


@dataclass
class DeviceType:
    id: str
    name: str
    revision: int
    server_clusters: dict[str, ClusterRequirement] = field(default_factory=dict)
    client_clusters: dict[str, ClusterRequirement] = field(default_factory=dict)

    @classmethod
    def from_json(cls, d: dict) -> "DeviceType":
        return cls(
            id=d["id"],
            name=d["name"],
            revision=d["revision"],
            server_clusters={k: ClusterRequirement.from_json(v)
                             for k, v in d.get("server_clusters", {}).items()},
            client_clusters={k: ClusterRequirement.from_json(v)
                             for k, v in d.get("client_clusters", {}).items()},
        )

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "revision": self.revision,
            "server_clusters": _map_to_json(self.server_clusters),
            "client_clusters": _map_to_json(self.client_clusters),
        }


@dataclass
class DataModel:
    spec_version: str
    clusters: dict[str, Cluster] = field(default_factory=dict)
    device_types: dict[str, DeviceType] = field(default_factory=dict)
    # The Base Device Type's clusters apply to every endpoint. It has no device
    # type id of its own, so it is stored separately rather than in
    # ``device_types``; consumers merge it into each endpoint's device type.
    base_device_type: DeviceType | None = None
    provenance: dict = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_json(cls, d: dict) -> "DataModel":
        base = d.get("base_device_type")
        return cls(
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            spec_version=d["spec_version"],
            provenance=d.get("provenance", {}),
            clusters={k: Cluster.from_json(v) for k, v in d.get("clusters", {}).items()},
            device_types={k: DeviceType.from_json(v)
                          for k, v in d.get("device_types", {}).items()},
            base_device_type=DeviceType.from_json(base) if base else None,
        )

    def to_json(self) -> dict:
        out = {
            "schema_version": self.schema_version,
            "spec_version": self.spec_version,
            "provenance": self.provenance,
            "clusters": {k: v.to_json() for k, v in self.clusters.items()},
            "device_types": {k: v.to_json() for k, v in self.device_types.items()},
        }
        if self.base_device_type is not None:
            out["base_device_type"] = self.base_device_type.to_json()
        return out

    def device_type_by_name(self, name: str) -> DeviceType | None:
        for dt in self.device_types.values():
            if dt.name.lower() == name.lower():
                return dt
        return None
