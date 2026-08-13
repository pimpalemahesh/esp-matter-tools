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

from esp_matter_datamodel import boolexpr

from .template_io import list_templates

logger = logging.getLogger(__name__)


@dataclass
class WriteSummary:
    files: list[str] = field(default_factory=list)
    supported: int = 0
    pixits: int = 0


def _pixits_of(src: Path, enabled: set[str]) -> list[tuple[str, str]]:
    """(itemNumber, question text) of every APPLICABLE PIXIT in a template.

    Inapplicable ones (cond false for this endpoint) are exported as "n/a" and
    need no manual value, so they stay off the checklist.
    """
    out = []
    for px in ET.parse(str(src)).getroot().iter("pixitItem"):
        num = (px.findtext("itemNumber") or "").strip()
        if num and _pixit_applicable(px, enabled):
            out.append((num, " ".join((px.findtext("feature") or "").split())))
    return out


def _pixit_checklist(
    per_endpoint: dict[int, list[tuple[str, list[tuple[str, str]]]]],
) -> str:
    """Render PIXIT_CHECKLIST.md: the test-bed values only the engineer can fill.

    The CSA PICS validator flags every unfilled applicable PIXIT as a warning;
    this file turns those warnings into an explicit TODO list.
    """
    lines = [
        "# PIXIT checklist",
        "",
        "PIXITs are test-bed / product-specific values (network credentials,",
        "timings, product info). They CANNOT be generated -- fill them in the",
        "CSA PICS tool / Test Harness before running certification tests.",
        "The PICS validator reports each applicable unfilled PIXIT as a warning.",
        "",
    ]
    for endpoint, files in sorted(per_endpoint.items()):
        lines.append(f"## endpoint{endpoint}")
        for fname, pixits in files:
            lines.append(f"\n### {fname}")
            for num, feature in pixits:
                lines.append(f"- [ ] `{num}`" + (f" -- {feature}" if feature else ""))
        lines.append("")
    return "\n".join(lines) + "\n"


def _pixit_applicable(px: ET.Element, enabled: set[str]) -> bool:
    """A PIXIT applies when any of its status conds holds for the enabled set."""
    statuses = px.findall("status")
    if not statuses:
        return True
    for s in statuses:
        cond = (s.attrib.get("cond") or "").strip()
        if not cond:
            return True
        try:
            if boolexpr.evaluate(boolexpr.parse(cond), lambda a: a in enabled):
                return True
        except boolexpr.ExpressionSyntaxError:
            return True  # unresolvable: safer to keep it as a value to fill
    return False


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
    # PIXITs whose condition is false for this endpoint are NOT APPLICABLE:
    # export them as "n/a" (matching the hand-curated CSA reference); leaving
    # the template's 0x00 reads as "value provided" and trips the validator's
    # dependency check (e.g. PIXIT.OO.ENDPOINT on a client-only On/Off file).
    for px in root.iter("pixitItem"):
        support = px.find("support")
        if support is not None and not _pixit_applicable(px, enabled):
            support.text = "n/a"
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


def write_pics(
    version: str, endpoints_enabled: dict[int, set[str]], out_dir: str | Path
) -> WriteSummary:
    """Write filled templates per endpoint into ``out_dir/endpoint<N>/``.

    A template is written for an endpoint only if at least one of its items is
    enabled there (so each endpoint folder holds just its relevant PICS files).
    """
    out = Path(out_dir).expanduser()
    templates = list_templates(version)
    if not templates:
        raise FileNotFoundError(f"no templates found for version {version!r}")

    summary = WriteSummary()
    pixits_by_ep: dict[int, list[tuple[str, list[tuple[str, str]]]]] = {}
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
            pixits = _pixits_of(src, enabled)
            if pixits:
                pixits_by_ep.setdefault(endpoint, []).append((src.name, pixits))
                summary.pixits += len(pixits)

    if pixits_by_ep:
        checklist = out / "PIXIT_CHECKLIST.md"
        checklist.parent.mkdir(parents=True, exist_ok=True)
        checklist.write_text(_pixit_checklist(pixits_by_ep), encoding="utf-8")
        summary.files.append(str(checklist))
    return summary
