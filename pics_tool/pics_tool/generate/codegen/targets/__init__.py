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
"""Registry of output code targets. Add a target by registering it in TARGETS."""

from .base import CodeTarget, GeneratedFile, GeneratedOutput
from .esp_matter.target import EspMatterTarget

TARGETS: dict[str, CodeTarget] = {t.name: t for t in (EspMatterTarget(),)}


def get_target(name: str) -> CodeTarget:
    try:
        return TARGETS[name]
    except KeyError:
        raise ValueError(f"unknown code target {name!r}; available: {sorted(TARGETS)}") from None


def list_targets() -> list[str]:
    return sorted(TARGETS)


__all__ = ["CodeTarget", "GeneratedOutput", "GeneratedFile", "get_target", "list_targets", "TARGETS"]
