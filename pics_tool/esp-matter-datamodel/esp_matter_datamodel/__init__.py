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
"""esp-matter-datamodel: a tool-neutral, versioned Matter data model as JSON.

The XML-to-JSON layer shared across esp-matter-tools. It defines the standard
schema, the (single) spec-XML parser, and a validating loader. It contains no
PICS (or any other tool) concepts.
"""

from .model.elements import SCHEMA_VERSION, DataModel

__all__ = ["DataModel", "SCHEMA_VERSION"]
