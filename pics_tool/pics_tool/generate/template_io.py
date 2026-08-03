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
"""Read the maintained CSA PICS templates (incl. Base.xml).

Provides a light read-only view of the ``<picsItem>`` entries (used by the
MCORE engine to evaluate Base.xml conds). The writer (see writer.py) edits the
XML in place separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from pathlib import Path


@dataclass
class PicsItem:
    number: str
    statuses: list[tuple[str, str]] = field(default_factory=list)  # (status_text, cond)
    support: str = "false"

    def is_pure_optional_leaf(self) -> bool:
        """True if this is a plain device-fact flag (all optional, no condition)."""
        return bool(self.statuses) and all(
            text != "M" and not cond for text, cond in self.statuses
        )

    def unconditional_mandatory(self) -> bool:
        return any(text == "M" and not cond for text, cond in self.statuses)


def templates_dir(version: str) -> Path:
    return Path(str(files("pics_tool").joinpath(f"templates/{version}")))


def list_templates(version: str) -> list[Path]:
    return sorted(templates_dir(version).glob("*.xml"))


@lru_cache(maxsize=4)
def known_item_numbers(version: str) -> frozenset[str]:
    """Every PICS itemNumber that exists in this version's templates.

    The engine derives codes from the data model, but a code is only claimable
    (question text, export, CSA validation) if some template carries it. Codes
    outside this set -- e.g. the OTA clusters, whose test plan uses MCORE.OTA.*
    / MCORE.BDX.* instead of the per-element grid -- must be filtered out of
    anything user-facing.
    """
    numbers: set[str] = set()
    for path in list_templates(version):
        for item in parse_pics_items(path):
            numbers.add(item.number)
    return frozenset(numbers)


def base_template_path(version: str) -> Path:
    return templates_dir(version) / "Base.xml"


def parse_pics_items(path: str | Path) -> list[PicsItem]:
    """Parse all ``<picsItem>`` entries from a template (any section)."""
    import xml.etree.ElementTree as ET

    root = ET.parse(str(path)).getroot()
    items: list[PicsItem] = []
    for pi in root.iter("picsItem"):
        number_el = pi.find("itemNumber")
        if number_el is None or not (number_el.text and number_el.text.strip()):
            continue
        statuses = [((st.text or "").strip(), (st.attrib.get("cond", "") or "").strip())
                    for st in pi.findall("status")]
        support_el = pi.find("support")
        support = (support_el.text or "").strip() if support_el is not None else "false"
        items.append(PicsItem(number_el.text.strip(), statuses, support))
    return items
