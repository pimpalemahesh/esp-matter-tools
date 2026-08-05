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
"""Phase 1: the spec-XML -> data-model-JSON producer.

This subpackage is the *only* place that parses connectedhomeip spec XML. It is
deliberately isolated: nothing else in the package imports from ``ingest`` at
runtime, so a future externally-supplied JSON could make it removable.
"""

from .builder import build_data_model

__all__ = ["build_data_model"]
