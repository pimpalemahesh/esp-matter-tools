# Copyright 2025 Espressif Systems (Shanghai) PTE LTD
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
"""Fill the maintained templates in place and write per-endpoint PICS.

Design decisions D15/D16: we annotate the authoritative CSA templates (never
generate from scratch), editing only ``<support>`` with stdlib ElementTree
(comments preserved) and copying the header block verbatim so diffs against the
template show only support changes.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .template_io import list_templates

logger = logging.getLogger(__name__)


@dataclass
class WriteSummary:
    files: list[str] = field(default_factory=list)
    supported: int = 0


def _fill_tree(src: Path, enabled: set[str]) -> tuple[ET.ElementTree, str, int]:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(str(src), parser)
    root = tree.getroot()
    count = 0
    for pi in root.iter("picsItem"):
        number = pi.find("itemNumber")
        support = pi.find("support")
        if number is None or support is None or not number.text:
            continue
        if number.text.strip() in enabled:
            support.text = "true"
            count += 1
    return tree, root.tag, count


def _verbatim_header(src: Path, root_tag: str) -> str:
    """Everything before the root element's opening tag (xml decl + comments)."""
    header: list[str] = []
    with open(src, encoding="utf-8") as f:
        for line in f:
            if f"<{root_tag}" in line:
                break
            header.append(line)
    return "".join(header)


def write_filled(src: Path, dst: Path, enabled: set[str]) -> int:
    tree, root_tag, count = _fill_tree(src, enabled)
    header = _verbatim_header(src, root_tag)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(header)
        tree.write(f, encoding="unicode")
        f.write("\n")
    return count


def write_pics(version: str, endpoints_enabled: dict[int, set[str]],
               out_dir: str | Path) -> WriteSummary:
    """Write filled templates per endpoint into ``out_dir/endpoint<N>/``.

    A template is written for an endpoint only if at least one of its items is
    enabled there (so each endpoint folder holds just its relevant PICS files).
    """
    out = Path(out_dir).expanduser()
    templates = list_templates(version)
    if not templates:
        raise FileNotFoundError(f"no templates found for version {version!r}")

    summary = WriteSummary()
    for endpoint, enabled in sorted(endpoints_enabled.items()):
        ep_dir = out / f"endpoint{endpoint}"
        for src in templates:
            tree, root_tag, count = _fill_tree(src, enabled)
            if count == 0:
                continue
            dst = ep_dir / src.name
            header = _verbatim_header(src, root_tag)
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(dst, "w", encoding="utf-8") as f:
                f.write(header)
                tree.write(f, encoding="unicode")
                f.write("\n")
            summary.files.append(str(dst))
            summary.supported += count
    return summary
