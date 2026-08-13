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
"""The output-target port: what every code target implements + returns.

A target renders a neutral :class:`~pics_tool.generate.codegen.ir.DataModelPlan`
into a :class:`GeneratedOutput`. Adding a new output format = implement
:class:`CodeTarget` and register it; the IR and consumers are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GeneratedFile:
    path: str
    text: str


@dataclass
class GeneratedOutput:
    """What a consumer (CLI/UI) receives -- identical regardless of who asked."""

    target: str
    version: str
    primary: str  # the snippet to show / copy
    files: list[GeneratedFile] = field(default_factory=list)
    elements: list[dict] = field(
        default_factory=list
    )  # recap: {endpoint, cluster, name, kind}
    notes: list[str] = field(default_factory=list)
    exact: bool = False  # a knowledge source was consulted
    knowledge_source: str = ""  # e.g. "bundled esp_matter 1.5.1"
    unresolved: list[dict] = field(
        default_factory=list
    )  # selected elements omitted (no signature)


class CodeTarget:
    """Base class for output targets. Subclasses set ``name`` and implement ``render``."""

    name: str = ""

    def default_knowledge(self, version: str):
        """The knowledge source to use when the caller doesn't supply one.

        ``None`` means "no knowledge" -> the target degrades to placeholders.
        """
        return None

    def render(
        self, plan, knowledge=None
    ) -> GeneratedOutput:  # pragma: no cover - interface
        raise NotImplementedError
