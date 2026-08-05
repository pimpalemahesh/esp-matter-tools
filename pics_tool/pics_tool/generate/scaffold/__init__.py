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
"""Generate the esp-matter application data-model scaffold from PICS.

Turns a PICS selection (the clusters/features a device supports, already chosen
in the PICS tool) into the ``node::create`` / ``endpoint::<device_type>::create``
construction code the user would otherwise hand-write in ``app_main.cpp``.
"""

from .generator import ScaffoldResult, generate_scaffold

__all__ = ["generate_scaffold", "ScaffoldResult"]
