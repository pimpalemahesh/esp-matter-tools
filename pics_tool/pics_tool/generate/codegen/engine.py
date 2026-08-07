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
"""The single entry point every consumer (CLI, Web UI, ...) calls.

Same ``(selection, model, target, knowledge)`` -> same ``GeneratedOutput``, so
the CLI and the browser produce identical code.
"""

from __future__ import annotations

from esp_matter_datamodel.model.elements import DataModel

from .from_pics import build_plan
from .targets import get_target
from .targets.base import GeneratedOutput


def generate_code(selection, model: DataModel, *, target: str = "esp_matter",
                  knowledge=None) -> GeneratedOutput:
    """Render code for a PICS ``selection`` with the chosen output ``target``.

    ``knowledge`` overrides the target's default knowledge source (e.g. a live
    esp_matter component); ``None`` uses the target default.
    """
    plan = build_plan(selection, model)
    tgt = get_target(target)
    kb = knowledge if knowledge is not None else tgt.default_knowledge(plan.spec_version)
    return tgt.render(plan, kb)
