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
"""Access to the packaged JSON Schema and instance validation."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files


class SchemaValidationError(ValueError):
    """Raised when a data-model JSON instance does not match the schema."""


@lru_cache(maxsize=1)
def load_schema() -> dict:
    """Return the packaged ``datamodel.schema.json`` as a dict."""
    resource = files("esp_matter_datamodel").joinpath("schema/datamodel.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def validate(instance: dict) -> None:
    """Validate ``instance`` against the data-model schema.

    Raises :class:`SchemaValidationError` on the first violation.
    """
    import jsonschema  # imported lazily so importing the model needs no deps

    try:
        jsonschema.validate(instance=instance, schema=load_schema())
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise SchemaValidationError(f"{location}: {exc.message}") from exc
