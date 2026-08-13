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
"""Assemble a :class:`DataModel` from a connectedhomeip ``data_model/<ver>`` tree."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from xml.etree.ElementTree import Element
from xml.etree.ElementTree import parse as parse_xml

from ..model.elements import Cluster, DataModel, DeviceType
from .parser import parse_cluster, parse_device_type

logger = logging.getLogger(__name__)

_BASE_DEVICE_TYPE_NAME = "Base Device Type"


class IngestError(RuntimeError):
    """Raised when a spec-XML file cannot be parsed into the model."""


def build_data_model(data_model_dir: str | Path, version: str) -> DataModel:
    """Parse ``<data_model_dir>/<version>/{clusters,device_types}`` into a DataModel.

    Parse failures raise :class:`IngestError` (fail loudly) rather than being
    silently skipped, so the produced JSON is never quietly incomplete.
    """
    base = Path(data_model_dir).expanduser() / version
    clusters_dir = base / "clusters"
    device_types_dir = base / "device_types"
    if not clusters_dir.is_dir():
        raise IngestError(f"clusters directory not found: {clusters_dir}")

    clusters = _parse_clusters(clusters_dir)
    device_types, base_device_type = _parse_device_types(device_types_dir, clusters)

    provenance = _read_provenance(base)
    provenance["generated_from"] = f"data_model/{version}"

    return DataModel(
        spec_version=version,
        clusters=clusters,
        device_types=device_types,
        base_device_type=base_device_type,
        provenance=provenance,
    )


def _root_of(path: Path) -> Element:
    try:
        return parse_xml(path).getroot()
    except Exception as exc:  # noqa: BLE001 - re-raised with file context
        raise IngestError(f"failed to parse XML {path}: {exc}") from exc


def _normalize_cluster_name(name: str) -> str:
    name = name.strip()
    for suffix in (" Clusters", " Cluster"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _parse_clusters(clusters_dir: Path) -> dict[str, Cluster]:
    # First pass: parse every cluster file (including abstract, id-less bases).
    parsed: list[tuple[Element, Cluster]] = []
    for path in sorted(clusters_dir.glob("*.xml")):
        root = _root_of(path)
        if root.tag != "cluster":
            logger.debug(
                "skipping non-cluster XML: %s (root <%s>)", path.name, root.tag
            )
            continue
        try:
            cluster = parse_cluster(root)
        except Exception as exc:  # noqa: BLE001
            raise IngestError(f"failed to parse cluster {path.name}: {exc}") from exc
        parsed.append((root, cluster))

    # Index every parsed cluster by normalized name so derived clusters can
    # resolve their baseCluster (which may be an abstract base or a real cluster).
    by_name: dict[str, Cluster] = {}
    for _root, cluster in parsed:
        by_name.setdefault(_normalize_cluster_name(cluster.name), cluster)

    clusters: dict[str, Cluster] = {}
    for root, cluster in parsed:
        if not cluster.id:
            continue  # abstract base cluster: template only, not a standalone entry
        classification = root.find("classification")
        if (
            classification is not None
            and classification.attrib.get("hierarchy") == "derived"
        ):
            base_name = classification.attrib.get("baseCluster", "")
            base = by_name.get(_normalize_cluster_name(base_name))
            if base is None:
                logger.warning(
                    "derived cluster %s: base %r not found; no inheritance",
                    cluster.name,
                    base_name,
                )
            else:
                cluster = _merge_inherited(cluster, base)
        if cluster.id in clusters:
            logger.warning(
                "duplicate cluster id %s (%s); overwriting", cluster.id, cluster.name
            )
        clusters[cluster.id] = cluster
    logger.info("parsed %d clusters", len(clusters))
    return clusters


def _merge_inherited(derived: Cluster, base: Cluster) -> Cluster:
    """Return ``derived`` with ``base``'s elements merged in (derived wins)."""

    def merged(base_map: dict, derived_map: dict) -> dict:
        out = dict(base_map)
        out.update(derived_map)
        return out

    return dataclasses.replace(
        derived,
        features=merged(base.features, derived.features),
        attributes=merged(base.attributes, derived.attributes),
        accepted_commands=merged(base.accepted_commands, derived.accepted_commands),
        generated_commands=merged(base.generated_commands, derived.generated_commands),
        events=merged(base.events, derived.events),
    )


def _parse_device_types(
    device_types_dir: Path, clusters: dict[str, Cluster]
) -> tuple[dict[str, DeviceType], DeviceType | None]:
    device_types: dict[str, DeviceType] = {}
    base_device_type: DeviceType | None = None
    if not device_types_dir.is_dir():
        logger.warning("device_types directory not found: %s", device_types_dir)
        return device_types, base_device_type

    for path in sorted(device_types_dir.glob("*.xml")):
        root = _root_of(path)
        if root.tag != "deviceType":
            continue
        try:
            device_type = parse_device_type(root, clusters)
        except Exception as exc:  # noqa: BLE001
            raise IngestError(
                f"failed to parse device type {path.name}: {exc}"
            ) from exc
        if device_type.name == _BASE_DEVICE_TYPE_NAME:
            base_device_type = device_type
        else:
            device_types[device_type.id] = device_type
    logger.info(
        "parsed %d device types (base_device_type=%s)",
        len(device_types),
        base_device_type is not None,
    )
    return device_types, base_device_type


def _read_provenance(base: Path) -> dict:
    provenance: dict = {}
    spec_sha = base / "spec_sha"
    scraper = base / "scraper_version"
    if spec_sha.is_file():
        provenance["spec_sha"] = spec_sha.read_text(encoding="utf-8").strip()
    if scraper.is_file():
        provenance["scraper_version"] = scraper.read_text(encoding="utf-8").strip()
    return provenance
