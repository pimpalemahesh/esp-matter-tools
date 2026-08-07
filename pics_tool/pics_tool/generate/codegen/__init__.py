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
"""Code-generation engine: turn a target-neutral data-model plan into code.

Ports & adapters:
  input adapters (e.g. PICS -> ``from_pics.build_plan``) produce a neutral
  :class:`~pics_tool.generate.codegen.ir.DataModelPlan`; the :func:`generate_code`
  facade hands it to a selected output *target* (adapter) from the registry; each
  target renders the plan, consulting its own optional *knowledge* source. This
  keeps code generation independent of PICS and pluggable across output formats.
"""

from .engine import generate_code
from .targets import get_target, list_targets

__all__ = ["generate_code", "get_target", "list_targets"]
