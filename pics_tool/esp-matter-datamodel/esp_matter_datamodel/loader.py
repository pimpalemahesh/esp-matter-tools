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
"""The single, validating doorway consumers use to obtain a DataModel.

Consumers (e.g. a PICS generator) call :func:`load` or :func:`load_version`;
they never import :mod:`esp_matter_datamodel.ingest`. This is the seam that
makes the XML->JSON producer replaceable: any JSON that validates against the
schema loads here, whoever produced it.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from . import validation
from .model.elements import DataModel


def load(path: str | Path, *, validate: bool = True) -> DataModel:
    """Load a data-model JSON file, validating it against the schema by default."""
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if validate:
        validation.validate(data)
    return DataModel.from_json(data)


def load_version(version: str, *, validate: bool = True) -> DataModel:
    """Load a data-model shipped with the package for ``version`` (e.g. "1.6")."""
    resource = files("esp_matter_datamodel").joinpath(f"datamodels/datamodel_{version}.json")
    if not resource.is_file():
        raise FileNotFoundError(f"no packaged data model for version {version!r}")
    data = json.loads(resource.read_text(encoding="utf-8"))
    if validate:
        validation.validate(data)
    return DataModel.from_json(data)


def dump(model: DataModel, path: str | Path, *, validate: bool = True) -> None:
    """Serialize ``model`` to ``path`` as JSON (validating the result by default)."""
    data = model.to_json()
    if validate:
        validation.validate(data)
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
