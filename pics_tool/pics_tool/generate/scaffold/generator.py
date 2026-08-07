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
"""Back-compat entry point for the esp-matter scaffold.

The generator has been refactored into the pluggable code-generation engine
(``pics_tool.generate.codegen``): a PICS ``Selection`` becomes a neutral
``DataModelPlan`` (``codegen.from_pics``), which the ``esp_matter`` target renders.
This module keeps the original ``generate_scaffold`` / ``ScaffoldResult`` API so
existing callers and tests are unchanged.
"""

from __future__ import annotations

from pathlib import Path

from ..codegen.from_pics import build_plan
from ..codegen.targets.esp_matter.target import (  # noqa: F401  (re-exported)
    DeviceTypeInfo, EndpointScaffold, EspMatterTarget, OptionalElem,
    OptionalFeature, OptionalSide, ScaffoldResult)

_TARGET = EspMatterTarget()


def generate_scaffold(selection, model, output_dir: str | Path | None = None,
                      knowledge=None) -> ScaffoldResult:
    """Build the esp-matter data-model construction snippet for ``selection``.

    ``selection`` is a :class:`pics_tool.generate.selection.Selection`. If
    ``output_dir`` is given, the snippet is also written to
    ``<output_dir>/app_data_model.cpp``. ``knowledge`` overrides the esp_matter
    signature source (e.g. a live component); ``None`` uses the bundled caps for
    the version, or placeholders if none is shipped.
    """
    plan = build_plan(selection, model)
    if knowledge is None:
        knowledge = _TARGET.default_knowledge(plan.spec_version)
    endpoints = _TARGET.build_endpoints(plan)
    snippet = _TARGET.render_snippet(endpoints, knowledge)

    written: str | None = None
    if output_dir is not None:
        out = Path(output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        dst = out / "app_data_model.cpp"
        dst.write_text(snippet, encoding="utf-8")
        written = str(dst)

    return ScaffoldResult(
        snippet=snippet, file=written, endpoints=endpoints,
        exact=knowledge is not None,
        knowledge_source=getattr(knowledge, "source_label", None) or "none (placeholders)")


__all__ = ["generate_scaffold", "ScaffoldResult", "EndpointScaffold", "DeviceTypeInfo",
           "OptionalFeature", "OptionalElem", "OptionalSide"]
