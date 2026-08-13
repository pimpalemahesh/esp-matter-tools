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
"""``esp-matter-datamodel`` CLI: build the JSON from spec XML, or validate it."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click

from .. import loader, validation
from ..ingest import build_data_model


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def main(verbose: bool) -> None:
    """Tooling for the shared Matter data-model JSON."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


@main.command("build-model")
@click.option(
    "--data-model-dir",
    required=True,
    help="Path to connectedhomeip 'data_model' directory.",
)
@click.option(
    "--version", "spec_version", required=True, help="Spec version, e.g. 1.6."
)
@click.option(
    "--output",
    type=click.Path(),
    help="Output JSON path (default: packaged datamodels/datamodel_<ver>.json).",
)
@click.option(
    "--no-validate", is_flag=True, help="Skip schema validation of the output."
)
def build_model(
    data_model_dir: str, spec_version: str, output: str | None, no_validate: bool
) -> None:
    """Parse spec XML into the versioned data-model JSON."""
    model = build_data_model(data_model_dir, spec_version)
    click.echo(
        f"Parsed {len(model.clusters)} clusters, {len(model.device_types)} device types"
        f" (base_device_type={'yes' if model.base_device_type else 'no'})."
    )

    if output is None:
        pkg_dir = Path(__file__).resolve().parent.parent / "datamodels"
        out_path = pkg_dir / f"datamodel_{spec_version}.json"
    else:
        out_path = Path(output)

    loader.dump(model, out_path, validate=not no_validate)
    click.echo(f"Wrote {out_path}")


@main.command("validate")
@click.argument("path", type=click.Path(exists=True))
def validate_cmd(path: str) -> None:
    """Validate a data-model JSON file against the schema."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validation.validate(data)
    click.echo(f"OK: {path} is valid (schema {data.get('schema_version')}).")


if __name__ == "__main__":
    main()
